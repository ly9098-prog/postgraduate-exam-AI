"""Query scored-practice fill candidates without owning filters or transactions."""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

    from app.models.question import Question


def build_random_fill_query(
    conditions: list[ColumnElement[bool]],
    fill_total: int,
    remaining: int,
) -> Select[tuple[Question]]:
    from sqlalchemy import and_, func, select
    from sqlalchemy.orm import selectinload

    from app.models.question import Question

    if fill_total <= remaining:
        return (
            select(Question)
            .where(and_(*conditions))
            .options(selectinload(Question.subject_ref))
            .order_by(Question.id.asc())
        )
    if fill_total <= 2000:
        return (
            select(Question)
            .where(and_(*conditions))
            .options(selectinload(Question.subject_ref))
            .order_by(func.random())
            .limit(remaining)
        )
    offset = random.randint(0, fill_total - remaining)
    return (
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
        .order_by(Question.id.asc())
        .offset(offset)
        .limit(remaining)
    )


async def load_random_fill_questions(
    db: AsyncSession,
    conditions: list[ColumnElement[bool]],
    remaining: int,
) -> Sequence[Question]:
    from sqlalchemy import and_, func, select

    from app.models.question import Question

    fill_count_q = select(func.count(Question.id)).where(and_(*conditions))
    fill_total = (await db.execute(fill_count_q)).scalar() or 0
    fill_q = build_random_fill_query(conditions, fill_total, remaining)
    fill_result = await db.execute(fill_q)
    return fill_result.scalars().all()


async def load_repeat_fill_questions(
    db: AsyncSession,
    conditions: list[ColumnElement[bool]],
    remaining: int,
    sample_query: Callable[..., Select[tuple[Question]]],
) -> Sequence[Question]:
    from sqlalchemy import and_, func, select
    from sqlalchemy.orm import selectinload

    from app.models.question import Question

    fill_q2_base = (
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
    )
    fill_count2 = (
        await db.execute(select(func.count(Question.id)).where(and_(*conditions)))
    ).scalar() or 0
    fill_q2 = sample_query(
        fill_q2_base,
        total_count=fill_count2,
        need=remaining,
        id_col=Question.id,
    )
    fill_result2 = await db.execute(fill_q2)
    return fill_result2.scalars().all()
