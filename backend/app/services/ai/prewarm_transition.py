"""Map prewarm input/result states without owning the background session."""

from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import Any


def dead_retry_budget(task_data: dict[str, Any]) -> int | None:
    if str(task_data.get("error") or "").startswith("ai_service_unavailable:"):
        return max(3, int(task_data.get("max_retries", 0) or 0))
    return None


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


def failure_category(error_code: str, retryable: bool) -> str:
    if error_code in {
        "vision_input_missing",
        "vision_parse_failed",
        "vision_unavailable",
    }:
        return "failed_input"
    return "retry" if retryable else "failed_permanent"


def revision_changed(
    *,
    wrong_question: Any,
    expected_revision: str | None,
    build_revision: Callable[..., str],
) -> bool:
    if not expected_revision:
        return False
    current_revision = build_revision(
        review_count=wrong_question.review_count,
        wrong_answer=wrong_question.wrong_answer,
    )
    return current_revision != expected_revision


def recovery_regenerated(
    *,
    wrong_question: Any,
    baseline_generated_at: str | None,
    generated_at: Callable[[Any], str | None],
) -> bool:
    if baseline_generated_at is None:
        return False
    current_generated_at = generated_at(wrong_question.ai_analysis) or ""
    return current_generated_at != str(baseline_generated_at or "")


def success_outcome(result: dict[str, Any]) -> dict:
    status = "cache_hit" if result.get("from_cache") else "success"
    return {
        "status": status,
        "reason": None,
        "from_cache": bool(result.get("from_cache")),
        "model": result.get("model"),
        "duration_ms": result.get("duration_ms", 0),
    }


def finish_prewarm_result(
    result: dict[str, Any],
    *,
    wrong_question_id: int,
    user_id: int,
    expected_revision: str | None,
    logger: Logger,
    failure_factory: Callable[[dict], Exception],
) -> dict:
    """Convert synchronous fallback/cache outcomes into worker semantics."""
    if result.get("from_fallback") or (
        result.get("cache_preserved") and result.get("error_code")
    ):
        failure = failure_factory(result)
        category = failure_category(failure.error_code, failure.retryable)
        logger.warning(
            "[prewarm] %s id=%d uid=%d revision=%s error_code=%s retryable=%s model=%s",
            category,
            wrong_question_id,
            user_id,
            expected_revision or "legacy",
            failure.error_code,
            failure.retryable,
            failure.model,
        )
        raise failure

    status = "cache_hit" if result.get("from_cache") else "success"
    logger.info(
        "[prewarm] %s id=%d uid=%d revision=%s model=%s duration_ms=%s",
        status,
        wrong_question_id,
        user_id,
        expected_revision or "legacy",
        result.get("model"),
        result.get("duration_ms"),
    )
    return success_outcome(result)
