"""a7b8c9d0e1f2 subject→subject_id migration test on real PostgreSQL.

Covers the production-specific behavior that SQLite cannot reproduce: the
subject FKs on ``questions`` / ``question_imports`` / ``pomodoro_sessions``
already exist at ``c9d8e7f6a5b4`` (created by ``p5_4`` / ``r3g4h5i6j7k8``).
``a7b8c9d0e1f2`` must skip re-creating them — Postgres rejects duplicate
constraint names — while still backfilling ``subject_id`` on the 9 business
tables, dropping the legacy ``subject`` columns, and enforcing NOT NULL on
``questions.subject_id``.

Run with:
    pytest tests/integration/test_migration_subject_id.py --run-integration -v

Requires a PostgreSQL reachable via TEST_DATABASE_URL / TEST_DATABASE_SYNC_URL
(default localhost:5433 test:test). Uses a dedicated ``subject_migration_test``
database and never touches other databases.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parent.parent.parent

TEST_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5433/testdb",
)
SYNC_URL = os.environ.get(
    "TEST_DATABASE_SYNC_URL",
    "postgresql+asyncpg://test:test@localhost:5433/testdb",
)

TEST_DB = "subject_migration_test"

# The 9 business tables migrated from a legacy string `subject` column.
LEGACY_TABLES = [
    "answer_behaviors",
    "practice_records",
    "review_schedules",
    "knowledge_points",
    "knowledge_edges",
    "recommendation_logs",
    "recommendation_metrics_daily",
    "tags",
    "user_knowledge_states",
]

# FKs that already exist at c9d8e7f6a5b4 and must NOT be duplicated by a7b8c9d0e1f2.
PRE_EXISTING_FKS = {
    "questions": ("fk_questions_subject_id", "NO ACTION"),
    "question_imports": ("fk_question_imports_subject_id", "SET NULL"),
    "pomodoro_sessions": ("fk_pomodoro_sessions_subject_id", "SET NULL"),
}


def _conn_kwargs(db: str) -> dict:
    url = make_url(TEST_URL)
    return {
        "user": url.username,
        "password": url.password,
        "host": url.host,
        "port": url.port,
        "database": db,
    }


def _alembic(args: list[str], db: str) -> subprocess.CompletedProcess:
    url = make_url(SYNC_URL).set(database=db)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        timeout=240,
        cwd=str(BACKEND),
        env={**os.environ, "DATABASE_URL": str(url)},
    )


def _run(coro):
    return asyncio.run(coro)


async def _drop_database() -> None:
    conn = await asyncpg.connect(**_conn_kwargs("postgres"))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    finally:
        await conn.close()


async def _create_database() -> None:
    conn = await asyncpg.connect(**_conn_kwargs("postgres"))
    try:
        await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()


async def _seed() -> dict[str, int]:
    """Insert pre-migration data; returns {code: subject_id} for verification.

    p5_5_1 seeds subjects with the legacy taxonomy (math2/exam408-ds/pol).  On
    production the subjects table was later re-seeded with the current taxonomy
    (math/ds/os/...) by sync tooling, and that is the state a7b8c9d0e1f2 runs
    against — so the test replaces subjects with the current taxonomy first.
    """
    conn = await asyncpg.connect(**_conn_kwargs(TEST_DB))
    try:
        async with conn.transaction():
            await conn.execute("DELETE FROM subjects")
            await conn.execute(
                "INSERT INTO users (id, openid) VALUES (1, 'subject_migration_test_user')"
            )
            ids: dict[str, int] = {}
            for code, name in (("math", "数学"), ("ds", "数据结构"), ("os", "操作系统")):
                ids[code] = await conn.fetchval(
                    "INSERT INTO subjects (code, name, path) VALUES ($1, $2, $3) "
                    "RETURNING id",
                    code,
                    name,
                    f"/{code}",
                )

            # questions: subject_id is set so relation-derived backfill works.
            for i, (qid, code) in enumerate(((1001, "math"), (1002, "ds"), (1003, "os")), start=1):
                await conn.execute(
                    "INSERT INTO questions "
                    "(id, subject_id, question_type, content, answer, difficulty, "
                    " review_status, is_active) VALUES "
                    "($1, $2, 'single_choice', $3, 'A', 1, 'new', TRUE)",
                    qid,
                    ids[code],
                    f'"q{i}"',  # content is a JSON column
                )

            # practice_records — covers relation-derived, alias-derived, and
            # the agreement path. (The empty-subject + deleted-question → os
            # fallback is covered by the SQLite migration verification; the
            # question FK here makes an orphaned reference unseeddable.)
            await conn.execute(
                "INSERT INTO practice_records "
                "(id, user_id, question_id, subject) VALUES "
                "(1, 1, 1001, ''), "      # relation → math
                "(2, 1, 1002, 'ds'), "    # alias+relation agree → ds
                "(3, 1, 1002, 'exam408-ds'), "
                "(4, 1, NULL, 'os')",     # alias only → os
            )

            # answer_behaviors — nullable subject_id, keeps NULL if unresolved.
            await conn.execute(
                "INSERT INTO answer_behaviors "
                "(id, user_id, question_id, time_spent_sec, view_answer_count, "
                " switch_count, is_abandoned, session_type, subject) VALUES "
                "(1, 1, 1001, 10, 0, 0, FALSE, 'practice', ''), "
                "(2, 1, 1002, 10, 0, 0, FALSE, 'practice', 'ds')",
            )

            # review_schedules — one with NULL subject (relation-derived).
            await conn.execute(
                "INSERT INTO review_schedules "
                "(id, user_id, question_id, interval, ease_factor, repetitions, subject) VALUES "
                "(1, 1, 1002, 1, 2.5, 0, 'ds'), "
                "(2, 1, 1002, 1, 2.5, 0, NULL)",
            )
        return ids
    finally:
        await conn.close()


async def _fetch_scalar(query: str, *args) -> object:
    conn = await asyncpg.connect(**_conn_kwargs(TEST_DB))
    try:
        return await conn.fetchval(query, *args)
    finally:
        await conn.close()


async def _fetch_pairs(query: str, *args) -> list[tuple]:
    conn = await asyncpg.connect(**_conn_kwargs(TEST_DB))
    try:
        rows = await conn.fetch(query, *args)
        return [(r[0], r[1]) for r in rows]
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def migrated_db():
    """Drop + create the dedicated DB, upgrade to c9d8e7f6a5b4, seed, upgrade to head."""
    _run(_drop_database())
    _run(_create_database())

    result = _alembic(["upgrade", "c9d8e7f6a5b4"], TEST_DB)
    assert result.returncode == 0, (
        f"upgrade to c9d8e7f6a5b4 failed:\n{result.stdout}\n{result.stderr}"
    )

    ids = _run(_seed())

    result = _alembic(["upgrade", "head"], TEST_DB)
    assert result.returncode == 0, (
        f"upgrade to head (a7b8c9d0e1f2) failed:\n{result.stdout}\n{result.stderr}"
    )

    yield ids

    _run(_drop_database())


class TestSubjectIdMigration:
    def test_head_reached(self, migrated_db):
        result = _alembic(["current"], TEST_DB)
        assert "b2c3d4e5f6a7" in result.stdout

    def test_pre_existing_fks_not_duplicated(self, migrated_db):
        for table, (fk_name, _delete) in PRE_EXISTING_FKS.items():
            count = _run(_fetch_scalar(
                "SELECT count(*) FROM pg_constraint WHERE conname = $1 AND conrelid = $2::regclass",
                fk_name,
                table,
            ))
            assert count == 1, f"{table}.{fk_name} must exist exactly once, got {count}"

    def test_legacy_subject_columns_dropped(self, migrated_db):
        for table in LEGACY_TABLES:
            count = _run(_fetch_scalar(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = $1 AND column_name = 'subject'",
                table,
            ))
            assert count == 0, f"{table}.subject should have been dropped"

        # subject_id now present on every legacy table
        for table in LEGACY_TABLES:
            count = _run(_fetch_scalar(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = $1 AND column_name = 'subject_id'",
                table,
            ))
            assert count == 1, f"{table}.subject_id missing"

    def test_practice_records_backfilled(self, migrated_db):
        ids = migrated_db
        expected = {
            1: ids["math"],
            2: ids["ds"],
            3: ids["ds"],
            4: ids["os"],
        }
        got = dict(_run(_fetch_pairs(
            "SELECT id, subject_id FROM practice_records ORDER BY id"
        )))
        assert got == expected, f"practice_records subject_id mismatch: {got}"

    def test_questions_subject_id_not_null(self, migrated_db):
        result = _run(_fetch_scalar(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'questions' AND column_name = 'subject_id'",
        ))
        assert result == "NO"
