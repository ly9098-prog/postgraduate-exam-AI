"""Aggregate practice-record statistics without owning session helpers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import shanghai_date_utc_range, shanghai_today
from app.models.admin import Subject
from app.models.practice_record import PracticeRecord


async def load_practice_totals(db: AsyncSession, user_id: int) -> tuple[int, int]:
    result = await db.execute(
        select(
            func.count(PracticeRecord.id),
            func.coalesce(func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0),
        ).where(PracticeRecord.user_id == user_id)
    )
    row = result.one()
    return int(row[0]), int(row[1])


async def load_subject_breakdown(db: AsyncSession, user_id: int) -> list[dict]:
    result = await db.execute(
        select(
            PracticeRecord.subject_id,
            Subject.code,
            Subject.name,
            func.count(PracticeRecord.id),
            func.coalesce(func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0),
        )
        .outerjoin(Subject, PracticeRecord.subject_id == Subject.id)
        .where(PracticeRecord.user_id == user_id)
        .group_by(PracticeRecord.subject_id, Subject.code, Subject.name)
    )
    breakdown = []
    for row in result.all():
        answered = int(row[3])
        correct = int(row[4])
        breakdown.append(
            {
                "subject_id": row[0],
                "subject_code": row[1] or "",
                "subject_name": row[2] or "",
                "answered": answered,
                "correct": correct,
                "accuracy": accuracy(correct, answered),
            }
        )
    return breakdown


async def load_daily_breakdown(
    db: AsyncSession,
    user_id: int,
    days: int,
    china_date_expr: Callable,
) -> list[dict]:
    today = shanghai_today()
    since = shanghai_date_utc_range(today - timedelta(days=days - 1))[0]
    day_expr = await china_date_expr(db, PracticeRecord.answered_at)
    result = await db.execute(
        select(
            day_expr,
            func.count(PracticeRecord.id),
            func.coalesce(func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .group_by(day_expr)
        .order_by(day_expr)
    )
    daily_map = {
        str(row[0]): {"answered": row[1], "correct": row[2]}
        for row in result.all()
    }

    stats = []
    for offset in range(days):
        day = (today - timedelta(days=days - 1 - offset)).isoformat()
        entry = daily_map.get(day, {"answered": 0, "correct": 0})
        stats.append({"date": day, **entry})
    return stats


def accuracy(correct: int, answered: int) -> float:
    return round(correct / answered, 4) if answered > 0 else 0.0
