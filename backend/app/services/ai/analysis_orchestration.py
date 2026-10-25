"""End-to-end orchestration for one locked AI error analysis."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.analysis_execution import (
    AnalysisLease,
    begin_analysis_generation,
    finish_analysis_generation,
    prepare_locked_analysis_inputs,
    review_locked_analysis_cache,
)
from app.services.ai.analysis_invocation import (
    AnalysisInvocationRequest,
    invoke_prepared_analysis,
)
from app.services.ai.analysis_result_review import (
    resolve_analysis_outcome,
    review_analysis_result,
)
from app.services.ai.analysis_responses import generation_in_progress_response


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
    locked_cache = await review_locked_analysis_cache(
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
    input_signature = locked_cache.input_signature
    if locked_cache.response is not None:
        return locked_cache.response

    inputs = await prepare_locked_analysis_inputs(
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
    if inputs.response is not None:
        return inputs.response

    context = inputs.context
    context["answer_grounding"] = inputs.prompt_grounding
    invocation = await invoke_prepared_analysis(
        AnalysisInvocationRequest(
            db=request.db,
            wrong_question=request.wrong_question,
            question=request.question,
            context=context,
            runtime=request.runtime,
            image_data_urls=inputs.image_data_urls,
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
    review = await review_analysis_result(
        invocation,
        image_data_urls=inputs.image_data_urls,
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
    runtime = invocation.runtime
    return await resolve_analysis_outcome(
        request.db,
        review,
        wrong_question=request.wrong_question,
        user_id=request.user_id,
        context=context,
        result=invocation.result,
        image_data_urls=inputs.image_data_urls,
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
