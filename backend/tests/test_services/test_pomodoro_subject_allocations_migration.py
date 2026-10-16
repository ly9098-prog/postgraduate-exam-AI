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
    / "v19_pomodoro_subject_allocations.py"
)


def _run_migration(connection):
    spec = importlib.util.spec_from_file_location(
        "pomodoro_subject_allocations_migration", MIGRATION_PATH
    )
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()


def test_allocation_migration_preserves_sessions_and_enforces_unique_subject_rows():
    engine = sa.create_engine("sqlite:///:memory:")
    @sa.event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE subjects (id INTEGER PRIMARY KEY)"))
            connection.execute(
                sa.text("CREATE TABLE pomodoro_sessions (id INTEGER PRIMARY KEY)")
            )
            connection.execute(sa.text("INSERT INTO subjects VALUES (1)"))
            connection.execute(sa.text("INSERT INTO pomodoro_sessions VALUES (7)"))

            _run_migration(connection)

            assert connection.execute(
                sa.text("SELECT id FROM pomodoro_sessions")
            ).scalar_one() == 7
            connection.execute(
                sa.text(
                    "INSERT INTO pomodoro_subject_allocations "
                    "(session_id, subject_id, weight_basis_points, "
                    "subject_code_snapshot, subject_name_snapshot) "
                    "VALUES (7, 1, 10000, 'english', '英语')"
                )
            )
            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(
                    sa.text(
                        "INSERT INTO pomodoro_subject_allocations "
                        "(session_id, subject_id, weight_basis_points, "
                        "subject_code_snapshot, subject_name_snapshot) "
                        "VALUES (7, 1, 10000, 'english', '英语')"
                    )
                )
            connection.execute(sa.text("DELETE FROM subjects WHERE id = 1"))
            row = connection.execute(
                sa.text(
                    "SELECT subject_id, subject_code_snapshot, subject_name_snapshot "
                    "FROM pomodoro_subject_allocations WHERE session_id = 7"
                )
            ).one()
            assert row == (None, "english", "英语")
    finally:
        engine.dispose()
