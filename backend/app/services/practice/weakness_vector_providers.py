"""SQL providers for the smart weakness-vector strategy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from app.models.question import Question


@dataclass(slots=True)
class WeaknessVectorProviderRequest:
    db: Any
    user_id: int
    exclude_answered: bool
    no_repeat_days: int | None
    revision_condition: Callable[[list[int]], Any]
    build_excluded: Callable[..., Any | None]
    utcnow: Callable[[], Any]
    random_sample: Callable[..., Any]


async def load_vector_matches(
    request: WeaknessVectorProviderRequest,
    recalls: list[dict],
    scope_ids: list[int],
    exclude_ids: set[int],
) -> list[tuple[Question, dict]]:
    rec_ids = [
        recall["question_id"]
        for recall in recalls
        if recall["question_id"] not in exclude_ids
    ]
    if not rec_ids:
        return []
    conditions = [
        Question.id.in_(rec_ids),
        Question.is_active,
        Question.subject_id.in_(scope_ids),
        request.revision_condition(scope_ids),
    ]
    excluded_sub = _excluded_sub(request)
    if excluded_sub is not None:
        conditions.append(Question.id.notin_(excluded_sub))
    result = await request.db.execute(
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
    )
    by_id = {question.id: question for question in result.scalars().all()}
    return [
        (by_id[recall["question_id"]], recall)
        for recall in recalls
        if recall["question_id"] in by_id and recall["question_id"] not in exclude_ids
    ]


async def load_fill_questions(
    request: WeaknessVectorProviderRequest,
    remaining: int,
    scope_ids: list[int],
    existing_ids: set[int],
) -> list[Question]:
    conditions = [
        Question.is_active,
        Question.subject_id.in_(scope_ids),
        request.revision_condition(scope_ids),
        Question.id.notin_(existing_ids),
    ]
    excluded_sub = _excluded_sub(request)
    if excluded_sub is not None:
        conditions.append(Question.id.notin_(excluded_sub))
    total = (
        await request.db.execute(
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
    query = request.random_sample(query, total, remaining, Question.id)
    return list((await request.db.execute(query)).scalars().all())


def _excluded_sub(request: WeaknessVectorProviderRequest):
    return request.build_excluded(
        user_id=request.user_id,
        exclude_answered=request.exclude_answered,
        no_repeat_days=request.no_repeat_days,
    )
