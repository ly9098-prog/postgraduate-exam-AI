"""Contract for assembled prepared-analysis provider invocations."""

from __future__ import annotations

import logging
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.schemas.ai import AiResponse
from app.services.ai import analysis_orchestration, analysis_review_invocation
from app.services.ai.analysis_invocation import (
    AnalysisInvocationRequest,
    invoke_prepared_analysis,
)
from app.services.ai.provider_invocation import ProviderInvocationResult
from tests.test_services.analysis_orchestration_support import harness


def request(**overrides):
    values = dict(
        db="db",
        wrong_question=SimpleNamespace(id=7, wrong_answer="A"),
        question=SimpleNamespace(id=3, answer="B"),
        context={"question": {"id": 3}},
        runtime=SimpleNamespace(model_config_id=11),
        image_data_urls=[],
        requires_visual=False,
        prompt_grounding={"answer": "B"},
        input_signature="input",
        model_signature="model",
        force=True,
        model_timeout_sec=30,
        max_tokens=800,
        timeout_guard_sec=3,
        logger=None,
        chat=None,
        resolve_runtime=None,
        quarantine_runtime=None,
        cached_response=lambda *_args, **_kwargs: {"old": "cache"},
    )
    values.update(overrides)
    return AnalysisInvocationRequest(**values)


@pytest.mark.asyncio
async def test_prepared_invocation_uses_exact_provider_contract(monkeypatch):
    captured = {}

    async def invoke(payload):
        captured["payload"] = payload
        return ProviderInvocationResult({"content": "raw"}, payload.runtime)

    monkeypatch.setattr(
        "app.services.ai.analysis_invocation.invoke_analysis_provider", invoke
    )
    item = request()

    result = await invoke_prepared_analysis(item)

    assert result.result == {"content": "raw"}
    payload = captured["payload"]
    assert payload.db == "db"
    assert payload.wrong_question_id == 7
    assert payload.force is True
    assert payload.visual is False
    assert payload.question == {"id": 3}
    assert payload.wrong_answer == "A"
    assert payload.correct_answer == "B"
    assert payload.answer_grounding == {"answer": "B"}
    assert payload.model_timeout_sec == 30
    assert payload.max_tokens == 800
    assert payload.timeout_guard_sec == 3


@pytest.mark.asyncio
async def test_provider_failure_preserves_matching_force_cache(monkeypatch):
    async def invoke(provider_payload):
        return provider_payload.failure_response(
            error_code="ai_provider_timeout",
            retryable=True,
            failure_model="timeout",
            duration_ms=25,
        )

    monkeypatch.setattr(
        "app.services.ai.analysis_invocation.invoke_analysis_provider", invoke
    )
    captured_payload = None

    async def capture_invoke(provider_payload):
        nonlocal captured_payload
        captured_payload = provider_payload
        return await invoke(provider_payload)

    monkeypatch.setattr(
        "app.services.ai.analysis_invocation.invoke_analysis_provider", capture_invoke
    )
    response = await invoke_prepared_analysis(request(force=True))
    assert captured_payload is not None

    assert response == {
        "old": "cache",
        "force_regenerated": False,
        "cache_preserved": True,
        "error_code": "ai_provider_timeout",
        "retryable": True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error_code", "retryable"),
    [
        (RuntimeError("HTTP 403 Forbidden"), "ai_provider_auth_failed", False),
        (RuntimeError("HTTP 401 Unauthorized"), "ai_provider_auth_failed", False),
        (RuntimeError("HTTP 429 Too Many Requests"), "ai_provider_rate_limited", True),
        (
            RuntimeError("API Error: 503 Service Unavailable"),
            "ai_provider_transient",
            True,
        ),
        (TimeoutError(), "ai_provider_timeout", True),
    ],
)
@pytest.mark.parametrize("preserve_cache", [False, True])
async def test_provider_failure_reaches_api_response_without_review_and_releases_lease(
    monkeypatch, failure, error_code, retryable, preserve_cache
):
    h = harness(monkeypatch)
    monkeypatch.setattr(
        "app.services.ai.provider_invocation.require_runtime_verified",
        AsyncMock(),
    )
    old_cache = {
        "content": {"mistake_diagnosis": "previous analysis"},
        "model": "cached",
        "from_cache": True,
        "tokens_used": 0,
        "duration_ms": 0,
        "generated_at": "2026-11-01T00:00:00+00:00",
    }
    item = request(
        runtime=SimpleNamespace(
            model_config_id=11,
            provider="synthetic",
            model_name="analysis",
            api_key="test-only",
            base_url="https://example.test/v1",
        ),
        chat=AsyncMock(side_effect=failure),
        resolve_runtime=AsyncMock(return_value=None),
        quarantine_runtime=AsyncMock(),
        logger=logging.getLogger(__name__),
        cached_response=lambda *_args, **_kwargs: old_cache if preserve_cache else None,
    )
    for field in fields(item):
        setattr(h.request, field.name, getattr(item, field.name))
    h.request.effective_force = True
    h.request.parse_content = Mock(
        side_effect=AssertionError("must not review a failure")
    )
    h.inputs.context = item.context
    h.inputs.model_timeout_sec = item.model_timeout_sec
    h.inputs.expected_answer_check = None
    h.inputs.answer_grounding = None
    monkeypatch.setattr(
        analysis_orchestration,
        "invoke_and_review_analysis",
        analysis_review_invocation.invoke_and_review_analysis,
    )
    monkeypatch.setattr(
        analysis_orchestration,
        "resolve_reviewed_analysis_outcome",
        analysis_review_invocation.resolve_reviewed_analysis_outcome,
    )

    response = await analysis_orchestration.execute_locked_analysis(h.request)

    api_response = AiResponse(session_type="error_analysis", **response)
    assert api_response.error_code == error_code
    assert api_response.retryable is retryable
    assert api_response.cache_preserved is preserve_cache
    assert api_response.from_fallback is not preserve_cache
    assert api_response.tokens_used == 0
    if preserve_cache:
        assert response is old_cache
        assert api_response.content == {"mistake_diagnosis": "previous analysis"}
        assert api_response.generated_at == "2026-11-01T00:00:00+00:00"
    item.chat.assert_awaited_once()
    h.request.parse_content.assert_not_called()
    assert [name for name, *_ in h.events] == ["begin", "cache", "inputs", "finish"]
