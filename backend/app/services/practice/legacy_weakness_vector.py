"""Legacy smart weakness-vector strategy retained as a direct fallback branch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from app.models.question import Question


@dataclass(slots=True)
class LegacyWeaknessRequest:
    db: Any
    user_id: int
    subject_code: str
    count: int
    exclude_answered: bool
    no_repeat_days: int | None
    use_leitner: bool
    subject_ids: list[int] | None
    skip_finalize: bool
    request_id: str | None
    experiment_id: int | None
    variant_key: str | None
    logger: Logger
    load_mastery: Callable[..., Awaitable[list[dict]]]
    compute_weak_kps: Callable[..., Awaitable[list[dict]]]
    load_random: Callable[..., Awaitable[list[Question]]]
    vector_recall: Callable[..., Awaitable[list[dict]]]
    load_strategy_config: Callable[..., Awaitable[Any]]
    rerank: Callable[..., Awaitable[tuple[list[Question], dict[int, dict]]]]
    build_excluded: Callable[..., Any | None]
    revision_condition: Callable[[list[int]], Any]
    kp_any_condition: Callable[[list[str]], Any]
    random_sample: Callable[..., Any]
    finalize: Callable[..., Awaitable[tuple[list[Question], dict[int, dict]]]]


async def run_legacy_weakness_vector(request: LegacyWeaknessRequest):
    metadata: dict[int, dict] = {}
    weak_kps = await _load_weak_kps(request)
    if not weak_kps:
        return await _random_without_history(request, metadata)

    kp_names = [kp["name"] for kp in weak_kps[:5]]
    vector_questions = await _load_vector_questions(request, metadata, kp_names)
    vector_questions, metadata = await _apply_strategy_rerank(
        request, vector_questions, metadata, kp_names
    )
    if len(vector_questions) >= request.count:
        return await _finalize(request, vector_questions[: request.count], metadata)

    existing_ids = {q.id for q in vector_questions}
    conditions = _base_fill_conditions(request, existing_ids)
    vector_questions = await _fill_by_weak_kps(
        request, conditions, existing_ids, vector_questions, metadata, kp_names
    )
    vector_questions = await _random_fill(
        request, conditions, existing_ids, vector_questions, metadata
    )
    return await _finalize(request, vector_questions[: request.count], metadata)


async def _load_weak_kps(request: LegacyWeaknessRequest) -> list[dict]:
    try:
        weak_kps = await request.load_mastery(
            request.db, request.user_id, request.subject_code, limit=5
        )
        if weak_kps:
            return weak_kps
    except Exception:
        request.logger.warning(
            "mastery_service.get_user_weak_knowledge_points failed, fallback",
            exc_info=True,
        )
    return await request.compute_weak_kps(
        request.db, request.user_id, request.subject_ids or []
    )


async def _random_without_history(request: LegacyWeaknessRequest, metadata):
    request.logger.info("smart 模式: 无足够做题记录，退化为随机")
    questions = await request.load_random(
        db=request.db,
        user_id=request.user_id,
        subject_code=request.subject_code,
        count=request.count,
        mode="random",
        exclude_answered=request.exclude_answered,
        no_repeat_days=request.no_repeat_days,
        use_leitner=request.use_leitner,
        subject_ids=request.subject_ids,
    )
    for question in questions:
        metadata[question.id] = {
            "recommend_reason": "随机推荐（无足够做题记录）",
            "recommend_score": None,
            "strategy": "random_fallback",
            "similarity": None,
        }
    return await _finalize(request, questions, metadata)


async def _load_vector_questions(request: LegacyWeaknessRequest, metadata, kp_names):
    questions: list[Question] = []
    excluded_sub = request.build_excluded(
        user_id=request.user_id,
        exclude_answered=request.exclude_answered,
        no_repeat_days=request.no_repeat_days,
    )
    try:
        recalls = await request.vector_recall(
            db=request.db,
            user_id=request.user_id,
            subject=request.subject_code,
            query_text=(
                f"科目：{request.subject_code}。请推荐这些薄弱知识点的练习题："
                f"{'、'.join(kp_names)}。要求题目适合查漏补缺和变式训练。"
            ),
            count=request.count,
            exclude_answered=request.exclude_answered,
            no_repeat_days=request.no_repeat_days,
        )
        if not recalls:
            return questions
        rec_ids = [recall["question_id"] for recall in recalls]
        vector_conditions = [
            Question.id.in_(rec_ids),
            Question.is_active,
            Question.subject_id.in_(request.subject_ids or []),
            request.revision_condition(request.subject_ids or []),
        ]
        if excluded_sub is not None:
            vector_conditions.append(Question.id.notin_(excluded_sub))
        result = await request.db.execute(
            select(Question)
            .where(and_(*vector_conditions))
            .options(selectinload(Question.subject_ref))
        )
        by_id = {q.id: q for q in result.scalars().all()}
        for recall in recalls:
            question = by_id.get(recall["question_id"])
            if question:
                questions.append(question)
                metadata[question.id] = {
                    "recommend_reason": f"薄弱知识点推荐：{'、'.join(kp_names[:3])}",
                    "recommend_score": recall.get("recommend_score"),
                    "strategy": "smart_vector",
                    "similarity": recall.get("similarity"),
                }
    except Exception:
        request.logger.warning("smart 模式向量召回失败，回退", exc_info=True)
    return questions


async def _apply_strategy_rerank(request, vector_questions, metadata, kp_names):
    try:
        strategy_config = await request.load_strategy_config(
            request.db,
            "practice_smart",
            strategy_name="default_weakness_vector",
        )
    except Exception:
        request.logger.debug("获取推荐策略配置失败，跳过权重重排", exc_info=True)
        return vector_questions, metadata
    if not strategy_config:
        return vector_questions, metadata
    return await request.rerank(
        request.db,
        request.user_id,
        vector_questions,
        metadata,
        strategy_config,
        kp_names,
    )


def _base_fill_conditions(request: LegacyWeaknessRequest, existing_ids: set[int]):
    conditions = [
        Question.is_active,
        Question.subject_id.in_(request.subject_ids or []),
        request.revision_condition(request.subject_ids or []),
        Question.id.notin_(existing_ids),
    ]
    excluded_sub = request.build_excluded(
        user_id=request.user_id,
        exclude_answered=request.exclude_answered,
        no_repeat_days=request.no_repeat_days,
    )
    if excluded_sub is not None:
        conditions.append(Question.id.notin_(excluded_sub))
    return conditions


async def _fill_by_weak_kps(
    request,
    conditions,
    existing_ids,
    vector_questions,
    metadata,
    kp_names,
):
    kp_cond = request.kp_any_condition(kp_names) if kp_names else None
    if kp_cond is None:
        return vector_questions

    kp_total = (
        await request.db.execute(
            select(func.count()).select_from(
                select(Question).where(and_(*conditions, kp_cond)).subquery()
            )
        )
    ).scalar() or 0
    kp_remaining = request.count - len(vector_questions)
    if kp_total <= 0 or kp_remaining <= 0:
        return vector_questions
    query = (
        select(Question)
        .where(and_(*conditions, kp_cond))
        .options(selectinload(Question.subject_ref))
    )
    query = request.random_sample(
        query, kp_total, min(kp_remaining, kp_total), Question.id
    )
    result = await request.db.execute(query)
    for question in list(result.scalars().all()):
        if question.id in existing_ids:
            continue
        existing_ids.add(question.id)
        vector_questions.append(question)
        metadata[question.id] = {
            "recommend_reason": f"薄弱知识点补齐：{'、'.join(kp_names[:3])}",
            "recommend_score": None,
            "strategy": "kp_fallback",
            "similarity": None,
        }
        if len(vector_questions) >= request.count:
            break
    return vector_questions


async def _random_fill(
    request,
    conditions,
    existing_ids,
    vector_questions,
    metadata,
):
    if len(vector_questions) >= request.count:
        return vector_questions
    remaining = request.count - len(vector_questions)
    count_query = select(func.count()).select_from(
        select(Question)
        .where(and_(*conditions, Question.id.notin_(existing_ids)))
        .subquery()
    )
    total = (await request.db.execute(count_query)).scalar() or 0
    fill_query = (
        select(Question)
        .where(and_(*conditions, Question.id.notin_(existing_ids)))
        .options(selectinload(Question.subject_ref))
    )
    fill_query = request.random_sample(fill_query, total, remaining, Question.id)
    result = await request.db.execute(fill_query)
    random_fill = list(result.scalars().all())
    for question in random_fill:
        metadata[question.id] = {
            "recommend_reason": "随机补齐",
            "recommend_score": None,
            "strategy": "random_fallback",
            "similarity": None,
        }
    vector_questions.extend(random_fill)
    return vector_questions


async def _finalize(request: LegacyWeaknessRequest, questions, metadata):
    return await request.finalize(
        questions,
        metadata,
        request.skip_finalize,
        request.db,
        request.user_id,
        request.subject_code,
        request_id=request.request_id,
        experiment_id=request.experiment_id,
        variant_key=request.variant_key,
    )
