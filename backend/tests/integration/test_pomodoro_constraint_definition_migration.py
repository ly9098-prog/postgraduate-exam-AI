from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "z0a1b2c3d4e5_verify_pomodoro_constraint_definitions.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("pomodoro_definition_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_connection(*, duplicate_active=False, duplicate_client_start=False):
    engine = sa.create_engine("sqlite:///:memory:")
    conn = engine.connect()
    # Intentionally create canonical names with wrong definitions. The migration
    # must inspect semantics rather than accepting names at face value.
    conn.execute(sa.text("""
        CREATE TABLE pomodoro_sessions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            client_start_id VARCHAR(64),
            start_time DATETIME NOT NULL,
            end_time DATETIME,
            actual_duration INTEGER,
            status VARCHAR(16) NOT NULL,
            CONSTRAINT ck_pomodoro_sessions_completed_duration
                CHECK (status != 'completed' OR actual_duration >= -1)
        )
    """))
    conn.execute(sa.text("""
        CREATE TABLE pomodoro_pause_intervals (
            id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL,
            started_at DATETIME NOT NULL,
            ended_at DATETIME,
            CONSTRAINT ck_pomodoro_pause_intervals_ended_at
                CHECK (ended_at IS NULL OR ended_at >= started_at)
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX ix_pomodoro_pause_intervals_session_started "
        "ON pomodoro_pause_intervals (session_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX ux_pomodoro_pause_intervals_one_open "
        "ON pomodoro_pause_intervals (session_id) WHERE ended_at IS NULL"
    ))
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX ux_pomodoro_sessions_one_active_per_user "
        "ON pomodoro_sessions (user_id, status) WHERE status = 'running'"
    ))
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX ux_pomodoro_sessions_user_client_start_id "
        "ON pomodoro_sessions (client_start_id) WHERE client_start_id IS NOT NULL"
    ))

    if duplicate_active:
        conn.execute(sa.text("""
            INSERT INTO pomodoro_sessions
                (id, user_id, client_start_id, start_time, status)
            VALUES
                (1, 7, 'a', '2026-01-01 10:00:00', 'running'),
                (2, 7, 'b', '2026-01-01 10:01:00', 'paused')
        """))
    elif duplicate_client_start:
        conn.execute(sa.text("DROP INDEX ux_pomodoro_sessions_user_client_start_id"))
        conn.execute(sa.text(
            "CREATE UNIQUE INDEX ux_pomodoro_sessions_user_client_start_id "
            "ON pomodoro_sessions (id) WHERE client_start_id IS NOT NULL"
        ))
        conn.execute(sa.text("""
            INSERT INTO pomodoro_sessions
                (id, user_id, client_start_id, start_time, end_time, actual_duration, status)
            VALUES
                (1, 8, 'same', '2026-01-01 10:00:00', '2026-01-01 10:01:00', 60, 'completed'),
                (2, 8, 'same', '2026-01-01 11:00:00', '2026-01-01 11:01:00', 60, 'completed')
        """))
    conn.commit()
    return engine, conn


def _run_upgrade(conn):
    migration = _load_migration()
    context = MigrationContext.configure(conn)
    migration.op = Operations(context)
    migration.upgrade()
    return migration


def _compact(value) -> str:
    return "".join(str(value).lower().replace('"', '').replace("'", '').split()).replace("(", "").replace(")", "")


def test_wrong_named_constraint_and_index_definitions_are_repaired():
    engine, conn = _make_connection()
    try:
        migration = _run_upgrade(conn)
        inspector = sa.inspect(conn)
        pause_checks = {item["name"]: item for item in inspector.get_check_constraints("pomodoro_pause_intervals")}
        session_checks = {item["name"]: item for item in inspector.get_check_constraints("pomodoro_sessions")}
        pause_indexes = {item["name"]: item for item in inspector.get_indexes("pomodoro_pause_intervals")}
        session_indexes = {item["name"]: item for item in inspector.get_indexes("pomodoro_sessions")}

        pause_sql = _compact(pause_checks[migration.CK_PAUSE_ENDED]["sqltext"])
        assert "ended_at>started_at" in pause_sql
        assert "ended_at>=started_at" not in pause_sql

        completed_sql = _compact(session_checks[migration.CK_SESSION_COMPLETED]["sqltext"])
        assert "end_time>=start_time" in completed_sql
        assert "actual_duration>=0" in completed_sql

        assert pause_indexes[migration.IX_PAUSE_SESSION_STARTED]["column_names"] == ["session_id", "started_at"]
        assert not bool(pause_indexes[migration.IX_PAUSE_SESSION_STARTED]["unique"])
        assert pause_indexes[migration.UX_ONE_OPEN]["column_names"] == ["session_id"]
        assert bool(pause_indexes[migration.UX_ONE_OPEN]["unique"])
        assert session_indexes[migration.UX_ONE_ACTIVE]["column_names"] == ["user_id"]
        assert bool(session_indexes[migration.UX_ONE_ACTIVE]["unique"])
        assert session_indexes[migration.UX_CLIENT_START]["column_names"] == ["user_id", "client_start_id"]
        assert bool(session_indexes[migration.UX_CLIENT_START]["unique"])

        # Re-running the repair logic is definition-idempotent.
        migration.upgrade()
    finally:
        conn.close()
        engine.dispose()


def test_repaired_definitions_enforce_the_canonical_invariants():
    engine, conn = _make_connection()
    try:
        _run_upgrade(conn)
        conn.execute(sa.text("""
            INSERT INTO pomodoro_sessions
                (id, user_id, client_start_id, start_time, status)
            VALUES (1, 11, 'first', '2026-01-01 10:00:00', 'running')
        """))
        conn.commit()

        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO pomodoro_sessions
                    (id, user_id, client_start_id, start_time, status)
                VALUES (2, 11, 'second', '2026-01-01 10:01:00', 'paused')
            """))
            conn.commit()
        conn.rollback()

        conn.execute(sa.text("""
            UPDATE pomodoro_sessions
            SET status='completed', end_time='2026-01-01 10:01:00', actual_duration=60
            WHERE id=1
        """))
        conn.commit()
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO pomodoro_sessions
                    (id, user_id, client_start_id, start_time, end_time, actual_duration, status)
                VALUES (3, 11, 'first', '2026-01-01 11:00:00', '2026-01-01 11:01:00', 60, 'completed')
            """))
            conn.commit()
        conn.rollback()

        conn.execute(sa.text("""
            INSERT INTO pomodoro_pause_intervals (id, session_id, started_at, ended_at)
            VALUES (1, 1, '2026-01-01 10:00:10', NULL)
        """))
        conn.commit()
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO pomodoro_pause_intervals (id, session_id, started_at, ended_at)
                VALUES (2, 1, '2026-01-01 10:00:20', NULL)
            """))
            conn.commit()
        conn.rollback()

        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO pomodoro_pause_intervals (id, session_id, started_at, ended_at)
                VALUES (3, 2, '2026-01-01 12:00:00', '2026-01-01 12:00:00')
            """))
            conn.commit()
        conn.rollback()
    finally:
        conn.close()
        engine.dispose()


def test_duplicate_active_rows_fail_before_repairing_unique_index():
    engine, conn = _make_connection(duplicate_active=True)
    try:
        with pytest.raises(RuntimeError, match="multiple active"):
            _run_upgrade(conn)
    finally:
        conn.close()
        engine.dispose()


def test_duplicate_client_start_rows_fail_before_repairing_unique_index():
    engine, conn = _make_connection(duplicate_client_start=True)
    try:
        with pytest.raises(RuntimeError, match="client_start_id"):
            _run_upgrade(conn)
    finally:
        conn.close()
        engine.dispose()
