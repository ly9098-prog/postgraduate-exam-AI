"""Lock and post-lock preparation contracts for AI error analysis."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from logging import Logger
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.analysis_responses import (
    analysis_model_unconfigured_response,
    vision_input_missing_response,
)


@dataclass(slots=True)
class AnalysisLease:
    lock_key: str
    lock_value: str
    have_lock: bool


@dataclass(slots=True)
class LockedCacheReview:
    input_signature: str
    response: dict | None = None


@dataclass(slots=True)
class LockedAnalysisInputs:
    image_data_urls: list[str] = field(default_factory=list)
    context: dict | None = None
    answer_grounding: Any = None
    prompt_grounding: Any = None
    expected_answer_check: Any = None
    model_timeout_sec: int | float | None = None
    response: dict | None = None


async def begin_analysis_generation(
    *,
    wrong_question_id: int,
    user_id: int,
    timeout_sec: int | float,
    lock_grace_sec: int,
    generating: set[int],
    cache: Any,
) -> AnalysisLease | None:
    """Reserve local and cross-process generation; None means already running."""
    if wrong_question_id in generating:
        return None
    generating.add(wrong_question_id)
    lock_key = f"ai:error_analysis:{wrong_question_id}"
    lock_value = f"{user_id}:{uuid4().hex}"
    try:
        have_lock = await cache.acquire_lock(
            lock_key, lock_value, ttl=timeout_sec + lock_grace_sec
        )
    except Exception:
        generating.discard(wrong_question_id)
        raise
    if not have_lock and cache.is_enabled:
        generating.discard(wrong_question_id)
        return None
    return AnalysisLease(lock_key, lock_value, have_lock)


async def finish_analysis_generation(
    *,
    wrong_question_id: int,
    generating: set[int],
    lease: AnalysisLease | None,
    cache: Any,
) -> None:
    generating.discard(wrong_question_id)
    if lease is None or not lease.have_lock:
        return
    try:
        await cache.release_lock(lease.lock_key, lease.lock_value)
    except Exception:
        pass


async def review_locked_analysis_cache(
    db: AsyncSession,
    wrong_question: Any,
    question: Any,
    *,
    user_id: int,
    force: bool,
    requires_visual: bool,
    stored_visual_sources: list[str],
    knowledge_points: list[str],
    model_signature: str,
    input_signature: Callable[..., str],
    cached_response: Callable[..., dict | None],
    cache_age: Callable[[Any], int | None],
    logger: Logger,
) -> LockedCacheReview:
    await db.refresh(wrong_question)
    signature = input_signature(
        wrong_question,
        question,
        knowledge_points,
        visual_sources=stored_visual_sources,
    )
    if force:
        return LockedCacheReview(signature)
    cached = cached_response(
        wrong_question,
        requires_visual=requires_visual,
        expected_input_signature=signature,
        expected_model_signature=model_signature,
    )
    if cached is None:
        return LockedCacheReview(signature)
    logger.info(
        "ai.error_analysis.cache_hit_after_lock wq_id=%d user_id=%d age_ms=%s",
        wrong_question.id,
        user_id,
        cache_age(wrong_question.ai_analysis),
    )
    return LockedCacheReview(signature, cached)


async def prepare_locked_analysis_inputs(
    wrong_question: Any,
    question: Any,
    *,
    current_answer_grounding: Any,
    requires_visual: bool,
    runtime: Any,
    knowledge_points: list[str],
    timeout_sec: int | float,
    logger: Logger,
    prepare_visual_inputs: Callable[..., Any],
    build_context: Callable[..., dict],
    build_prompt_grounding: Callable[[Any], Any],
    build_expected_answer_check: Callable[[Any], Any],
) -> LockedAnalysisInputs:
    image_data_urls, visual_meta = await prepare_visual_inputs(question)
    structured_visual = str(visual_meta.get("structured_visual") or "")

    if requires_visual and not image_data_urls:
        logger.info(
            "ai.error_analysis.image_load_failed wq_id=%d question_id=%d declared_sources=%d",
            wrong_question.id,
            question.id,
            int(visual_meta.get("declared_source_count") or 0),
        )
        return LockedAnalysisInputs(response=vision_input_missing_response())
    if runtime is None:
        return LockedAnalysisInputs(
            image_data_urls=image_data_urls,
            response=analysis_model_unconfigured_response(image_data_urls),
        )

    context = build_context(wrong_question, question, knowledge_points)
    context["question"]["structured_visual"] = structured_visual
    prompt_grounding = build_prompt_grounding(current_answer_grounding)
    expected_answer_check = build_expected_answer_check(current_answer_grounding)
    return LockedAnalysisInputs(
        image_data_urls=image_data_urls,
        context=context,
        answer_grounding=current_answer_grounding,
        prompt_grounding=prompt_grounding,
        expected_answer_check=expected_answer_check,
        model_timeout_sec=timeout_sec,
    )
