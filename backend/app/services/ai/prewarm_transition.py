"""Map prewarm input/result states without owning the background session."""

from __future__ import annotations

from typing import Any



def skipped_not_found() -> dict:
    return {
        "status": "skipped",
        "reason": "wrong_question_not_found",
        "from_cache": False,
    }


def superseded_revision() -> dict:
    return {
        "status": "superseded",
        "reason": "revision_changed",
        "from_cache": False,
    }


def superseded_regenerated() -> dict:
    return {
        "status": "superseded",
        "reason": "analysis_already_regenerated",
        "from_cache": True,
    }


def prewarm_failure(result: dict):
    from app.services.ai_service import _prewarm_failure_from_result

    return _prewarm_failure_from_result(result)


def failure_category(error_code: str, retryable: bool) -> str:
    if error_code in {
        "vision_input_missing",
        "vision_parse_failed",
        "vision_unavailable",
    }:
        return "failed_input"
    return "retry" if retryable else "failed_permanent"


def success_outcome(result: dict[str, Any]) -> dict:
    status = "cache_hit" if result.get("from_cache") else "success"
    return {
        "status": status,
        "reason": None,
        "from_cache": bool(result.get("from_cache")),
        "model": result.get("model"),
        "duration_ms": result.get("duration_ms", 0),
    }
