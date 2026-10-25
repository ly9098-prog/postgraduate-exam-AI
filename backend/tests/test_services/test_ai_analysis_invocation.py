"""Contract for assembled prepared-analysis provider invocations."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai.analysis_invocation import (
    AnalysisInvocationRequest,
    invoke_prepared_analysis,
)
from app.services.ai.provider_invocation import ProviderInvocationResult


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
