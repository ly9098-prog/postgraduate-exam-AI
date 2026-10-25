"""V1 repeat-window fallback query construction and execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from app.models.question import Question
from app.services.practice.time_window import excluded_question_subquery

QueryExecutor = Callable[[Any], Awaitable[Any]]
RandomSampler = Callable[..., Any]


@dataclass(slots=True)
class V1FallbackRequest:
    db: Any
    base_conditions: list[Any]
    mode: str
    count: int
    user_id: int
    exclude_answered: bool
    no_repeat_days: int | None
    exclude_ids: set[int] | None
    utcnow: Callable[[], Any]
    random_sample: RandomSampler
    execute: QueryExecutor


async def run_v1_fallback(request: V1FallbackRequest) -> list[Question]:
    """Load N-day -> 7-day -> 1-day -> unrestricted candidates in order."""
    questions = await _query(request, request.exclude_answered, request.no_repeat_days)
    if len(questions) >= request.count or not request.no_repeat_days:
        return questions

    existing = {question.id for question in questions}
    existing.update(request.exclude_ids or set())
    questions.extend(await _fill(request, questions, existing, 7, True))
    if len(questions) >= request.count:
        return questions[: request.count]

    questions.extend(await _fill(request, questions, existing, 1, True))
    if len(questions) >= request.count:
        return questions[: request.count]

    questions.extend(await _fill(request, questions, existing, None, False))
    return questions[: request.count]


async def _fill(
    request: V1FallbackRequest,
    questions: list[Question],
    existing: set[int],
    days: int | None,
    exclude_answered: bool,
) -> list[Question]:
    if days is not None and (request.no_repeat_days or 0) <= days:
        return []
    more = await _query(
        request,
        exclude_answered,
        days,
        extra_exclude_ids=existing,
        limit=request.count - len(questions),
    )
    existing.update(question.id for question in more)
    return more


async def _query(
    request: V1FallbackRequest,
    excl_answered: bool,
    excl_days: int | None,
    extra_exclude_ids: set[int] | None = None,
    limit: int | None = None,
) -> list[Question]:
    conds = list(request.base_conditions)
    sub = excluded_question_subquery(
        user_id=request.user_id,
        exclude_answered=excl_answered,
        no_repeat_days=excl_days,
        utcnow=request.utcnow,
    )
    if sub is not None:
        conds.append(Question.id.notin_(sub))
    all_excl: set[int] = set()
    all_excl.update(request.exclude_ids or set())
    all_excl.update(extra_exclude_ids or set())
    if all_excl:
        conds.append(Question.id.notin_(all_excl))

    query = (
        select(Question).where(and_(*conds)).options(selectinload(Question.subject_ref))
    )
    if request.mode == "random":
        total_query = select(func.count()).select_from(
            select(Question).where(and_(*conds)).subquery()
        )
        total = (await request.execute(total_query)).scalar() or 0
        query = request.random_sample(query, total, limit or request.count, Question.id)
    else:
        query = query.order_by(Question.id.asc())
    result = await request.execute(
        query.limit(limit if limit is not None else request.count)
    )
    return list(result.scalars().all())
