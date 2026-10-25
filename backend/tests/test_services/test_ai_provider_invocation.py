"""Compatibility contract for analysis provider invocation and auth failover."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.ai.provider_invocation import (
    ProviderInvocationInput,
    invoke_analysis_provider,
)


def runtime(config_id=11, model="analysis-primary"):
    return SimpleNamespace(
        model_config_id=config_id,
        provider="openai-compatible",
        model_name=model,
        base_url="https://example.test/v1",
        api_key="synthetic-key",
    )


def payload(**overrides):
    values = dict(
        db=SimpleNamespace(),
        runtime=runtime(),
        chat=AsyncMock(return_value={"content": "ok", "model": "analysis-primary"}),
        logger=logging.getLogger("app.services.ai_service"),
        wrong_question_id=7,
        force=True,
        visual=True,
        question={"stem": "题干"},
        wrong_answer="B",
        correct_answer="A",
        image_data_urls=["data:image/png;base64,c3lu"],
        answer_grounding={"answer": "A"},
        model_timeout_sec=150,
        max_tokens=1200,
        timeout_guard_sec=3,
        resolve_runtime=AsyncMock(return_value=None),
        quarantine_runtime=AsyncMock(),
        failure_response=lambda **kwargs: kwargs,
    )
    values.update(overrides)
    return ProviderInvocationInput(**values)


@pytest.mark.asyncio
async def test_success_passes_analysis_contract_to_selected_model():
    item = payload()

    outcome = await invoke_analysis_provider(item)

    assert outcome.result == {"content": "ok", "model": "analysis-primary"}
    assert outcome.runtime is item.runtime
    item.chat.assert_awaited_once()
    args, kwargs = item.chat.await_args
    assert args[0][0]["role"] == "system"
    assert kwargs == {
        "temperature": 0.2,
        "model": "analysis-primary",
        "api_key": "synthetic-key",
        "base_url": "https://example.test/v1",
        "provider": "openai-compatible",
        "timeout": 150,
        "max_tokens": 1200,
        "prefer_direct_answer": True,
    }
    item.quarantine_runtime.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_auth_failure_returns_typed_response_without_failover():
    item = payload(chat=AsyncMock(side_effect=RuntimeError("provider overloaded")))

    outcome = await invoke_analysis_provider(item)

    assert outcome == {
        "error_code": "ai_provider_error",
        "retryable": True,
        "failure_model": "fallback",
    }
    item.quarantine_runtime.assert_not_awaited()
    item.resolve_runtime.assert_not_awaited()


@pytest.mark.asyncio
async def test_auth_failure_quarantines_and_tries_fallback_once():
    fallback = runtime(config_id=12, model="analysis-fallback")
    item = payload(
        chat=AsyncMock(side_effect=[
            RuntimeError("invalid_api_key"),
            {"content": "fallback-ok", "model": "analysis-fallback"},
        ]),
        resolve_runtime=AsyncMock(return_value=fallback),
    )

    outcome = await invoke_analysis_provider(item)

    assert outcome.result == {"content": "fallback-ok", "model": "analysis-fallback"}
    assert outcome.runtime is fallback
    item.quarantine_runtime.assert_awaited_once_with(item.runtime)
    item.resolve_runtime.assert_awaited_once_with(
        item.db,
        excluded_model_config_ids={11, 12},
    )
    assert item.chat.await_count == 2
    assert item.chat.await_args_list[1].kwargs["model"] == "analysis-fallback"


@pytest.mark.asyncio
async def test_auth_failure_without_fallback_preserves_failure_response():
    item = payload(
        chat=AsyncMock(side_effect=RuntimeError("authentication failed")),
        resolve_runtime=AsyncMock(return_value=None),
    )

    outcome = await invoke_analysis_provider(item)

    assert outcome == {
        "error_code": "ai_provider_auth_failed",
        "retryable": False,
        "failure_model": "fallback",
    }
    item.quarantine_runtime.assert_awaited_once_with(item.runtime)


@pytest.mark.asyncio
async def test_fallback_auth_failure_quarantines_fallback_model_too():
    fallback = runtime(config_id=12, model="analysis-fallback")
    item = payload(
        chat=AsyncMock(side_effect=[
            RuntimeError("invalid_api_key"),
            RuntimeError("403 forbidden"),
        ]),
        resolve_runtime=AsyncMock(return_value=fallback),
    )

    outcome = await invoke_analysis_provider(item)

    assert outcome == {
        "error_code": "ai_provider_auth_failed",
        "retryable": False,
        "failure_model": "fallback",
    }
    assert [call.args[0] for call in item.quarantine_runtime.await_args_list] == [
        item.runtime,
        fallback,
    ]


@pytest.mark.asyncio
async def test_timeout_and_fallback_timeout_return_retryable_response():
    fallback = runtime(config_id=12, model="analysis-fallback")

    first = payload(chat=AsyncMock(side_effect=TimeoutError()))
    first_outcome = await invoke_analysis_provider(first)
    assert first_outcome.pop("duration_ms") >= 0
    assert first_outcome == {
        "error_code": "ai_provider_timeout",
        "retryable": True,
        "failure_model": "timeout",
    }

    second = payload(
        chat=AsyncMock(side_effect=[RuntimeError("invalid_api_key"), TimeoutError()]),
        resolve_runtime=AsyncMock(return_value=fallback),
    )
    second_outcome = await invoke_analysis_provider(second)
    assert second_outcome.pop("duration_ms") >= 0
    assert second_outcome == {
        "error_code": "ai_provider_timeout",
        "retryable": True,
        "failure_model": "timeout",
    }
    second.quarantine_runtime.assert_awaited_once_with(second.runtime)
