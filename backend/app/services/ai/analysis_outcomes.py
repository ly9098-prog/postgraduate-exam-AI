"""Terminal outcome projection and persistence for analyzed errors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.analysis_persistence import (
    persist_repaired_analysis,
    persist_valid_analysis,
)
from app.services.ai.analysis_responses import (
    grounding_repaired_response,
    valid_analysis_response,
    visual_ack_failed_response,
)
from app.services.ai.analysis_validation import AnalysisUsage, GroundingValidation


@dataclass(slots=True)
class VisualAckFailure:
    error_code: str
    retryable: bool
    evidence_text: str


def build_analysis_usage(
    *,
    raw_content: str,
    result: dict,
    image_data_urls: list[str],
    extract_evidence: Callable[[str], str],
) -> AnalysisUsage:
    return AnalysisUsage(
        visual_evidence=(extract_evidence(raw_content) if image_data_urls else ""),
        visual_ack_retried=False,
        visual_ack_retry_ms=0,
        total_tokens_used=int(result.get("tokens_used") or 0),
        total_duration_ms=int(result.get("duration_ms") or 0),
    )


def detect_visual_ack_failure(
    *,
    image_data_urls: list[str],
    visual_evidence: str,
    evidence_is_valid: Callable[[str], bool],
) -> VisualAckFailure | None:
    if not image_data_urls or evidence_is_valid(visual_evidence):
        return None
    evidence_text = str(visual_evidence or "").strip()
    ack_missing = not evidence_text
    return VisualAckFailure(
        error_code="vision_ack_missing" if ack_missing else "vision_parse_failed",
        retryable=bool(ack_missing),
        evidence_text=evidence_text,
    )


def visual_ack_failure_outcome(
    *,
    wrong_question_id: int,
    result: dict,
    image_data_urls: list[str],
    usage: AnalysisUsage,
    visual_ack_retried: bool,
    failure: VisualAckFailure,
    logger: Logger,
) -> dict:
    logger.info(
        "ai.error_analysis.visual_ack_failed wq_id=%s model=%s evidence=%r "
        "retried=%s error_code=%s retryable=%s",
        wrong_question_id,
        result.get("model"),
        failure.evidence_text[:120],
        visual_ack_retried,
        failure.error_code,
        failure.retryable,
    )
    return visual_ack_failed_response(
        error_code=failure.error_code,
        retryable=failure.retryable,
        tokens_used=usage.total_tokens_used,
        duration_ms=usage.total_duration_ms,
        visual_input_count=len(image_data_urls),
    )


async def grounding_repair_outcome(
    db: AsyncSession,
    *,
    wrong_question: Any,
    user_id: int,
    context: dict,
    result: dict,
    grounding: GroundingValidation,
    usage: AnalysisUsage,
    image_data_urls: list[str],
    input_signature: str,
    model_signature: str,
    expected_answer_check: Any,
    effective_force: bool,
    runtime: Any,
    logger: Logger,
    persist=persist_repaired_analysis,
) -> dict:
    safe, generated_at = await persist(
        db,
        wrong_question=wrong_question,
        user_id=user_id,
        context=context,
        result=result,
        answer_grounding=grounding.answer_grounding,
        visual_evidence=usage.visual_evidence,
        visual_ack_retried=usage.visual_ack_retried,
        visual_ack_retry_ms=usage.visual_ack_retry_ms,
        image_count=len(image_data_urls),
        input_signature=input_signature,
        model_signature=model_signature,
        expected_answer_check=expected_answer_check,
        grounding_guard_reason=grounding.guard_reason,
        actual_answer_check=grounding.actual_answer_check,
        tokens_used=usage.total_tokens_used,
        duration_ms=usage.total_duration_ms,
        effective_force=effective_force,
        runtime=runtime,
    )
    logger.warning(
        "ai.error_analysis.grounding_repaired wq_id=%s force=%s model=%s reason=%s "
        "expected=%s actual=%s",
        wrong_question.id,
        effective_force,
        result.get("model"),
        grounding.guard_reason,
        expected_answer_check,
        grounding.actual_answer_check,
    )
    return grounding_repaired_response(
        content=safe,
        tokens_used=usage.total_tokens_used,
        duration_ms=usage.total_duration_ms,
        effective_force=effective_force,
        visual_input_count=len(image_data_urls),
        visual_evidence=usage.visual_evidence,
        generated_at=generated_at,
    )


async def valid_analysis_outcome(
    db: AsyncSession,
    *,
    wrong_question: Any,
    user_id: int,
    context: dict,
    result: dict,
    parsed: dict,
    grounding: GroundingValidation,
    usage: AnalysisUsage,
    image_data_urls: list[str],
    input_signature: str,
    model_signature: str,
    expected_answer_check: Any,
    effective_force: bool,
    visual_evidence_is_valid: Callable[[str], bool],
    max_tokens: int,
    runtime: Any,
    logger: Logger,
    persist=persist_valid_analysis,
) -> dict:
    await persist(
        db,
        wrong_question=wrong_question,
        user_id=user_id,
        context=context,
        result=result,
        parsed=parsed,
        answer_grounding=grounding.answer_grounding,
        visual_evidence=usage.visual_evidence,
        visual_ack_retried=usage.visual_ack_retried,
        visual_ack_retry_ms=usage.visual_ack_retry_ms,
        image_count=len(image_data_urls),
        input_signature=input_signature,
        model_signature=model_signature,
        expected_answer_check=expected_answer_check,
        effective_force=effective_force,
        tokens_used=usage.total_tokens_used,
        duration_ms=usage.total_duration_ms,
        runtime=runtime,
    )
    logger.info(
        "ai.error_analysis.result wq_id=%s force=%s model=%s input_mode=%s visual_count=%s "
        "visual_evidence_valid=%s parsed_valid=%s compatibility=%s max_tokens=%s "
        "visual_ack_retried=%s visual_ack_retry_ms=%s "
        "fields=%s duration_ms=%s",
        wrong_question.id,
        effective_force,
        result.get("model"),
        "vision" if image_data_urls else "text",
        len(image_data_urls),
        visual_evidence_is_valid(usage.visual_evidence) if image_data_urls else None,
        True,
        result.get("compatibility_profile") or "default",
        max_tokens,
        usage.visual_ack_retried,
        usage.visual_ack_retry_ms,
        {
            k: bool(parsed.get(k))
            for k in ["mistake_diagnosis", "knowledge_patch", "review_task"]
        },
        usage.total_duration_ms,
    )
    return valid_analysis_response(
        parsed,
        result,
        tokens_used=usage.total_tokens_used,
        duration_ms=usage.total_duration_ms,
        effective_force=effective_force,
        image_data_urls=image_data_urls,
        visual_evidence=usage.visual_evidence,
    )
