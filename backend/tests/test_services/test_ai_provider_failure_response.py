"""Contract for preserving old cache when forced provider regeneration fails."""

from __future__ import annotations

from app.ai.fallback import get_fallback_analysis
from app.services.ai.analysis_provider_failure import build_provider_failure_response


def test_force_failure_annotates_matching_old_cache_in_place():
    wrong_question = object()
    cache = {
        "content": {"mistake_diagnosis": "旧诊断"},
        "from_cache": True,
        "tokens_used": 0,
        "model": "cache_preserved",
    }

    def cached_response(*args, **kwargs):
        assert args[0] is wrong_question
        assert kwargs["requires_visual"] is True
        assert kwargs["expected_input_signature"] == "input"
        assert kwargs["expected_model_signature"] == "model"
        return cache

    failure = build_provider_failure_response(
        wrong_question=wrong_question,
        requires_visual=True,
        input_signature="input",
        model_signature="model",
        effective_force=True,
        image_data_urls=["data:image/png;base64,x"],
        cached_response=cached_response,
    )
    response = failure(
        error_code="ai_provider_timeout",
        retryable=True,
        failure_model="timeout",
        duration_ms=123,
    )

    assert response is cache
    assert response["force_regenerated"] is False
    assert response["cache_preserved"] is True
    assert response["error_code"] == "ai_provider_timeout"
    assert response["retryable"] is True


def test_failure_without_matching_cache_returns_provider_fallback():
    calls = []

    def cached_response(*args, **kwargs):
        calls.append(kwargs)
        return None

    failure = build_provider_failure_response(
        wrong_question=object(),
        requires_visual=False,
        input_signature="input",
        model_signature="model",
        effective_force=True,
        image_data_urls=[],
        cached_response=cached_response,
    )
    response = failure(
        error_code="ai_provider_failed",
        retryable=False,
        failure_model="failed-model",
        duration_ms=45,
    )

    assert calls and calls[0]["requires_visual"] is False
    assert response == {
        "content": get_fallback_analysis(),
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": "failed-model",
        "duration_ms": 45,
        "force_regenerated": False,
        "cache_preserved": False,
        "visual_input_count": 0,
        "error_code": "ai_provider_failed",
        "retryable": False,
    }
