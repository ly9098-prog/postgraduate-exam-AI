from __future__ import annotations

import asyncio
import os
import uuid

import pytest

asyncpg = pytest.importorskip("asyncpg")
POSTGRES_URL = os.getenv("POMODORO_TEST_POSTGRES_URL", "")
if not POSTGRES_URL:
    pytest.skip(
        "set POMODORO_TEST_POSTGRES_URL to run real PostgreSQL pomodoro concurrency tests",
        allow_module_level=True,
    )

RAW_POSTGRES_URL = POSTGRES_URL
if RAW_POSTGRES_URL.startswith("postgresql+asyncpg://"):
    RAW_POSTGRES_URL = "postgresql://" + RAW_POSTGRES_URL.split("postgresql+asyncpg://", 1)[1]

SQLALCHEMY_POSTGRES_URL = POSTGRES_URL
if SQLALCHEMY_POSTGRES_URL.startswith("postgresql://"):
    SQLALCHEMY_POSTGRES_URL = "postgresql+asyncpg://" + SQLALCHEMY_POSTGRES_URL.split("postgresql://", 1)[1]

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import every model before the service so SQLAlchemy can resolve Subject's
# string-based relationships in the same way the production application does.
import app.models  # noqa: F401,E402
from app.services import pomodoro_service  # noqa: E402


@pytest.fixture
async def pg_schema():
    """Isolated schema containing the real columns/invariants used by the service."""
    schema = "pomo_concurrency_" + uuid.uuid4().hex[:12]
    admin = await asyncpg.connect(RAW_POSTGRES_URL)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    await admin.execute(
        f"""
        CREATE TABLE "{schema}".users (
            id BIGINT PRIMARY KEY,
            openid VARCHAR(64) NOT NULL UNIQUE
        );

        CREATE TABLE "{schema}".subjects (
            id BIGINT PRIMARY KEY,
            parent_id BIGINT NULL,
            code VARCHAR(32) NOT NULL UNIQUE,
            name VARCHAR(64) NOT NULL,
            level SMALLINT NOT NULL DEFAULT 1,
            path VARCHAR(128) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE "{schema}".pomodoro_sessions (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            subject_id BIGINT NULL,
            chapter_id VARCHAR(64) NULL,
            client_start_id VARCHAR(64) NULL,
            preset VARCHAR(16) NOT NULL DEFAULT 'standard',
            work_duration INTEGER NOT NULL DEFAULT 25,
            break_duration INTEGER NOT NULL DEFAULT 5,
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP NULL,
            expected_end_time TIMESTAMP NULL,
            actual_duration INTEGER NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'running',
            notification_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            notification_sent BOOLEAN NOT NULL DEFAULT FALSE,
            notification_sent_at TIMESTAMP NULL,
            notification_error TEXT NULL,
            openid_snapshot VARCHAR(64) NULL,
            paused_at TIMESTAMP NULL,
            total_paused_sec INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_pomodoro_sessions_completed_duration
              CHECK (status != 'completed' OR (end_time >= start_time AND actual_duration >= 0))
        );

        CREATE TABLE "{schema}".pomodoro_pause_intervals (
            id BIGSERIAL PRIMARY KEY,
            session_id BIGINT NOT NULL REFERENCES "{schema}".pomodoro_sessions(id) ON DELETE CASCADE,
            started_at TIMESTAMP NOT NULL,
            ended_at TIMESTAMP NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_pomodoro_pause_intervals_ended_at
                CHECK (ended_at IS NULL OR ended_at > started_at)
        );

        CREATE INDEX ix_pomodoro_sessions_user_status_start
            ON "{schema}".pomodoro_sessions(user_id, status, start_time);
        CREATE INDEX ix_pomodoro_sessions_user_status_end
            ON "{schema}".pomodoro_sessions(user_id, status, end_time);
        CREATE UNIQUE INDEX ux_pomodoro_sessions_one_active_per_user
            ON "{schema}".pomodoro_sessions(user_id)
            WHERE status IN ('running', 'paused');
        CREATE UNIQUE INDEX ux_pomodoro_sessions_user_client_start_id
            ON "{schema}".pomodoro_sessions(user_id, client_start_id)
            WHERE client_start_id IS NOT NULL;
        CREATE INDEX ix_pomodoro_pause_intervals_session_started
            ON "{schema}".pomodoro_pause_intervals(session_id, started_at);
        CREATE UNIQUE INDEX ux_pomodoro_pause_intervals_one_open
            ON "{schema}".pomodoro_pause_intervals(session_id)
            WHERE ended_at IS NULL;

        INSERT INTO "{schema}".users(id, openid) VALUES (101, 'pomo-service-user');
        INSERT INTO "{schema}".subjects(id, code, name, level, path, sort_order, is_active)
            VALUES (201, 'pomo-test-subject', 'Pomodoro Test', 1, '/pomo-test-subject', 0, TRUE);
        """
    )
    try:
        yield schema
    finally:
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


async def _connect(schema: str):
    conn = await asyncpg.connect(RAW_POSTGRES_URL)
    await conn.execute(f'SET search_path TO "{schema}"')
    return conn


@pytest.fixture
async def service_sessions(pg_schema):
    """AsyncSession factory wired to the isolated schema for real service calls."""
    engine = create_async_engine(
        SQLALCHEMY_POSTGRES_URL,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": pg_schema, "timezone": "UTC"}},
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _service_start(factory, client_start_id: str):
    async with factory() as db:
        try:
            row = await pomodoro_service.start_session(
                db,
                user_id=101,
                subject_id=201,
                chapter_id=None,
                preset="standard",
                work_duration=25,
                break_duration=5,
                notification_enabled=False,
                client_start_id=client_start_id,
            )
            await db.commit()
            return "ok", row.id
        except ValueError:
            await db.rollback()
            return "conflict", None


@pytest.mark.asyncio
async def test_concurrent_start_guard_allows_only_one_active_row(pg_schema):
    """Raw invariant smoke test: PostgreSQL itself enforces one active row."""
    c1 = await _connect(pg_schema)
    c2 = await _connect(pg_schema)
    gate = asyncio.Event()

    async def insert(conn, client_start_id):
        await gate.wait()
        try:
            await conn.execute(
                "INSERT INTO pomodoro_sessions(user_id, client_start_id, start_time, status) "
                "VALUES(7, $1, clock_timestamp(), 'running')",
                client_start_id,
            )
            return "ok"
        except asyncpg.UniqueViolationError:
            return "unique"

    try:
        t1 = asyncio.create_task(insert(c1, "device-a"))
        t2 = asyncio.create_task(insert(c2, "device-b"))
        gate.set()
        results = await asyncio.gather(t1, t2)
        assert sorted(results) == ["ok", "unique"]
        count = await c1.fetchval(
            "SELECT COUNT(*) FROM pomodoro_sessions "
            "WHERE user_id=7 AND status IN ('running','paused')"
        )
        assert count == 1
    finally:
        await c1.close()
        await c2.close()


@pytest.mark.asyncio
async def test_for_update_serializes_pause_then_resume_on_same_session(pg_schema):
    """Raw lock smoke test kept as a fast diagnosis when a service test fails."""
    setup = await _connect(pg_schema)
    session_id = await setup.fetchval(
        "INSERT INTO pomodoro_sessions(user_id, client_start_id, start_time, status) "
        "VALUES(9, 'lock-test', clock_timestamp() - interval '1 minute', 'running') RETURNING id"
    )
    await setup.close()

    c1 = await _connect(pg_schema)
    c2 = await _connect(pg_schema)
    pause_locked = asyncio.Event()
    allow_pause_commit = asyncio.Event()
    resume_finished = asyncio.Event()

    async def pause_tx():
        tx = c1.transaction()
        await tx.start()
        try:
            row = await c1.fetchrow(
                "SELECT id, status FROM pomodoro_sessions WHERE id=$1 FOR UPDATE",
                session_id,
            )
            assert row["status"] == "running"
            pause_locked.set()
            await allow_pause_commit.wait()
            started = await c1.fetchval("SELECT clock_timestamp()")
            await c1.execute(
                "INSERT INTO pomodoro_pause_intervals(session_id, started_at) VALUES($1, $2)",
                session_id,
                started,
            )
            await c1.execute(
                "UPDATE pomodoro_sessions SET status='paused', paused_at=$2 WHERE id=$1",
                session_id,
                started,
            )
            await tx.commit()
        except Exception:
            await tx.rollback()
            raise

    async def resume_tx():
        await pause_locked.wait()
        tx = c2.transaction()
        await tx.start()
        try:
            # This SELECT must block behind c1 and then observe c1's committed
            # paused state, matching the service's .with_for_update(...) contract.
            row = await c2.fetchrow(
                "SELECT id, status FROM pomodoro_sessions WHERE id=$1 FOR UPDATE",
                session_id,
            )
            assert row["status"] == "paused"
            open_pause = await c2.fetchrow(
                "SELECT id, started_at FROM pomodoro_pause_intervals "
                "WHERE session_id=$1 AND ended_at IS NULL",
                session_id,
            )
            assert open_pause is not None
            ended = await c2.fetchval("SELECT clock_timestamp()")
            await c2.execute(
                "UPDATE pomodoro_pause_intervals SET ended_at=$2 WHERE id=$1",
                open_pause["id"],
                ended,
            )
            await c2.execute(
                "UPDATE pomodoro_sessions SET status='running', paused_at=NULL WHERE id=$1",
                session_id,
            )
            await tx.commit()
            resume_finished.set()
        except Exception:
            await tx.rollback()
            raise

    try:
        p = asyncio.create_task(pause_tx())
        r = asyncio.create_task(resume_tx())
        await pause_locked.wait()
        await asyncio.sleep(0.05)
        assert not resume_finished.is_set(), "resume unexpectedly bypassed the row lock"
        allow_pause_commit.set()
        await asyncio.gather(p, r)

        verify = await _connect(pg_schema)
        try:
            status = await verify.fetchval(
                "SELECT status FROM pomodoro_sessions WHERE id=$1", session_id
            )
            open_count = await verify.fetchval(
                "SELECT COUNT(*) FROM pomodoro_pause_intervals "
                "WHERE session_id=$1 AND ended_at IS NULL",
                session_id,
            )
            assert status == "running"
            assert open_count == 0
        finally:
            await verify.close()
    finally:
        await c1.close()
        await c2.close()


@pytest.mark.asyncio
async def test_service_concurrent_start_serializes_real_start_session(service_sessions):
    """Different device keys race through the real start_session implementation."""
    gate = asyncio.Event()

    async def run(key: str):
        await gate.wait()
        return await _service_start(service_sessions, key)

    t1 = asyncio.create_task(run("service-device-a"))
    t2 = asyncio.create_task(run("service-device-b"))
    gate.set()
    results = await asyncio.gather(t1, t2)

    assert sorted(result[0] for result in results) == ["conflict", "ok"]
    async with service_sessions() as db:
        count = await db.scalar(
            text(
                "SELECT COUNT(*) FROM pomodoro_sessions "
                "WHERE user_id=101 AND status IN ('running','paused')"
            )
        )
        assert count == 1


@pytest.mark.asyncio
async def test_service_same_client_start_id_is_idempotent_under_race(service_sessions):
    """Lost-response retries racing concurrently must resolve to the same row."""
    gate = asyncio.Event()

    async def run():
        await gate.wait()
        return await _service_start(service_sessions, "same-service-start-id")

    t1 = asyncio.create_task(run())
    t2 = asyncio.create_task(run())
    gate.set()
    first, second = await asyncio.gather(t1, t2)

    assert first[0] == second[0] == "ok"
    assert first[1] == second[1]


@pytest.mark.asyncio
async def test_service_pause_then_resume_waits_for_real_row_lock(service_sessions):
    """Actual pause_session holds the row lock until commit; resume_session waits."""
    status, session_id = await _service_start(service_sessions, "service-lock-resume")
    assert status == "ok"

    pause_db = service_sessions()
    resume_db = service_sessions()
    try:
        paused = await pomodoro_service.pause_session(pause_db, session_id, 101)
        assert paused is not None and paused.status == "paused"

        resume_task = asyncio.create_task(
            pomodoro_service.resume_session(resume_db, session_id, 101)
        )
        await asyncio.sleep(0.05)
        assert not resume_task.done(), "resume unexpectedly bypassed the real service row lock"

        await pause_db.commit()
        resumed = await asyncio.wait_for(resume_task, timeout=2)
        assert resumed is not None and resumed.status == "running"
        await resume_db.commit()

        async with service_sessions() as verify:
            status = await verify.scalar(
                text("SELECT status FROM pomodoro_sessions WHERE id=:id").bindparams(id=session_id)
            )
            open_count = await verify.scalar(
                text(
                    "SELECT COUNT(*) FROM pomodoro_pause_intervals "
                    "WHERE session_id=:id AND ended_at IS NULL"
                ).bindparams(id=session_id)
            )
            assert status == "running"
            assert open_count == 0
    finally:
        await pause_db.close()
        await resume_db.close()


@pytest.mark.asyncio
async def test_service_interrupt_waits_for_inflight_pause_and_closes_timeline(service_sessions):
    """Terminal service calls serialize behind a pause and leave no open interval."""
    status, session_id = await _service_start(service_sessions, "service-lock-interrupt")
    assert status == "ok"

    pause_db = service_sessions()
    interrupt_db = service_sessions()
    try:
        paused = await pomodoro_service.pause_session(pause_db, session_id, 101)
        assert paused is not None and paused.status == "paused"

        terminal_task = asyncio.create_task(
            pomodoro_service.interrupt_session(interrupt_db, session_id, 101)
        )
        await asyncio.sleep(0.05)
        assert not terminal_task.done(), "interrupt unexpectedly bypassed the real service row lock"

        await pause_db.commit()
        terminal = await asyncio.wait_for(terminal_task, timeout=2)
        assert terminal is not None and terminal.status == "interrupted"
        await interrupt_db.commit()

        async with service_sessions() as verify:
            row = (
                await verify.execute(
                    text(
                        "SELECT status, paused_at, actual_duration FROM pomodoro_sessions WHERE id=:id"
                    ).bindparams(id=session_id)
                )
            ).mappings().one()
            open_count = await verify.scalar(
                text(
                    "SELECT COUNT(*) FROM pomodoro_pause_intervals "
                    "WHERE session_id=:id AND ended_at IS NULL"
                ).bindparams(id=session_id)
            )
            assert row["status"] == "interrupted"
            assert row["paused_at"] is None
            assert row["actual_duration"] is not None and row["actual_duration"] >= 0
            assert open_count == 0
    finally:
        await pause_db.close()
        await interrupt_db.close()
