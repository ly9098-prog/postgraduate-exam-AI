"""Validation and visual-ack metadata extraction for AI analysis responses."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class GroundingValidation:
    valid: bool
    guard_reason: str
    actual_answer_check: Any = None
    answer_grounding: Any = None


@dataclass(slots=True)
class AnalysisUsage:
    visual_evidence: str
    visual_ack_retried: bool
    visual_ack_retry_ms: int
    total_tokens_used: int
    total_duration_ms: int


@dataclass(slots=True)
class VisualValidationRequest:
    result: dict
    image_data_urls: list[str]
    runtime: Any
    wrong_question_id: int
    chat: Callable[..., Awaitable[Any]]
    extract_evidence: Callable[[str], str]
    validate_answer_check: Callable[[str, Any], tuple[bool, str, Any]]
    diagnosis_contradicts_grounding: Callable[[str, Any], tuple[bool, str | None]]
    evidence_is_valid: Callable[[str], bool]
    should_retry_visual_ack: Callable[..., bool]
    retry_visual_ack: Callable[..., Awaitable[Any]]


def validate_analysis_grounding(
    *,
    parsed_valid: bool,
    raw_content: str,
    parsed_diagnosis: str,
    expected_answer_check: Any,
    answer_grounding: Any,
    validate_answer_check: Callable[[str, Any], tuple[bool, str, Any]],
    diagnosis_contradicts_grounding: Callable[[str, Any], tuple[bool, str | None]],
) -> GroundingValidation:
    if not parsed_valid:
        return GroundingValidation(False, "analysis_invalid")

    valid, reason, actual = validate_answer_check(raw_content, expected_answer_check)
    if not valid:
        return GroundingValidation(False, reason, actual)

    contradicts, contradiction_reason = diagnosis_contradicts_grounding(
        parsed_diagnosis, answer_grounding
    )
    if contradicts:
        return GroundingValidation(
            False, contradiction_reason or "diagnosis_contradiction", actual
        )
    return GroundingValidation(True, reason, actual)


async def reconcile_visual_evidence(
    request: VisualValidationRequest,
    parsed: dict,
    parsed_valid: bool,
    expected_answer_check: Any,
    answer_grounding: Any,
    usage: AnalysisUsage,
) -> GroundingValidation:
    grounding = validate_analysis_grounding(
        parsed_valid=parsed_valid,
        raw_content=str(request.result.get("content") or ""),
        parsed_diagnosis=str(parsed.get("mistake_diagnosis", "")),
        expected_answer_check=expected_answer_check,
        answer_grounding=answer_grounding,
        validate_answer_check=request.validate_answer_check,
        diagnosis_contradicts_grounding=request.diagnosis_contradicts_grounding,
    )
    grounding.answer_grounding = answer_grounding

    if request.image_data_urls and not request.evidence_is_valid(usage.visual_evidence):
        if request.should_retry_visual_ack(
            parsed_valid=parsed_valid,
            grounding_valid=grounding.valid,
            duration_ms=usage.total_duration_ms,
        ):
            ack = await request.retry_visual_ack(
                request.image_data_urls,
                runtime=request.runtime,
                source_model=str(request.result.get("model") or ""),
                wrong_question_id=request.wrong_question_id,
                current_evidence=usage.visual_evidence,
                chat=request.chat,
                extract_evidence=request.extract_evidence,
            )
            usage.visual_ack_retried = ack.retried
            usage.visual_ack_retry_ms = ack.retry_ms
            usage.total_duration_ms += ack.retry_ms
            usage.total_tokens_used += ack.tokens_used_delta
            usage.visual_evidence = ack.evidence
    return grounding
