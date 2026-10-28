"""End-to-end orchestration for one locked AI error analysis."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.analysis_execution import (
    AnalysisLease,
    LockedAnalysisInputs,
    LockedCacheReview,
    begin_analysis_generation,
    finish_analysis_generation,
    prepare_locked_analysis_inputs,
    review_locked_analysis_cache,
)
from app.services.ai.analysis_responses import generation_in_progress_response
from app.services.ai.analysis_review_invocation import (
    invoke_and_review_analysis,
    resolve_reviewed_analysis_outcome,
)


@dataclass(slots=True)
class AnalysisOrchestrationRequest:
    db: AsyncSession
    user_id: int
    wrong_question: Any
    question: Any
    answer_grounding: Any
    stored_visual_sources: list
    requires_visual: bool
    knowledge_points: list
    runtime: Any
    input_signature: str
    model_signature: str | None
    effective_force: bool
    timeout_sec: int | float
    lock_grace_sec: int
    generating: set[int]
    cache: Any
    logger: Logger
    prepare_visual_inputs: Callable[..., Awaitable[Any]]
    build_context: Callable[..., dict]
    build_prompt_grounding: Callable[[Any], Any]
    build_expected_answer_check: Callable[[Any], Any]
    input_signature_builder: Callable[..., str]
    cached_response: Callable[..., dict | None]
    cache_age: Callable[[Any], Any]
    chat: Callable[..., Awaitable[dict]]
    resolve_runtime: Callable[..., Awaitable[Any]]
    quarantine_runtime: Callable[[Any], Awaitable[None]]
    parse_content: Callable[[str], dict]
    validate_content: Callable[[dict], bool]
    extract_evidence: Callable[[str], str]
    build_usage: Callable[..., Any]
    validate_answer_check: Callable[..., tuple[bool, str, Any]]
    diagnosis_contradicts_grounding: Callable[..., tuple[bool, str | None]]
    evidence_is_valid: Callable[[str], bool]
    should_retry_visual_ack: Callable[..., bool]
    retry_visual_ack: Callable[..., Awaitable[Any]]
    model_signature_builder: Callable[[Any], str | None]
    max_tokens: int
    timeout_guard_sec: int
    visual_ack_failure: Callable[..., dict]
    grounding_repair: Callable[..., Awaitable[dict]]
    valid_outcome: Callable[..., Awaitable[dict]]


async def execute_locked_analysis(request: AnalysisOrchestrationRequest) -> dict:
    lease = await begin_analysis_generation(
        wrong_question_id=request.wrong_question.id,
        user_id=request.user_id,
        timeout_sec=request.timeout_sec,
        lock_grace_sec=request.lock_grace_sec,
        generating=request.generating,
        cache=request.cache,
    )
    if lease is None:
        return generation_in_progress_response()
    try:
        return await _execute_with_lease(request, lease)
    finally:
        await finish_analysis_generation(
            wrong_question_id=request.wrong_question.id,
            generating=request.generating,
            lease=lease,
            cache=request.cache,
        )


async def _execute_with_lease(
    request: AnalysisOrchestrationRequest, lease: AnalysisLease
) -> dict:
    del lease
    locked_cache = await _review_cache(request)
    input_signature = locked_cache.input_signature
    if locked_cache.response is not None:
        return locked_cache.response

    inputs = await _prepare_inputs(request)
    if inputs.response is not None:
        return inputs.response

    context = _grounded_context(inputs)
    invocation, review = await _invoke_review(request, context, input_signature, inputs)
    return await _resolve_review_outcome(
        request, context, input_signature, inputs, invocation, review
    )


def _grounded_context(inputs: LockedAnalysisInputs) -> dict:
    context = inputs.context
    context["answer_grounding"] = inputs.prompt_grounding
    return context


async def _invoke_review(
    request: AnalysisOrchestrationRequest,
    context: dict,
    input_signature: str,
    inputs: LockedAnalysisInputs,
):
    return await invoke_and_review_analysis(
        db=request.db,
        request=request,
        context=context,
        image_data_urls=inputs.image_data_urls,
        input_signature=input_signature,
        inputs=inputs,
    )


async def _resolve_review_outcome(
    request: AnalysisOrchestrationRequest,
    context: dict,
    input_signature: str,
    inputs: LockedAnalysisInputs,
    invocation,
    review,
) -> dict:
    return await resolve_reviewed_analysis_outcome(
        request=request,
        context=context,
        input_signature=input_signature,
        image_data_urls=inputs.image_data_urls,
        inputs=inputs,
        invocation=invocation,
        review=review,
    )


async def _review_cache(request: AnalysisOrchestrationRequest) -> LockedCacheReview:
    return await review_locked_analysis_cache(
        request.db,
        request.wrong_question,
        request.question,
        user_id=request.user_id,
        force=request.effective_force,
        requires_visual=request.requires_visual,
        stored_visual_sources=request.stored_visual_sources,
        knowledge_points=request.knowledge_points,
        model_signature=request.model_signature,
        input_signature=request.input_signature_builder,
        cached_response=request.cached_response,
        cache_age=request.cache_age,
        logger=request.logger,
    )


async def _prepare_inputs(
    request: AnalysisOrchestrationRequest,
) -> LockedAnalysisInputs:
    return await prepare_locked_analysis_inputs(
        request.wrong_question,
        request.question,
        current_answer_grounding=request.answer_grounding,
        requires_visual=request.requires_visual,
        runtime=request.runtime,
        knowledge_points=request.knowledge_points,
        timeout_sec=request.timeout_sec,
        logger=request.logger,
        prepare_visual_inputs=request.prepare_visual_inputs,
        build_context=request.build_context,
        build_prompt_grounding=request.build_prompt_grounding,
        build_expected_answer_check=request.build_expected_answer_check,
    )
