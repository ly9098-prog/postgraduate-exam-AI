"""Practice repeat-window query helpers shared by candidate providers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.models.practice_record import PracticeRecord


def excluded_question_subquery(
    *,
    user_id: int,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    utcnow: Callable[[], Any],
) -> select | None:
    """Build the V1 recently-answered question exclusion subquery."""
    if not exclude_answered and not no_repeat_days:
        return None

    sub = select(PracticeRecord.question_id).where(PracticeRecord.user_id == user_id)
    if no_repeat_days:
        cutoff = utcnow() - timedelta(days=no_repeat_days)
        sub = sub.where(PracticeRecord.answered_at >= cutoff)
    return sub.distinct()
