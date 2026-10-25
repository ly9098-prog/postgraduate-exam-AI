"""Typed response projections for the synchronous error-analysis API."""

from __future__ import annotations

from typing import Any

from app.ai.fallback import get_fallback_analysis


def generation_in_progress_response() -> dict[str, Any]:
    return {
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


def vision_input_missing_response(*, visual_input_count: int = 0) -> dict[str, Any]:
    return {
        "content": get_fallback_analysis(),
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": "vision_input_missing",
        "duration_ms": 0,
        "force_regenerated": False,
        "cache_preserved": False,
        "visual_input_count": visual_input_count,
        "error_code": "vision_input_missing",
        "retryable": False,
    }


def analysis_model_unconfigured_response(
    image_data_urls: list[str],
) -> dict[str, Any]:
    return {
        "content": get_fallback_analysis(),
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": "vision_unavailable" if image_data_urls else "fallback",
        "duration_ms": 0,
        "force_regenerated": False,
        "cache_preserved": False,
        "visual_input_count": len(image_data_urls),
        "error_code": "ai_model_unconfigured",
        "retryable": False,
    }


def provider_failure_response(
    *,
    error_code: str,
    retryable: bool,
    failure_model: str,
    duration_ms: int,
    image_data_urls: list[str],
) -> dict[str, Any]:
    return {
        "content": get_fallback_analysis(),
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": failure_model,
        "duration_ms": duration_ms,
        "force_regenerated": False,
        "cache_preserved": False,
        "visual_input_count": len(image_data_urls),
        "error_code": error_code,
        "retryable": retryable,
    }


def visual_ack_failed_response(
    *,
    error_code: str,
    retryable: bool,
    tokens_used: int,
    duration_ms: int,
    visual_input_count: int,
) -> dict[str, Any]:
    return {
        "content": get_fallback_analysis(),
        "from_cache": False,
        "from_fallback": True,
        "model": "vision_parse_failed",
        "tokens_used": tokens_used,
        "duration_ms": duration_ms,
        "force_regenerated": False,
        "cache_preserved": False,
        "visual_input_count": visual_input_count,
        "error_code": error_code,
        "retryable": retryable,
    }


def parse_failed_response(
    image_data_urls: list[str], *, effective_force: bool
) -> dict[str, Any]:
    response = {
        "content": get_fallback_analysis(),
        "from_cache": False,
        "from_fallback": True,
        "model": "parse_failed",
        "tokens_used": 0,
        "duration_ms": 0,
        "visual_input_count": len(image_data_urls),
        "error_code": "ai_response_parse_failed",
        "retryable": True,
    }
    if effective_force:
        response["force_regenerated"] = False
        response["cache_preserved"] = False
    return response


def grounding_repaired_response(
    *,
    content: Any,
    tokens_used: int,
    duration_ms: int,
    effective_force: bool,
    visual_input_count: int,
    visual_evidence: str,
    generated_at: Any,
) -> dict[str, Any]:
    return {
        "content": content,
        "from_cache": False,
        "from_fallback": False,
        "tokens_used": tokens_used,
        "model": "grounding_guard",
        "duration_ms": duration_ms,
        "force_regenerated": effective_force,
        "visual_input_count": visual_input_count,
        "visual_evidence": visual_evidence or None,
        "input_mode": "vision" if visual_input_count else "text",
        "generated_at": generated_at,
        "grounding_repaired": True,
    }


def valid_analysis_response(
    parsed: dict,
    result: dict,
    *,
    tokens_used: int,
    duration_ms: int,
    effective_force: bool,
    image_data_urls: list[str],
    visual_evidence: str,
) -> dict[str, Any]:
    return {
        "content": parsed,
        "from_cache": False,
        "from_fallback": False,
        "tokens_used": tokens_used,
        "model": result.get("model", ""),
        "duration_ms": duration_ms,
        "force_regenerated": effective_force,
        "visual_input_count": len(image_data_urls),
        "visual_evidence": visual_evidence or None,
        "input_mode": "vision" if image_data_urls else "text",
        "generated_at": parsed["_meta"]["generated_at"],
    }
