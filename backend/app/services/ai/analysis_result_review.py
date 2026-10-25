"""Post-provider parse, grounding validation, and outcome selection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.analysis_outcomes import (
    VisualAckFailure,
    detect_visual_ack_failure,
)
from app.services.ai.analysis_responses import parse_failed_response
from app.services.ai.analysis_validation import (
    AnalysisUsage,
    GroundingValidation,
    VisualValidationRequest,
    reconcile_visual_evidence,
)
from app.services.ai.provider_invocation import ProviderInvocationResult


@dataclass(slots=True)
class ReviewedAnalysis:
    parsed: dict
    parsed_valid: bool
    usage: AnalysisUsage
    grounding: GroundingValidation
    ack_failure: VisualAckFailure | None


async def review_analysis_result(
    invocation: ProviderInvocationResult,
    *,
    image_data_urls: list[str],
    wrong_question_id: int,
    chat: Callable[..., Awaitable[Any]],
    expected_answer_check: Any,
    answer_grounding: Any,
    parse_content: Callable[[str], dict],
    validate_content: Callable[[dict], bool],
    extract_evidence: Callable[[str], str],
    build_usage: Callable[..., AnalysisUsage],
    validate_answer_check: Callable[[str, Any], tuple[bool, str, Any]],
    diagnosis_contradicts_grounding: Callable[[str, Any], tuple[bool, str | None]],
    evidence_is_valid: Callable[[str], bool],
    should_retry_visual_ack: Callable[..., bool],
    retry_visual_ack: Callable[..., Awaitable[Any]],
) -> ReviewedAnalysis:
    result = invocation.result
    raw_content = result.get("content", "")
    parsed = parse_content(raw_content)
    parsed_valid = validate_content(parsed)
    usage = build_usage(
        raw_content=raw_content,
        result=result,
        image_data_urls=image_data_urls,
        extract_evidence=extract_evidence,
    )
    grounding = await reconcile_visual_evidence(
        VisualValidationRequest(
            result=result,
            image_data_urls=image_data_urls,
            runtime=invocation.runtime,
            wrong_question_id=wrong_question_id,
            chat=chat,
            extract_evidence=extract_evidence,
            validate_answer_check=validate_answer_check,
            diagnosis_contradicts_grounding=diagnosis_contradicts_grounding,
            evidence_is_valid=evidence_is_valid,
            should_retry_visual_ack=should_retry_visual_ack,
            retry_visual_ack=retry_visual_ack,
        ),
        parsed,
        parsed_valid=parsed_valid,
        expected_answer_check=expected_answer_check,
        answer_grounding=answer_grounding,
        usage=usage,
    )
    return ReviewedAnalysis(
        parsed=parsed,
        parsed_valid=parsed_valid,
        usage=usage,
        grounding=grounding,
        ack_failure=detect_visual_ack_failure(
            image_data_urls=image_data_urls,
            visual_evidence=usage.visual_evidence,
            evidence_is_valid=evidence_is_valid,
        ),
    )


async def resolve_analysis_outcome(
    db: AsyncSession,
    review: ReviewedAnalysis,
    *,
    wrong_question: Any,
    user_id: int,
    context: dict,
    result: dict,
    image_data_urls: list[str],
    input_signature: str,
    model_signature: str,
    expected_answer_check: Any,
    effective_force: bool,
    runtime: Any,
    visual_evidence_is_valid: Callable[[str], bool],
    max_tokens: int,
    logger: Logger,
    visual_ack_failure: Callable[..., dict],
    grounding_repair: Callable[..., Awaitable[dict]],
    valid_outcome: Callable[..., Awaitable[dict]],
) -> dict:
    if review.ack_failure is not None:
        return visual_ack_failure(
            wrong_question_id=wrong_question.id,
            result=result,
            image_data_urls=image_data_urls,
            usage=review.usage,
            visual_ack_retried=review.usage.visual_ack_retried,
            failure=review.ack_failure,
            logger=logger,
        )
    if not review.parsed_valid:
        response = parse_failed_response(
            image_data_urls, effective_force=effective_force
        )
        logger.info(
            "ai.error_analysis.empty wq_id=%s force=%s model=parse_failed",
            wrong_question.id,
            effective_force,
        )
        return response
    if not review.grounding.valid:
        return await grounding_repair(
            db,
            wrong_question=wrong_question,
            user_id=user_id,
            context=context,
            result=result,
            grounding=review.grounding,
            usage=review.usage,
            input_signature=input_signature,
            model_signature=model_signature,
            expected_answer_check=expected_answer_check,
            effective_force=effective_force,
            runtime=runtime,
            logger=logger,
        )
    return await valid_outcome(
        db,
        wrong_question=wrong_question,
        user_id=user_id,
        context=context,
        result=result,
        parsed=review.parsed,
        grounding=review.grounding,
        usage=review.usage,
        input_signature=input_signature,
        model_signature=model_signature,
        expected_answer_check=expected_answer_check,
        effective_force=effective_force,
        visual_evidence_is_valid=visual_evidence_is_valid,
        max_tokens=max_tokens,
        runtime=runtime,
        logger=logger,
    )
