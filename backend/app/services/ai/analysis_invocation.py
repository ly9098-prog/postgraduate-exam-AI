"""Provider invocation assembly for a prepared AI error analysis."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.analysis_provider_failure import build_provider_failure_response
from app.services.ai.provider_invocation import (
    ProviderInvocationInput,
    ProviderInvocationResult,
    invoke_analysis_provider,
)


@dataclass(slots=True)
class AnalysisInvocationRequest:
    db: AsyncSession
    wrong_question: Any
    question: Any
    context: dict
    runtime: Any
    image_data_urls: list[str]
    requires_visual: bool
    prompt_grounding: Any
    input_signature: str
    model_signature: str | None
    force: bool
    model_timeout_sec: int | float
    max_tokens: int
    timeout_guard_sec: int
    logger: Logger
    chat: Callable[..., Awaitable[dict]]
    resolve_runtime: Callable[..., Awaitable[Any]]
    quarantine_runtime: Callable[[Any], Awaitable[None]]
    cached_response: Callable[..., dict | None]


async def invoke_prepared_analysis(
    request: AnalysisInvocationRequest,
) -> ProviderInvocationResult | dict:
    # Keep provider selection and its one auth-failure failover beside the
    # cache/persistence contract so model selection remains observable.
    return await invoke_analysis_provider(
        ProviderInvocationInput(
            db=request.db,
            runtime=request.runtime,
            chat=request.chat,
            logger=request.logger,
            wrong_question_id=request.wrong_question.id,
            force=request.force,
            visual=bool(request.image_data_urls),
            question=request.context["question"],
            wrong_answer=request.wrong_question.wrong_answer,
            correct_answer=request.question.answer,
            image_data_urls=request.image_data_urls,
            answer_grounding=request.prompt_grounding,
            model_timeout_sec=request.model_timeout_sec,
            max_tokens=request.max_tokens,
            timeout_guard_sec=request.timeout_guard_sec,
            resolve_runtime=request.resolve_runtime,
            quarantine_runtime=request.quarantine_runtime,
            failure_response=build_provider_failure_response(
                wrong_question=request.wrong_question,
                requires_visual=request.requires_visual,
                input_signature=request.input_signature,
                model_signature=request.model_signature,
                effective_force=request.force,
                image_data_urls=request.image_data_urls,
                cached_response=request.cached_response,
            ),
        )
    )
