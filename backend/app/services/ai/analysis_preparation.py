"""Load inputs and decide the initial cache path for error analysis."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy import select

from app.models.question import Question
from app.models.wrong_question import WrongQuestion
from app.services.ai.analysis_responses import vision_input_missing_response


@dataclass(slots=True)
class AnalysisPreparationRequest:
    db: Any
    user_id: int
    wrong_question_id: int
    force_regenerate: bool
    logger: Logger
    load_runtime: Callable[..., Awaitable[Any]]
    build_grounding: Callable[..., Any]
    revision_guard: Callable[..., Awaitable[dict | None]]
    collect_visual_sources: Callable[[Any], list]
    has_visual_slot: Callable[[Any], bool]
    load_knowledge_points: Callable[..., Awaitable[dict]]
    input_signature: Callable[..., str]
    model_signature: Callable[[Any], str | None]
    cached_response: Callable[..., dict | None]
    cache_age: Callable[[Any], Any]
    stale_reason: Callable[..., Any]


@dataclass(slots=True)
class AnalysisPreparation:
    wrong_question: Any
    question: Any
    answer_grounding: Any
    visual_sources: list
    requires_visual: bool
    knowledge_points: list
    runtime: Any
    input_signature: str
    model_signature: str | None
    force: bool
    response: dict | None = None


async def prepare_analysis(
    request: AnalysisPreparationRequest,
) -> AnalysisPreparation:
    wrong_question, question = await _load_analysis_pair(request)
    guarded = await _guard_revision(request, wrong_question, question)
    if guarded is not None:
        return _early_return(
            request, wrong_question, question, guarded, [], False, [], None, "", None
        )

    visual_sources, requires_visual = _visual_requirements(request, question)
    if requires_visual and not visual_sources:
        response = _missing_visual_response(request, wrong_question, question)
        return _early_return(
            request,
            wrong_question,
            question,
            response,
            visual_sources,
            requires_visual,
            [],
            None,
            "",
            None,
        )

    return await _prepare_material_analysis(
        request, wrong_question, question, visual_sources, requires_visual
    )


async def _prepare_material_analysis(
    request: AnalysisPreparationRequest,
    wrong_question: Any,
    question: Any,
    visual_sources: list,
    requires_visual: bool,
) -> AnalysisPreparation:
    knowledge_points, runtime = await _load_materials(request, question)
    grounding = request.build_grounding(
        question_type=getattr(question, "question_type", None),
        content=question.content,
        options=question.options,
        correct_answer=question.answer,
        user_answer=wrong_question.wrong_answer,
    )
    input_signature = request.input_signature(
        wrong_question, question, knowledge_points, visual_sources=visual_sources
    )
    model_signature = request.model_signature(runtime)
    response = _initial_cache_response(
        request,
        wrong_question,
        requires_visual=requires_visual,
        input_signature=input_signature,
        model_signature=model_signature,
    )
    return AnalysisPreparation(
        wrong_question=wrong_question,
        question=question,
        answer_grounding=grounding,
        visual_sources=visual_sources,
        requires_visual=requires_visual,
        knowledge_points=knowledge_points,
        runtime=runtime,
        input_signature=input_signature,
        model_signature=model_signature,
        force=bool(request.force_regenerate),
        response=response,
    )


async def _load_analysis_pair(request):
    wq_result = await request.db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id == request.wrong_question_id,
            WrongQuestion.user_id == request.user_id,
        )
    )
    wrong_question = wq_result.scalar_one_or_none()
    if not wrong_question:
        raise ValueError("错题记录不存在")

    # Teaching context follows the current projection while the immutable
    # attempt revision is checked separately below.
    q_result = await request.db.execute(
        select(Question).where(Question.id == wrong_question.question_id)
    )
    question = q_result.scalar_one_or_none()
    if question is None:
        raise ValueError("题目不存在")
    return wrong_question, question


async def _guard_revision(request, wrong_question, question):
    return await request.revision_guard(
        request.db, wrong_question=wrong_question, question=question
    )


def _visual_requirements(request, question):
    visual_sources = request.collect_visual_sources(question)
    requires_visual = bool(visual_sources) or request.has_visual_slot(question)
    return visual_sources, requires_visual


def _missing_visual_response(request, wrong_question, question):
    request.logger.info(
        "ai.error_analysis.image_missing wq_id=%d question_id=%d "
        "reason=declared_visual_without_source",
        wrong_question.id,
        question.id,
    )
    return vision_input_missing_response()


async def _load_materials(request, question):
    knowledge_map = await request.load_knowledge_points(request.db, [int(question.id)])
    knowledge_points = knowledge_map.get(int(question.id), [])
    # Resolve the selected model before the cache decision so a configuration
    # change deterministically invalidates old advice.
    runtime = await request.load_runtime(request.db)
    return knowledge_points, runtime


def _initial_cache_response(
    request,
    wrong_question,
    *,
    requires_visual,
    input_signature,
    model_signature,
):
    if request.force_regenerate:
        request.logger.info(
            "force regenerate error analysis wq_id=%d user_id=%d",
            wrong_question.id,
            request.user_id,
        )
        return None

    cached = request.cached_response(
        wrong_question,
        requires_visual=requires_visual,
        expected_input_signature=input_signature,
        expected_model_signature=model_signature,
    )
    if cached is not None:
        request.logger.info(
            "ai.error_analysis.cache_hit wq_id=%d user_id=%d age_ms=%s model=%s",
            wrong_question.id,
            request.user_id,
            request.cache_age(wrong_question.ai_analysis),
            ((wrong_question.ai_analysis or {}).get("_meta") or {}).get("model")
            or "unknown",
        )
        return cached

    reason = request.stale_reason(
        wrong_question.ai_analysis,
        requires_visual=requires_visual,
        expected_input_signature=input_signature,
        expected_model_signature=model_signature,
    )
    request.logger.info(
        "ai.error_analysis.cache_miss wq_id=%d user_id=%d reason=%s",
        wrong_question.id,
        request.user_id,
        reason or "unknown",
    )
    return None


def _early_return(
    request,
    wrong_question,
    question,
    response,
    visual_sources,
    requires_visual,
    knowledge_points,
    runtime,
    input_signature,
    model_signature,
):
    return AnalysisPreparation(
        wrong_question=wrong_question,
        question=question,
        answer_grounding=None,
        visual_sources=visual_sources,
        requires_visual=requires_visual,
        knowledge_points=knowledge_points,
        runtime=runtime,
        input_signature=input_signature,
        model_signature=model_signature,
        force=bool(request.force_regenerate),
        response=response,
    )
