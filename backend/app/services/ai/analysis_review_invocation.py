"""Assembly contracts between prepared inputs and provider result review."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.analysis_invocation import (
    AnalysisInvocationRequest,
    invoke_prepared_analysis,
)
from app.services.ai.analysis_result_review import review_analysis_result


async def invoke_and_review_analysis(
    *,
    db: AsyncSession,
    request: Any,
    context: dict,
    image_data_urls: list[str],
    input_signature: str,
    inputs: Any,
) -> tuple[Any, Any]:
    invocation = await invoke_prepared_analysis(
        AnalysisInvocationRequest(
            db=db,
            wrong_question=request.wrong_question,
            question=request.question,
            context=context,
            runtime=request.runtime,
            image_data_urls=image_data_urls,
            requires_visual=request.requires_visual,
            prompt_grounding=inputs.prompt_grounding,
            input_signature=input_signature,
            model_signature=request.model_signature,
            force=request.effective_force,
            model_timeout_sec=inputs.model_timeout_sec,
            max_tokens=request.max_tokens,
            timeout_guard_sec=request.timeout_guard_sec,
            logger=request.logger,
            chat=request.chat,
            resolve_runtime=request.resolve_runtime,
            quarantine_runtime=request.quarantine_runtime,
            cached_response=request.cached_response,
        )
    )
    # Provider failures and preserved caches are already complete API responses.
    if isinstance(invocation, dict):
        return invocation, None
    review = await _review_invocation(request, invocation, image_data_urls, inputs)
    return invocation, review


async def _review_invocation(request: Any, invocation: Any, image_data_urls, inputs):
    return await review_analysis_result(
        invocation,
        image_data_urls=image_data_urls,
        wrong_question_id=request.wrong_question.id,
        chat=request.chat,
        expected_answer_check=inputs.expected_answer_check,
        answer_grounding=inputs.answer_grounding,
        parse_content=request.parse_content,
        validate_content=request.validate_content,
        extract_evidence=request.extract_evidence,
        build_usage=request.build_usage,
        validate_answer_check=request.validate_answer_check,
        diagnosis_contradicts_grounding=request.diagnosis_contradicts_grounding,
        evidence_is_valid=request.evidence_is_valid,
        should_retry_visual_ack=request.should_retry_visual_ack,
        retry_visual_ack=request.retry_visual_ack,
    )


async def resolve_reviewed_analysis_outcome(
    *,
    request: Any,
    context: dict,
    input_signature: str,
    image_data_urls: list[str],
    inputs: Any,
    invocation: Any,
    review: Any,
) -> dict:
    if isinstance(invocation, dict):
        return invocation
    runtime = invocation.runtime
    return await _resolve_outcome(
        request,
        context,
        input_signature,
        image_data_urls,
        inputs,
        invocation,
        review,
        runtime,
    )


async def _resolve_outcome(
    request: Any,
    context: dict,
    input_signature: str,
    image_data_urls: list[str],
    inputs: Any,
    invocation: Any,
    review: Any,
    runtime: Any,
) -> dict:
    from app.services.ai.analysis_result_review import resolve_analysis_outcome

    return await resolve_analysis_outcome(
        request.db,
        review,
        wrong_question=request.wrong_question,
        user_id=request.user_id,
        context=context,
        result=invocation.result,
        image_data_urls=image_data_urls,
        input_signature=input_signature,
        model_signature=request.model_signature_builder(runtime),
        expected_answer_check=inputs.expected_answer_check,
        effective_force=request.effective_force,
        visual_evidence_is_valid=request.evidence_is_valid,
        max_tokens=request.max_tokens,
        runtime=runtime,
        logger=request.logger,
        visual_ack_failure=request.visual_ack_failure,
        grounding_repair=request.grounding_repair,
        valid_outcome=request.valid_outcome,
    )
