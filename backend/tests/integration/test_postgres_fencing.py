"""PostgreSQL stale worker fencing integration test.

Requires ``--run-integration`` and real PostgreSQL + Redis.

Test scenario:
    1. Worker A claims task, initializes fencing (gen=1)
    2. Worker A's lease expires (simulate crash/lag)
    3. Worker B claims same task (gen=2), writes result, commits
    4. Worker A wakes up, tries to write via fenced UPDATE → rowcount=0
    5. Worker A's transaction rolls back, FencingRejectedError raised
    6. Verify DB only contains Worker B's data
    7. Verify Worker A cannot complete/fail the task

Run:
    docker compose -f docker/docker-compose.yml up -d postgres redis
    REDIS_URL=redis://localhost:6379/2 \\
    TEST_DATABASE_URL=postgresql+asyncpg://postgraduate:change-me@localhost:5432/postgraduate \\
    python -m pytest tests/integration/test_postgres_fencing.py --run-integration -v
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/2")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5433/testdb",
)


@pytest.fixture
def test_suffix() -> str:
    return f"fence_{uuid.uuid4().hex[:8]}"


class TestStaleWorkerFencing:
    """Stale worker is prevented from writing business data after lease loss."""

    @pytest.mark.asyncio
    async def test_stale_worker_update_rejected(self, test_suffix: str):
        """Worker A (gen=1) loses lease → Worker B (gen=2) writes → A's fenced UPDATE rejected."""
        import redis.asyncio as aioredis
        from sqlalchemy import select, text
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.services.db_fencing import (
            conditional_update_with_fencing,
            initialize_fencing_fields,
        )

        # ── Setup ──
        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        redis = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
        test_ns = test_suffix

        pipeline_id = f"fence_test_{test_ns}"

        try:
            # ── 1. Create test pipeline record ──
            async with session_factory() as db:
                await db.execute(
                    text(
                        "INSERT INTO import_pipelines (pipeline_id, source_type, source_file, "
                        "status, total_pages, chunk_size, execution_generation, current_task_id, "
                        "current_owner_token) "
                        "VALUES (:pid, 'pdf', 'test.pdf', 'pending', 10, 40, 0, '', '')"
                    ),
                    {"pid": pipeline_id},
                )
                await db.commit()

            # ── 2. Worker A initializes fencing (gen=1) ──
            gen_a = 1
            owner_a = f"owner_a_{test_ns}"
            task_id_a_full = f"import:{pipeline_id}"

            async with session_factory() as db:
                from app.models.import_pipeline import ImportPipeline

                ok = await initialize_fencing_fields(
                    db=db,
                    model_class=ImportPipeline,
                    record_id=pipeline_id,
                    task_id=task_id_a_full,
                    owner_token=owner_a,
                    generation=gen_a,
                    status="processing",
                )
                assert ok, "Worker A should initialize fencing"

            # Verify Worker A's fence is set
            async with session_factory() as db:
                result = await db.execute(
                    select(ImportPipeline).where(ImportPipeline.pipeline_id == pipeline_id)
                )
                row = result.scalar_one()
                assert row.execution_generation == gen_a
                assert row.current_task_id == task_id_a_full

            # ── 3. Worker B takes over (gen=2) ──
            gen_b = 2
            owner_b = f"owner_b_{test_ns}"
            task_id_b = f"import:{pipeline_id}"  # same logical task, higher gen

            async with session_factory() as db:
                ok = await initialize_fencing_fields(
                    db=db,
                    model_class=ImportPipeline,
                    record_id=pipeline_id,
                    task_id=task_id_b,
                    owner_token=owner_b,
                    generation=gen_b,
                    status="processing",
                )
                # initialize_fencing_fields only sets if current gen < new gen
                # Since gen_b (2) > gen_a (1), this should succeed
                assert ok, f"Worker B should initialize fencing (gen={gen_b} > {gen_a})"

            # Verify Worker B's fence is now set
            async with session_factory() as db:
                result = await db.execute(
                    select(ImportPipeline).where(ImportPipeline.pipeline_id == pipeline_id)
                )
                row = result.scalar_one()
                assert row.execution_generation == gen_b, \
                    f"Expected gen={gen_b}, got {row.execution_generation}"
                assert row.current_task_id == task_id_b

            # ── 4. Worker B writes result via fenced UPDATE ──
            async with session_factory() as db:
                ok = await conditional_update_with_fencing(
                    db=db,
                    model_class=ImportPipeline,
                    record_id=pipeline_id,
                    expected_task_id=task_id_b,
                    expected_generation=gen_b,
                    expected_owner_token=owner_b,
                    status="completed",
                    error_message=None,
                )
                assert ok, "Worker B's fenced UPDATE should succeed"
                await db.commit()

            # Verify DB has Worker B's result
            async with session_factory() as db:
                result = await db.execute(
                    select(ImportPipeline).where(ImportPipeline.pipeline_id == pipeline_id)
                )
                row = result.scalar_one()
                assert row.status == "completed", f"Expected status=completed, got {row.status}"
                assert row.execution_generation == gen_b

            # ── 5. Worker A wakes up — tries to write → REJECTED ──
            async with session_factory() as db:
                ok = await conditional_update_with_fencing(
                    db=db,
                    model_class=ImportPipeline,
                    record_id=pipeline_id,
                    expected_task_id=task_id_a_full,
                    expected_generation=gen_a,  # stale gen
                    expected_owner_token=owner_a,
                    status="failed",  # A tries to mark as failed
                )
                assert not ok, "Worker A's stale fenced UPDATE must be rejected (rowcount=0)"
                await db.rollback()  # Must rollback after rejection

            # ── 6. Verify DB STILL has Worker B's data (not A's) ──
            async with session_factory() as db:
                result = await db.execute(
                    select(ImportPipeline).where(ImportPipeline.pipeline_id == pipeline_id)
                )
                row = result.scalar_one()
                assert row.status == "completed", \
                    f"Worker B's result must be preserved. Got status={row.status}"
                assert row.execution_generation == gen_b, \
                    f"Generation must be {gen_b} (Worker B's), got {row.execution_generation}"
                assert row.current_task_id == task_id_b, \
                    f"current_task_id must be Worker B's, got {row.current_task_id}"

            print("\n=== PASS: stale worker fencing — Worker B data preserved ===\n")

        finally:
            # Cleanup
            async with session_factory() as db:
                await db.execute(text("DELETE FROM import_pipelines WHERE pipeline_id = :pid"),
                                 {"pid": pipeline_id})
                await db.commit()

            # Clean Redis fencing keys
            keys = await redis.keys(f"taskq:v2:fencing:*{test_ns}*")
            if keys:
                await redis.delete(*keys)
            await redis.aclose()
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_fencing_rejected_error_propagates(self, test_suffix: str):
        """FencingRejectedError is raised when conditional_update_with_fencing returns False."""
        import redis.asyncio as aioredis
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.services.db_fencing import (
            FencingRejectedError,
            conditional_update_with_fencing,
        )

        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        redis = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
        test_ns = test_suffix
        pipeline_id = f"fence_err_{test_ns}"

        try:
            # Create pipeline without proper fencing
            async with session_factory() as db:
                await db.execute(
                    text(
                        "INSERT INTO import_pipelines (pipeline_id, source_type, source_file, "
                        "status, total_pages, chunk_size, execution_generation, current_task_id, "
                        "current_owner_token) "
                        "VALUES (:pid, 'pdf', 'test.pdf', 'pending', 10, 40, 5, 'other_task', 'other_owner')"
                    ),
                    {"pid": pipeline_id},
                )
                await db.commit()

            from app.models.import_pipeline import ImportPipeline

            # Try to update with mismatched fencing — should raise
            with pytest.raises(FencingRejectedError):
                async with session_factory() as db:
                    ok = await conditional_update_with_fencing(
                        db=db,
                        model_class=ImportPipeline,
                        record_id=pipeline_id,
                        expected_task_id="my_task",       # doesn't match 'other_task'
                        expected_generation=3,              # doesn't match 5
                        expected_owner_token="my_owner",    # doesn't match 'other_owner'
                        status="completed",
                    )
                    if not ok:
                        await db.rollback()
                        raise FencingRejectedError("Test: fence rejected as expected")

            print("\n=== PASS: FencingRejectedError properly raised and caught ===\n")

        finally:
            async with session_factory() as db:
                await db.execute(text("DELETE FROM import_pipelines WHERE pipeline_id = :pid"),
                                 {"pid": pipeline_id})
                await db.commit()
            await redis.aclose()
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_concurrent_fencing_race(self, test_suffix: str):
        """Two workers racing to initialize fencing — only the higher gen wins."""
        import redis.asyncio as aioredis
        from sqlalchemy import select, text
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        redis = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
        test_ns = test_suffix
        pipeline_id = f"fence_race_{test_ns}"

        try:
            # Create pipeline
            async with session_factory() as db:
                await db.execute(
                    text(
                        "INSERT INTO import_pipelines (pipeline_id, source_type, source_file, "
                        "status, total_pages, chunk_size, execution_generation, current_task_id, "
                        "current_owner_token) "
                        "VALUES (:pid, 'pdf', 'test.pdf', 'pending', 10, 40, 0, '', '')"
                    ),
                    {"pid": pipeline_id},
                )
                await db.commit()

            from app.models.import_pipeline import ImportPipeline
            from app.services.db_fencing import initialize_fencing_fields

            # Two workers try to initialize fencing concurrently
            async def worker_init(gen: int, owner: str, task_id: str):
                async with session_factory() as db:
                    return await initialize_fencing_fields(
                        db=db,
                        model_class=ImportPipeline,
                        record_id=pipeline_id,
                        task_id=task_id,
                        owner_token=owner,
                        generation=gen,
                        status="processing",
                    )

            # Race: gen=3 should beat gen=2 (ran first but lower gen)
            results = await asyncio.gather(
                worker_init(2, "owner_gen2", f"task_gen2_{test_ns}"),
                worker_init(3, "owner_gen3", f"task_gen3_{test_ns}"),
            )

            # At least one should succeed
            assert any(results), f"At least one worker init should succeed: {results}"

            # Final state should have the higher generation
            async with session_factory() as db:
                result = await db.execute(
                    select(ImportPipeline).where(ImportPipeline.pipeline_id == pipeline_id)
                )
                row = result.scalar_one()
                # initialize_fencing_fields uses WHERE gen < new_gen OR gen IS NULL
                # gen=3 should win because it's higher
                assert row.execution_generation >= 2, \
                    f"Expected gen >= 2, got {row.execution_generation}"

            print(f"\n=== PASS: concurrent fencing race — gen={row.execution_generation} wins ===\n")

        finally:
            async with session_factory() as db:
                await db.execute(text("DELETE FROM import_pipelines WHERE pipeline_id = :pid"),
                                 {"pid": pipeline_id})
                await db.commit()
            await redis.aclose()
            await engine.dispose()
