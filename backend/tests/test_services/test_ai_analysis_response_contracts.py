"""Compatibility contract for synchronous error-analysis response projections."""

from __future__ import annotations

from app.ai.fallback import get_fallback_analysis
from app.services.ai.analysis_responses import (
    analysis_model_unconfigured_response,
    generation_in_progress_response,
    grounding_repaired_response,
    parse_failed_response,
    provider_failure_response,
    valid_analysis_response,
    vision_input_missing_response,
    visual_ack_failed_response,
)


def test_generation_in_progress_and_missing_visual_payloads_are_stable():
    assert generation_in_progress_response() == {
        "content": {
            "mistake_diagnosis": "AI 分析正在生成中，请稍后刷新查看",
            "knowledge_patch": "",
            "review_task": "",
        },
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": "generating",
        "duration_ms": 0,
        "error_code": "generation_in_progress",
        "retryable": True,
    }

    assert vision_input_missing_response() == {
        "content": get_fallback_analysis(),
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": "vision_input_missing",
        "duration_ms": 0,
        "force_regenerated": False,
        "cache_preserved": False,
        "visual_input_count": 0,
        "error_code": "vision_input_missing",
        "retryable": False,
    }


def test_unconfigured_model_preserves_text_and_vision_model_names():
    assert analysis_model_unconfigured_response([])["model"] == "fallback"
    vision = analysis_model_unconfigured_response(["data:image/png;base64,x"])
    assert vision["model"] == "vision_unavailable"
    assert vision["visual_input_count"] == 1


def test_provider_failure_projection_keeps_usage_and_typed_error_fields():
    response = provider_failure_response(
        error_code="ai_provider_timeout",
        retryable=True,
        failure_model="timeout",
        duration_ms=1234,
        image_data_urls=["data:image/png;base64,x", "data:image/png;base64=y"],
    )
    assert response == {
        "content": get_fallback_analysis(),
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": "timeout",
        "duration_ms": 1234,
        "force_regenerated": False,
        "cache_preserved": False,
        "visual_input_count": 2,
        "error_code": "ai_provider_timeout",
        "retryable": True,
    }


def test_visual_ack_failure_keeps_accumulated_usage_and_distinguishes_retryability():
    missing = visual_ack_failed_response(
        error_code="vision_ack_missing",
        retryable=True,
        tokens_used=31,
        duration_ms=900,
        visual_input_count=2,
    )
    invalid = visual_ack_failed_response(
        error_code="vision_parse_failed",
        retryable=False,
        tokens_used=31,
        duration_ms=900,
        visual_input_count=2,
    )
    assert missing["retryable"] is True
    assert invalid["retryable"] is False
    for response in (missing, invalid):
        assert response["model"] == "vision_parse_failed"
        assert response["tokens_used"] == 31
        assert response["duration_ms"] == 900


def test_parse_failure_exposes_force_fields_only_for_force_regeneration():
    assert "force_regenerated" not in parse_failed_response([], effective_force=False)
    assert "cache_preserved" not in parse_failed_response([], effective_force=False)
    assert parse_failed_response(["data:image/png;base64,x"], effective_force=True) == {
        "content": get_fallback_analysis(),
        "from_cache": False,
        "from_fallback": True,
        "model": "parse_failed",
        "tokens_used": 0,
        "duration_ms": 0,
        "visual_input_count": 1,
        "error_code": "ai_response_parse_failed",
        "retryable": True,
        "force_regenerated": False,
        "cache_preserved": False,
    }


def test_grounding_and_valid_success_payloads_share_visual_metadata():
    grounding = grounding_repaired_response(
        content={"mistake_diagnosis": "safe"},
        tokens_used=7,
        duration_ms=88,
        effective_force=True,
        visual_input_count=2,
        visual_evidence="图中给出栈",
        generated_at="2026-10-26T00:00:00Z",
    )
    assert grounding == {
        "content": {"mistake_diagnosis": "safe"},
        "from_cache": False,
        "from_fallback": False,
        "tokens_used": 7,
        "model": "grounding_guard",
        "duration_ms": 88,
        "force_regenerated": True,
        "visual_input_count": 2,
        "visual_evidence": "图中给出栈",
        "input_mode": "vision",
        "generated_at": "2026-10-26T00:00:00Z",
        "grounding_repaired": True,
    }

    parsed = {
        "mistake_diagnosis": "诊断",
        "knowledge_patch": "补丁",
        "review_task": "任务",
        "_meta": {"generated_at": "2026-10-26T00:01:00Z"},
    }
    valid = valid_analysis_response(
        parsed,
        {"model": "analysis-model"},
        tokens_used=7,
        duration_ms=88,
        effective_force=False,
        image_data_urls=[],
        visual_evidence="",
    )
    assert valid == {
        "content": parsed,
        "from_cache": False,
        "from_fallback": False,
        "tokens_used": 7,
        "model": "analysis-model",
        "duration_ms": 88,
        "force_regenerated": False,
        "visual_input_count": 0,
        "visual_evidence": None,
        "input_mode": "text",
        "generated_at": "2026-10-26T00:01:00Z",
    }
