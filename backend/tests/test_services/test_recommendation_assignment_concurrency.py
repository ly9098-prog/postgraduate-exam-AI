from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every relationship before create_all
from app.core.database import Base
from app.models.recommendation_experiment import RecommendationExperiment
from app.models.recommendation_experiment_assignment import (
    RecommendationExperimentAssignment,
)
from app.models.user import User
from app.services import recommendation_experiment_service as service

VARIANTS = [
    {"key": "A", "strategy": "random", "ratio": 0.5},
    {"key": "B", "strategy": "weakness_vector", "ratio": 0.5},
]


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'recommendation-assignment.db'}",
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
    async with session_factory() as db:
        db.add_all(
            [
                User(id=1, openid="recommendation-assignment-user"),
                RecommendationExperiment(
                    id=1,
                    name="assignment-race",
                    scene="practice_smart",
                    status="running",
                    traffic_ratio=1.0,
                    max_traffic_percent=100.0,
                    variants=VARIANTS,
                    min_sample_size=100,
                ),
            ]
        )
        await db.commit()


async def _seed_assignment(session_factory, *, variant_key: str) -> None:
    async with session_factory() as db:
        strategy = next(
            item["strategy"] for item in VARIANTS if item["key"] == variant_key
        )
        db.add(
            RecommendationExperimentAssignment(
                experiment_id=1,
                user_id=1,
                variant_key=variant_key,
                strategy=strategy,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_assignment_claim_rolls_back_only_its_savepoint(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        await _seed_assignment(session_factory, variant_key="A")

        async with session_factory() as db:
            loser = RecommendationExperimentAssignment(
                experiment_id=1,
                user_id=1,
                variant_key="B",
                strategy="weakness_vector",
            )
            assert await service._claim_assignment(db, loser) is None

            await db.execute(update(User).where(User.id == 1).values(nickname="winner"))
            await db.commit()

        async with session_factory() as db:
            assignments = (
                (await db.execute(select(RecommendationExperimentAssignment)))
                .scalars()
                .all()
            )
            user = await db.get(User, 1)

        assert len(assignments) == 1
        assert assignments[0].variant_key == "A"
        assert user.nickname == "winner"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_assignment_claim_does_not_swallow_non_unique_integrity_errors(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)

        async with session_factory() as db:
            invalid = RecommendationExperimentAssignment(
                experiment_id=1,
                user_id=1,
                variant_key="A",
                strategy=None,
            )
            with pytest.raises(IntegrityError):
                await service._claim_assignment(db, invalid)

            await db.execute(update(User).where(User.id == 1).values(nickname="survives"))
            await db.commit()

        async with session_factory() as db:
            user = await db.get(User, 1)
            count = await db.scalar(
                select(func.count(RecommendationExperimentAssignment.id))
            )

        assert user.nickname == "survives"
        assert count == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_strategy_reloads_winner_after_stale_first_read(
    tmp_path, monkeypatch
):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        await _seed_assignment(session_factory, variant_key="B")

        original_load = service._load_assignment
        load_calls = 0

        async def stale_then_reload(db, *, experiment_id, user_id):
            nonlocal load_calls
            load_calls += 1
            if load_calls == 1:
                return None
            return await original_load(
                db,
                experiment_id=experiment_id,
                user_id=user_id,
            )

        monkeypatch.setattr(service, "_load_assignment", stale_then_reload)

        async with session_factory() as db:
            result = await service.resolve_strategy_for_user(
                db,
                user_id=1,
                scene="practice_smart",
                default_strategy="scored",
            )
            await db.execute(
                update(User).where(User.id == 1).values(nickname="still-open")
            )
            await db.commit()

        assert load_calls == 2
        assert result == {
            "experiment_id": 1,
            "variant_key": "B",
            "strategy": "weakness_vector",
            "source": "experiment",
        }
        async with session_factory() as db:
            user = await db.get(User, 1)
            count = await db.scalar(
                select(func.count(RecommendationExperimentAssignment.id))
            )
        assert user.nickname == "still-open"
        assert count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_assignments_converge_to_one_stable_row(tmp_path, monkeypatch):
    engine, session_factory = await _make_database(tmp_path)
    try:
        await _seed(session_factory)
        original_claim = service._claim_assignment
        barrier = asyncio.Barrier(2)

        async def synchronized_claim(db, assignment):
            await barrier.wait()
            return await original_claim(db, assignment)

        monkeypatch.setattr(service, "_claim_assignment", synchronized_claim)

        async def assign_once():
            async with session_factory() as db:
                result = await service.assign_user_to_variant(
                    db,
                    user_id=1,
                    experiment_id=1,
                )
                await db.commit()
                return result

        results = await asyncio.gather(assign_once(), assign_once())

        async with session_factory() as db:
            rows = (
                (await db.execute(select(RecommendationExperimentAssignment)))
                .scalars()
                .all()
            )

        assert len(rows) == 1
        assert {result["variant_key"] for result in results} == {rows[0].variant_key}
        assert {result["strategy"] for result in results} == {rows[0].strategy}
    finally:
        await engine.dispose()
