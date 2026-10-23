from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every relationship before create_all
from app.core.database import Base
from app.models.study_plan import StudyPlan, StudyPlanDay
from app.models.user import User
from app.services import study_plan_service as service

TODAY = date(2026, 10, 23)


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'study-plan-concurrency.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session_factory) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                User(id=1, openid="study-plan-snapshot-user"),
                StudyPlan(
                    id=1,
                    user_id=1,
                    target_date=date(2026, 12, 20),
                    daily_minutes=90,
                    weekly_days=6,
                    priority_mode="balanced",
                    revision=1,
                    is_active=True,
                ),
                StudyPlanDay(
                    plan_id=1,
                    plan_revision=1,
                    plan_date=TODAY,
                    target_minutes=45,
                    is_rest_day=False,
                    allocation_json={
                        "review": 15,
                        "weakness": 10,
                        "new": 10,
                        "exam": 10,
                    },
                    basis_json={"day_start_minute": 0, "winner": True},
                ),
            ]
        )
        await db.commit()


@pytest.mark.asyncio
async def test_day_snapshot_conflict_keeps_outer_plan_changes(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)

        async with session_factory() as db:
            plan = await db.scalar(select(StudyPlan).where(StudyPlan.id == 1))
            plan.daily_minutes = 120
            plan.revision = 2
            await db.flush()

            original_scalar = db.scalar
            stale_reads = 0

            async def stale_first_snapshot_read(statement, *args, **kwargs):
                nonlocal stale_reads
                stale_reads += 1
                if stale_reads == 1:
                    return None
                return await original_scalar(statement, *args, **kwargs)

            db.scalar = stale_first_snapshot_read
            day = await service._ensure_day_snapshot(
                db,
                plan=plan,
                today=TODAY,
                hub={},
                exam_suggestion=None,
                prior_active_days=0,
                day_start_minute=0,
            )
            await db.commit()

        async with session_factory() as db:
            saved_plan = await db.scalar(select(StudyPlan).where(StudyPlan.id == 1))
            count = await db.scalar(select(func.count(StudyPlanDay.id)))

        assert stale_reads == 2
        assert day.target_minutes == 45
        assert day.basis_json == {"day_start_minute": 0, "winner": True}
        assert saved_plan.daily_minutes == 120
        assert saved_plan.revision == 2
        assert count == 1
    finally:
        await engine.dispose()
