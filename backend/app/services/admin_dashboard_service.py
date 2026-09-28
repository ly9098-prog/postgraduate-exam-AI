import asyncio
from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Date, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.time_utils import shanghai_date_utc_range, shanghai_today
from app.models.admin import AuditLog
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.models.user import User


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    return shanghai_date_utc_range(day)


def _normalize_daily_range(
    created_from: date | None, created_to: date | None
) -> tuple[date, date]:
    end = created_to or shanghai_today()
    start = created_from or end - timedelta(days=6)
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")
    if end - start > timedelta(days=365):
        raise ValueError("统计查询跨度不能超过 1 年")
    return start, end


async def compute_dashboard_overview(db: AsyncSession) -> dict:
    today_start, tomorrow_start = _day_bounds(shanghai_today())
    return {
        "users_total": int(
            await db.scalar(select(func.count()).select_from(User)) or 0
        ),
        "users_new_today": int(
            await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.created_at >= today_start, User.created_at < tomorrow_start)
            )
            or 0
        ),
        "questions_total": int(
            await db.scalar(select(func.count()).select_from(Question)) or 0
        ),
        "questions_pending_review": int(
            await db.scalar(
                select(func.count())
                .select_from(Question)
                .where(Question.review_status == "pending")
            )
            or 0
        ),
        "imports_total": int(
            await db.scalar(select(func.count()).select_from(QuestionImport)) or 0
        ),
        "imports_pending": int(
            await db.scalar(
                select(func.count())
                .select_from(QuestionImport)
                .where(QuestionImport.status == "pending")
            )
            or 0
        ),
        "audit_critical_today": int(
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.severity == "critical",
                    AuditLog.created_at >= today_start,
                    AuditLog.created_at < tomorrow_start,
                )
            )
            or 0
        ),
        "cache": cache.get_stats(),
    }


async def get_dashboard_overview(db: AsyncSession) -> dict:
    key = "admin:dashboard:overview"
    cached_data = await cache.get(key)
    if cached_data is not None:
        return cached_data

    lock_key = f"{key}:lock"
    lock_value = uuid4().hex
    locked = await cache.acquire_lock(lock_key, lock_value, ttl=10)
    if not locked:
        await asyncio.sleep(0.1)
        cached_data = await cache.get(key)
        if cached_data is not None:
            return cached_data
        return await compute_dashboard_overview(db)

    try:
        data = await compute_dashboard_overview(db)
        await cache.set(key, data, ttl=cache.jitter_ttl(300, 0.1))
        return data
    finally:
        await cache.release_lock(lock_key, lock_value)


async def get_dashboard_daily(
    db: AsyncSession, created_from: date | None, created_to: date | None
) -> list[dict]:
    start, end = _normalize_daily_range(created_from, created_to)

    # admin:stats:daily:{from}:{to} — short-range windows are cache-friendly;
    # long custom ranges share the same TTL + jitter to avoid stampedes.
    if (end - start).days <= 31:
        stats_key = f"admin:stats:daily:{start.isoformat()}:{end.isoformat()}"
        try:
            cached_daily = await cache.get(stats_key)
        except Exception:
            cached_daily = None
        if cached_daily is not None:
            return [
                {**item, "date": date.fromisoformat(item["date"])}
                for item in cached_daily
            ]
    else:
        stats_key = None

    items = await _compute_dashboard_daily(db, start, end)

    if stats_key is not None:
        try:
            await cache.set(
                stats_key,
                [{**item, "date": item["date"].isoformat()} for item in items],
                ttl=cache.jitter_ttl(300, 0.1),
            )
        except Exception:
            pass
    return items


async def _compute_dashboard_daily(
    db: AsyncSession, start: date, end: date
) -> list[dict]:
    start_dt = shanghai_date_utc_range(start)[0]
    end_dt = shanghai_date_utc_range(end + timedelta(days=1))[0]

    bind = await db.connection()

    async def grouped(model):
        if bind.sync_connection.dialect.name == "sqlite":
            bucket = func.date(model.created_at, "+8 hours")
        else:
            bucket = cast(model.created_at + text("INTERVAL '8 hours'"), Date)
        result = await db.execute(
            select(bucket, func.count())
            .where(model.created_at >= start_dt, model.created_at < end_dt)
            .group_by(bucket)
        )
        return {
            date.fromisoformat(row[0]) if isinstance(row[0], str) else row[0]: int(
                row[1]
            )
            for row in result.all()
        }

    users = await grouped(User)
    questions = await grouped(Question)
    imports = await grouped(QuestionImport)
    audits = await grouped(AuditLog)

    items = []
    current = start
    while current <= end:
        items.append(
            {
                "date": current,
                "users_new": users.get(current, 0),
                "questions_new": questions.get(current, 0),
                "imports_new": imports.get(current, 0),
                "audits_total": audits.get(current, 0),
            }
        )
        current += timedelta(days=1)
    return items


async def get_dashboard_question_stats(db: AsyncSession) -> dict:
    async def grouped(column):
        result = await db.execute(
            select(column, func.count())
            .select_from(Question)
            .group_by(column)
            .order_by(func.count().desc())
        )
        return [
            {"name": row[0] if row[0] is not None else "unknown", "count": int(row[1])}
            for row in result.all()
        ]

    return {
        "by_subject": await grouped(Question.subject_id),
        "by_review_status": await grouped(Question.review_status),
        "by_difficulty": await grouped(Question.difficulty),
    }
