from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "y9z0a1b2c3d4_repair_pomodoro_constraints.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("pomodoro_corrective_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_connection(*, invalid_completed=False, duplicate_open=False):
    engine = sa.create_engine("sqlite:///:memory:")
    conn = engine.connect()
    conn.execute(sa.text("""
        CREATE TABLE pomodoro_sessions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            client_start_id VARCHAR(64),
            start_time DATETIME NOT NULL,
            end_time DATETIME,
            actual_duration INTEGER,
            status VARCHAR(16) NOT NULL
        )
    """))
    conn.execute(sa.text("""
        CREATE TABLE pomodoro_pause_intervals (
            id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL,
            started_at DATETIME NOT NULL,
            ended_at DATETIME,
            CONSTRAINT ck_pomodoro_pause_intervals_ended_at
                CHECK (ended_at IS NULL OR ended_at > started_at)
        )
    """))
    if invalid_completed:
        conn.execute(sa.text("""
            INSERT INTO pomodoro_sessions
                (id, user_id, client_start_id, start_time, end_time, actual_duration, status)
            VALUES (1, 1, NULL, '2026-01-01 10:00:00', '2026-01-01 09:59:00', -1, 'completed')
        """))
    if duplicate_open:
        conn.execute(sa.text("""
            INSERT INTO pomodoro_sessions
                (id, user_id, client_start_id, start_time, end_time, actual_duration, status)
            VALUES (1, 1, NULL, '2026-01-01 10:00:00', NULL, NULL, 'paused')
        """))
        conn.execute(sa.text("""
            INSERT INTO pomodoro_pause_intervals (id, session_id, started_at, ended_at)
            VALUES
                (1, 1, '2026-01-01 10:01:00', NULL),
                (2, 1, '2026-01-01 10:02:00', NULL)
        """))
    conn.commit()
    return engine, conn


def _run_upgrade(conn):
    migration = _load_migration()
    context = MigrationContext.configure(conn)
    migration.op = Operations(context)
    migration.upgrade()
    return migration


def test_partial_prior_apply_is_repaired_independently():
    engine, conn = _make_connection()
    try:
        migration = _run_upgrade(conn)
        inspector = sa.inspect(conn)
        pause_checks = {item["name"] for item in inspector.get_check_constraints("pomodoro_pause_intervals")}
        pause_indexes = {item["name"] for item in inspector.get_indexes("pomodoro_pause_intervals")}
        session_checks = {item["name"] for item in inspector.get_check_constraints("pomodoro_sessions")}
        session_indexes = {item["name"] for item in inspector.get_indexes("pomodoro_sessions")}

        assert migration.CK_PAUSE_ENDED in pause_checks
        assert migration.IX_PAUSE_SESSION_STARTED in pause_indexes
        assert migration.UX_ONE_OPEN in pause_indexes
        assert migration.CK_SESSION_COMPLETED in session_checks
        assert migration.UX_ONE_ACTIVE in session_indexes
        assert migration.UX_CLIENT_START in session_indexes

        # Idempotency: re-running the same corrective logic must be a no-op.
        migration.upgrade()
    finally:
        conn.close()
        engine.dispose()


def test_invalid_completed_data_fails_instead_of_silently_skipping_constraint():
    engine, conn = _make_connection(invalid_completed=True)
    try:
        with pytest.raises(RuntimeError, match="completed"):
            _run_upgrade(conn)
    finally:
        conn.close()
        engine.dispose()


def test_duplicate_open_pause_data_fails_before_unique_index_creation():
    engine, conn = _make_connection(duplicate_open=True)
    try:
        with pytest.raises(RuntimeError, match="open pause"):
            _run_upgrade(conn)
    finally:
        conn.close()
        engine.dispose()


def test_enforced_constraints_reject_conflicting_rows_at_database_level():
    engine, conn = _make_connection()
    try:
        _run_upgrade(conn)
        conn.execute(sa.text("""
            INSERT INTO pomodoro_sessions
                (id, user_id, client_start_id, start_time, end_time, actual_duration, status)
            VALUES (1, 7, 'start-a', '2026-01-01 10:00:00', NULL, NULL, 'running')
        """))
        conn.commit()

        # A user cannot own two active rows, even if they came from two devices.
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO pomodoro_sessions
                    (id, user_id, client_start_id, start_time, end_time, actual_duration, status)
                VALUES (2, 7, 'start-b', '2026-01-01 10:01:00', NULL, NULL, 'paused')
            """))
            conn.commit()
        conn.rollback()

        # client_start_id is scoped per user: another user may reuse the same text.
        conn.execute(sa.text("""
            INSERT INTO pomodoro_sessions
                (id, user_id, client_start_id, start_time, end_time, actual_duration, status)
            VALUES (2, 8, 'start-a', '2026-01-01 10:02:00',
                    '2026-01-01 10:03:00', 60, 'completed')
        """))
        conn.commit()

        # The same user cannot reuse the same idempotency key, even on a terminal row.
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO pomodoro_sessions
                    (id, user_id, client_start_id, start_time, end_time, actual_duration, status)
                VALUES (3, 7, 'start-a', '2026-01-01 11:00:00',
                        '2026-01-01 11:01:00', 60, 'completed')
            """))
            conn.commit()
        conn.rollback()

        conn.execute(sa.text("""
            INSERT INTO pomodoro_pause_intervals (id, session_id, started_at, ended_at)
            VALUES (1, 1, '2026-01-01 10:05:00', NULL)
        """))
        conn.commit()
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO pomodoro_pause_intervals (id, session_id, started_at, ended_at)
                VALUES (2, 1, '2026-01-01 10:06:00', NULL)
            """))
            conn.commit()
        conn.rollback()

        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO pomodoro_sessions
                    (id, user_id, client_start_id, start_time, end_time, actual_duration, status)
                VALUES (4, 9, NULL, '2026-01-01 12:00:00',
                        '2026-01-01 11:59:00', -1, 'completed')
            """))
            conn.commit()
        conn.rollback()
    finally:
        conn.close()
        engine.dispose()
