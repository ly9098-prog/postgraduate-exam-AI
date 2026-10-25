"""Vector-backed similar-question recall and rule fallback loading."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from app.models.question import Question

Recommendation = dict[str, Any]


@dataclass(slots=True)
class SimilarRecallRequest:
    db: Any
    user_id: int
    source_question_id: int
    scope_ids: list[int]
    excluded_sub: Any | None
    logger: Logger
    search_similar: Callable[..., Awaitable[dict]]
    revision_condition: Callable[[list[int]], Any]


async def load_similar_vector_questions(
    request: SimilarRecallRequest,
) -> tuple[list[Question], dict[int, dict]]:
    """Return vector candidates in provider order without trusting their filters."""
    try:
        result = await request.search_similar(
            db=request.db,
            user_id=request.user_id,
            question_id=request.source_question_id,
        )
        recommendations = (
            result.get("recommendations", []) if result.get("enabled") else []
        )
        if not recommendations:
            return [], {}
        return await _load_recommendations(request, recommendations)
    except Exception:
        request.logger.warning("similar 模式向量召回失败，回退到随机", exc_info=True)
        return [], {}


async def _load_recommendations(
    request: SimilarRecallRequest, recommendations: list[Recommendation]
) -> tuple[list[Question], dict[int, dict]]:
    rec_ids = [item["question_id"] for item in recommendations]
    conditions = [
        Question.id.in_(rec_ids),
        Question.id != request.source_question_id,
        Question.is_active,
        Question.subject_id.in_(request.scope_ids),
        request.revision_condition(request.scope_ids),
    ]
    if request.excluded_sub is not None:
        conditions.append(Question.id.notin_(request.excluded_sub))
    result = await request.db.execute(
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
    )
    by_id = {question.id: question for question in result.scalars().all()}
    questions: list[Question] = []
    metadata: dict[int, dict] = {}
    for recommendation in recommendations:
        question = by_id.get(recommendation["question_id"])
        if question:
            questions.append(question)
            metadata[question.id] = {
                "recommend_reason": recommendation.get("match_reason", "向量相似"),
                "recommend_score": recommendation.get("recommend_score"),
                "strategy": "vector",
                "similarity": recommendation.get("similarity"),
            }
    return questions, metadata


async def load_similar_fill_questions(
    db: Any,
    conditions: list[Any],
    need: int,
    random_sample: Callable[..., Any],
) -> list[Question]:
    """Load a bounded random supplement for a partial vector result."""
    total = (
        await db.execute(
            select(func.count()).select_from(
                select(Question).where(and_(*conditions)).subquery()
            )
        )
    ).scalar() or 0
    query = (
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
    )
    query = random_sample(query, total, need, Question.id)
    result = await db.execute(query)
    return list(result.scalars().all())
