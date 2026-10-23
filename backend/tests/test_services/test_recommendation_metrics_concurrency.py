from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every relationship before create_all
from app.core.database import Base
from app.core.time_utils import shanghai_date_utc_range
from app.models.admin import Subject
from app.models.recommendation_log import RecommendationLog
from app.models.recommendation_metrics_daily import RecommendationMetricsDaily
from app.models.user import User
from app.services import recommendation_metrics_service as service

TARGET_DATE = date(2026, 10, 22)


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'recommendation-metrics.db'}",
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session_factory) -> None:
    shown_at = shanghai_date_utc_range(TARGET_DATE)[0]
    async with session_factory() as db:
        db.add_all(
            [
                User(id=1, openid="recommendation-metrics-user"),
                Subject(
                    id=1,
                    code="advanced_math",
                    name="高等数学",
                    level=1,
                    path="advanced_math",
                    sort_order=1,
                    is_active=True,
                ),
                RecommendationLog(
                    user_id=1,
                    question_id=1,
                    subject_id=1,
                    scene="practice_smart",
                    strategy="scored",
                    variant_key=None,
                    shown_at=shown_at,
                ),
            ]
        )
        await db.commit()


@pytest.mark.asyncio
async def test_concurrent_null_variant_aggregates_converge_to_one_row(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        barrier = asyncio.Barrier(2)

        async def aggregate_once():
            async with session_factory() as db:
                await barrier.wait()
                result = await service.aggregate_recommendation_metrics_daily(
                    db,
                    target_date=TARGET_DATE,
                )
                await db.commit()
                return result

        results = await asyncio.gather(aggregate_once(), aggregate_once())

        async with session_factory() as db:
            rows = (
                (
                    await db.execute(
                        select(RecommendationMetricsDaily).where(
                            RecommendationMetricsDaily.date == TARGET_DATE,
                            RecommendationMetricsDaily.variant_key.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            count = await db.scalar(
                select(func.count(RecommendationMetricsDaily.id))
            )

        assert [row["aggregated_rows"] for row in results] == [1, 1]
        assert count == 1
        assert len(rows) == 1
        assert rows[0].exposure_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_aggregation_uses_transaction_advisory_lock():
    db = MagicMock()
    db.get_bind.return_value.dialect.name = "postgresql"
    db.execute = AsyncMock()

    await service._lock_metrics_aggregation(
        db,
        target_date=TARGET_DATE,
        subject_id=None,
    )

    statement = db.execute.await_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "pg_advisory_xact_lock" in compiled
