"""Leitner candidate query construction and layered scheduling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from app.models.question import Question
from app.models.user_question_state import UserQuestionState

DUE_STATE_CONDITION = (
    UserQuestionState.id.is_(None),
    UserQuestionState.next_review_at.is_(None),
)

RandomSampler = Callable[..., Any]
ScalarExecutor = Callable[[Any], Awaitable[Any]]
ResultExecutor = Callable[[Any], Awaitable[Any]]


@dataclass(slots=True)
class LeitnerQueryRequest:
    user_id: int
    base_conditions: list[Any]
    mode: str
    count: int
    excluded_sub: Any | None
    random_sample: RandomSampler
    scalar: ScalarExecutor
    execute: ResultExecutor


async def leitner_query(
    request: LeitnerQueryRequest,
    due_condition,
    exclude_ids: set[int] | None = None,
    limit: int | None = None,
    extra_order=None,
) -> list[Question]:
    """Outer-join user state and apply one due condition."""
    conds = list(request.base_conditions)
    if request.excluded_sub is not None:
        conds.append(Question.id.notin_(request.excluded_sub))
    if exclude_ids:
        conds.append(Question.id.notin_(exclude_ids))

    base_query = (
        select(Question)
        .outerjoin(
            UserQuestionState,
            and_(
                UserQuestionState.question_id == Question.id,
                UserQuestionState.user_id == request.user_id,
            ),
        )
        .where(and_(*conds, due_condition))
        .options(selectinload(Question.subject_ref))
    )
    limit_value = limit if limit is not None else request.count
    if extra_order is not None:
        query = base_query.order_by(extra_order).limit(limit_value)
    elif request.mode == "random":
        total = await _count_matching_rows(request, conds, due_condition)
        query = request.random_sample(base_query, total, limit_value, Question.id)
    else:
        query = base_query.order_by(Question.id.asc()).limit(limit_value)
    result = await request.execute(query)
    return list(result.scalars().all())


async def _count_matching_rows(
    request: LeitnerQueryRequest, conds, due_condition
) -> int:
    count_base = (
        select(Question.id)
        .outerjoin(
            UserQuestionState,
            and_(
                UserQuestionState.question_id == Question.id,
                UserQuestionState.user_id == request.user_id,
            ),
        )
        .where(and_(*conds, due_condition))
        .subquery()
    )
    total = await request.scalar(select(func.count()).select_from(count_base))
    return int(total or 0)


def due_condition(now):
    return or_(*DUE_STATE_CONDITION, UserQuestionState.next_review_at <= now)


def due_soon_condition(soon):
    return or_(*DUE_STATE_CONDITION, UserQuestionState.next_review_at <= soon)


def oldest_first_order():
    return UserQuestionState.last_answered_at.asc().nulls_first()
