"""Invoke the selected analysis model and own one auth-failure failover.

The multimodal message stays vendor-neutral: protocol dialects are negotiated
by the OpenAI-compatible client rather than from provider/model-name checks.
Authentication failures quarantine the saved model revision and try the next
configured analysis model once, so one invalid credential cannot fail every
wrong-question prewarm while a healthy fallback model is available.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.ai.prompts import build_error_analysis
from app.services.ai.analysis_availability import (
    AnalysisUnavailableError,
    note_failure,
    require_runtime_verified,
)
from app.services.ai.provider_exception import classify_ai_provider_exception

Chat = Callable[..., Awaitable[dict]]
RuntimeResolver = Callable[..., Awaitable[Any]]
Quarantiner = Callable[[Any], Awaitable[None]]
FailureResponse = Callable[..., dict]


@dataclass(slots=True)
class ProviderInvocationInput:
    db: Any
    runtime: Any
    chat: Chat
    logger: logging.Logger
    wrong_question_id: int
    force: bool
    visual: bool
    question: Any
    wrong_answer: str
    correct_answer: str
    image_data_urls: list[str]
    answer_grounding: Any
    model_timeout_sec: int
    max_tokens: int
    timeout_guard_sec: int
    resolve_runtime: RuntimeResolver
    quarantine_runtime: Quarantiner
    failure_response: FailureResponse


@dataclass(slots=True)
class ProviderInvocationResult:
    result: dict
    runtime: Any


async def invoke_analysis_provider(
    payload: ProviderInvocationInput,
) -> ProviderInvocationResult | dict:
    runtime = payload.runtime
    attempted_model_ids = _attempted_model_ids(runtime)
    invoke_started = time.monotonic()
    try:
        result = await _invoke_runtime(payload, runtime)
    except TimeoutError as exc:
        await note_failure(runtime, exc)
        return _timeout_failure(
            payload, int((time.monotonic() - invoke_started) * 1000)
        )
    except AnalysisUnavailableError as exc:
        return _availability_failure(payload, exc)
    except Exception as exc:
        return await _failure_or_failover(payload, runtime, attempted_model_ids, exc)
    return ProviderInvocationResult(result, runtime)


def _attempted_model_ids(runtime) -> set[int]:
    if runtime.model_config_id is None:
        return set()
    return {int(runtime.model_config_id)}


async def _invoke_runtime(payload: ProviderInvocationInput, selected_runtime):
    await require_runtime_verified(selected_runtime)
    messages = build_error_analysis(
        payload.question,
        payload.wrong_answer,
        payload.correct_answer,
        answer_grounding=payload.answer_grounding,
        image_data_urls=payload.image_data_urls,
    )
    async with asyncio.timeout(payload.model_timeout_sec + payload.timeout_guard_sec):
        return await payload.chat(
            messages,
            temperature=0.2,
            model=selected_runtime.model_name,
            api_key=selected_runtime.api_key,
            base_url=selected_runtime.base_url,
            provider=selected_runtime.provider,
            timeout=payload.model_timeout_sec,
            max_tokens=payload.max_tokens,
            prefer_direct_answer=True,
        )


async def _failure_or_failover(
    payload: ProviderInvocationInput,
    runtime,
    attempted_model_ids: set[int],
    exc: Exception,
) -> dict:
    await note_failure(runtime, exc)
    error_code, retryable, failure_model = classify_ai_provider_exception(
        exc, visual=payload.visual
    )
    if error_code not in {"ai_provider_auth_failed", "ai_provider_quota_exceeded"}:
        _log_provider_failure(payload, runtime, exc, error_code, retryable)
        return payload.failure_response(
            error_code=error_code,
            retryable=retryable,
            failure_model=failure_model,
        )
    return await _auth_failover(
        payload, runtime, attempted_model_ids, error_code, retryable, failure_model
    )


def _log_provider_failure(
    payload: ProviderInvocationInput,
    runtime,
    exc: Exception,
    error_code: str,
    retryable: bool,
) -> None:
    payload.logger.warning(
        "ai.error_analysis.provider_failed wq_id=%s force=%s visual=%s "
        "model_config_id=%s error_code=%s retryable=%s err_type=%s",
        payload.wrong_question_id,
        payload.force,
        payload.visual,
        runtime.model_config_id,
        error_code,
        retryable,
        type(exc).__name__,
    )


async def _auth_failover(
    payload: ProviderInvocationInput,
    runtime,
    attempted_model_ids: set[int],
    error_code: str,
    retryable: bool,
    failure_model: str,
) -> dict:
    await payload.quarantine_runtime(runtime)
    fallback_runtime = await payload.resolve_runtime(
        payload.db,
        excluded_model_config_ids=attempted_model_ids,
    )
    if fallback_runtime is None:
        return _auth_failure_without_fallback(
            payload, runtime, error_code, retryable, failure_model
        )
    _log_auth_failover(payload, runtime, fallback_runtime)
    attempted_model_ids.update(_attempted_model_ids(fallback_runtime))
    return await _invoke_fallback(payload, fallback_runtime)


def _auth_failure_without_fallback(
    payload: ProviderInvocationInput,
    runtime,
    error_code: str,
    retryable: bool,
    failure_model: str,
) -> dict:
    payload.logger.warning(
        "ai.error_analysis.auth_failed wq_id=%s force=%s visual=%s "
        "model_config_id=%s provider=%s model=%s fallback_model=none",
        payload.wrong_question_id,
        payload.force,
        payload.visual,
        runtime.model_config_id,
        runtime.provider,
        runtime.model_name,
    )
    return payload.failure_response(
        error_code=error_code,
        retryable=retryable,
        failure_model=failure_model,
    )


def _log_auth_failover(
    payload: ProviderInvocationInput, runtime, fallback_runtime
) -> None:
    payload.logger.warning(
        "ai.error_analysis.auth_failover wq_id=%s from_model_config_id=%s "
        "to_model_config_id=%s from_model=%s to_model=%s",
        payload.wrong_question_id,
        runtime.model_config_id,
        fallback_runtime.model_config_id,
        runtime.model_name,
        fallback_runtime.model_name,
    )


async def _invoke_fallback(
    payload: ProviderInvocationInput, fallback_runtime
) -> ProviderInvocationResult | dict:
    failover_started = time.monotonic()
    try:
        result = await _invoke_runtime(payload, fallback_runtime)
    except TimeoutError as exc:
        await note_failure(fallback_runtime, exc)
        elapsed_timeout_ms = int((time.monotonic() - failover_started) * 1000)
        return _failover_timeout_failure(payload, fallback_runtime, elapsed_timeout_ms)
    except AnalysisUnavailableError as exc:
        return _availability_failure(payload, exc)
    except Exception as exc:
        return await _fallback_failure(payload, fallback_runtime, exc)
    return ProviderInvocationResult(result, fallback_runtime)


def _availability_failure(
    payload: ProviderInvocationInput, exc: AnalysisUnavailableError
) -> dict:
    return payload.failure_response(
        error_code="ai_service_unavailable",
        retryable=False,
        failure_model="availability",
        availability=exc.state,
    )


def _timeout_failure(payload: ProviderInvocationInput, elapsed_timeout_ms: int) -> dict:
    payload.logger.warning(
        "ai.error_analysis.timeout wq_id=%s force=%s visual=%s timeout_sec=%s elapsed_ms=%s",
        payload.wrong_question_id,
        payload.force,
        payload.visual,
        payload.model_timeout_sec,
        elapsed_timeout_ms,
    )
    return payload.failure_response(
        error_code="ai_provider_timeout",
        retryable=True,
        failure_model="timeout",
        duration_ms=elapsed_timeout_ms,
    )


def _failover_timeout_failure(
    payload: ProviderInvocationInput, runtime, elapsed_timeout_ms: int
) -> dict:
    payload.logger.warning(
        "ai.error_analysis.failover_timeout wq_id=%s model_config_id=%s "
        "timeout_sec=%s elapsed_ms=%s",
        payload.wrong_question_id,
        runtime.model_config_id,
        payload.model_timeout_sec,
        elapsed_timeout_ms,
    )
    return payload.failure_response(
        error_code="ai_provider_timeout",
        retryable=True,
        failure_model="timeout",
        duration_ms=elapsed_timeout_ms,
    )


async def _fallback_failure(
    payload: ProviderInvocationInput, runtime, exc: Exception
) -> dict:
    await note_failure(runtime, exc)
    error_code, retryable, failure_model = classify_ai_provider_exception(
        exc, visual=payload.visual
    )
    if error_code == "ai_provider_auth_failed":
        await payload.quarantine_runtime(runtime)
    payload.logger.warning(
        "ai.error_analysis.failover_failed wq_id=%s force=%s visual=%s "
        "model_config_id=%s error_code=%s retryable=%s err_type=%s",
        payload.wrong_question_id,
        payload.force,
        payload.visual,
        runtime.model_config_id,
        error_code,
        retryable,
        type(exc).__name__,
    )
    return payload.failure_response(
        error_code=error_code,
        retryable=retryable,
        failure_model=failure_model,
    )
