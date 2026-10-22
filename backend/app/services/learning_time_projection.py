"""Shared Beijing natural-day projections for learning statistics."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date as SQLDate
from sqlalchemy import Integer, cast, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import (
    shanghai_date_utc_range,
    shanghai_today_boundaries,
)


def today_utc() -> datetime:
    """Return China today's 00:00 boundary as naive UTC."""
    return shanghai_today_boundaries()[0]


def date_utc_range(day: date) -> tuple[datetime, datetime]:
    """Return the naive UTC bounds of a Beijing natural day."""
    return shanghai_date_utc_range(day)


async def china_date_expr(db: AsyncSession, column):
    """Bucket a naive-UTC timestamp into a Beijing date."""
    bind = await db.connection()
    if bind.sync_connection.dialect.name == "sqlite":
        return func.date(column, "+8 hours")
    return cast(column + text("INTERVAL '8 hours'"), SQLDate)


async def china_hour_expr(db: AsyncSession, column):
    """Return the Beijing wall-clock hour of a naive-UTC timestamp."""
    bind = await db.connection()
    if bind.sync_connection.dialect.name == "sqlite":
        return cast(func.strftime("%H", column, "+8 hours"), Integer)
    return func.extract("hour", column + text("INTERVAL '8 hours'"))


def coerce_date(value) -> date | None:
    """Normalize SQLite string and PostgreSQL date rows to ``date``."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None
