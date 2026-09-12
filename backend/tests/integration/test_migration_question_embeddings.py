"""b2c3d4e5f6a7 question_embeddings subject→subject_id migration test on real PostgreSQL.

The local test PostgreSQL (localhost:5433) has no pgvector extension, so the
p5_3_vector_schema migration that creates question_embeddings is a no-op there.
This test therefore builds the pre-migration table shape directly — production
shaped, with a non-vector stub ``embedding`` column (the migration never touches
the embedding column, so the stub is sufficient) — then seeds data and upgrades
to head (b2c3d4e5f6a7).

Verified after migration:
  * subject_id backfilled from questions.subject_id (relation) with legacy
    alias fallback (exam408 -> computer, exam408-os -> os)
  * legacy ``subject`` column dropped
  * subject_id NOT NULL + fk_question_embeddings_subject_id
  * ix_question_embeddings_subject_id created, ix_question_embeddings_subject gone

Run with:
    pytest tests/integration/test_migration_question_embeddings.py --run-integration -v
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

TEST_DB = "question_embeddings_migration_test"


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
        env={**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)},
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
    """Create the pre-migration table shape and seed; returns {code: subject_id}.

    p5_5_1 seeds subjects with the legacy taxonomy (math2/exam408-ds/pol); the
    migration resolves against the current taxonomy, so this replaces subjects
    with the current taxonomy first (matching the production state).
    """
    conn = await asyncpg.connect(**_conn_kwargs(TEST_DB))
    try:
        async with conn.transaction():
            await conn.execute(
                "CREATE TABLE question_embeddings ("
                "  id BIGSERIAL PRIMARY KEY,"
                "  question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,"
                "  subject VARCHAR(32) NOT NULL,"
                "  question_type VARCHAR(32) NOT NULL,"
                "  embedding_model VARCHAR(128) NOT NULL,"
                "  embedding_dim INTEGER NOT NULL,"
                "  content_hash VARCHAR(64) NOT NULL,"
                "  content_text TEXT NOT NULL,"
                "  embedding DOUBLE PRECISION NOT NULL,"
                "  created_at TIMESTAMP NOT NULL DEFAULT NOW(),"
                "  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),"
                "  embedded_at TIMESTAMP NOT NULL DEFAULT NOW(),"
                "  UNIQUE(question_id, embedding_model)"
                ")"
            )
            await conn.execute(
                "CREATE INDEX ix_question_embeddings_subject ON question_embeddings(subject)"
            )
            await conn.execute(
                "CREATE INDEX ix_question_embeddings_question_id ON question_embeddings(question_id)"
            )

            await conn.execute("DELETE FROM subjects")
            await conn.execute(
                "INSERT INTO users (id, openid) VALUES (1, 'qe_migration_test_user')"
            )
            ids: dict[str, int] = {}
            for code, name in (
                ("math", "数学"),
                ("ds", "数据结构"),
                ("co", "计算机组成原理"),
                ("os", "操作系统"),
                ("computer", "计算机"),
            ):
                ids[code] = await conn.fetchval(
                    "INSERT INTO subjects (code, name, path) VALUES ($1, $2, $3) "
                    "RETURNING id",
                    code,
                    name,
                    f"/{code}",
                )

            # questions: subject_id set so relation-derived backfill applies.
            for i, (qid, code) in enumerate(
                (
                    (1001, "ds"),
                    (1002, "os"),
                    (1003, "co"),
                    (1004, "computer"),
                    (1005, "computer"),
                    (1006, "os"),
                ),
                start=1,
            ):
                await conn.execute(
                    "INSERT INTO questions "
                    "(id, subject_id, question_type, content, answer, difficulty, "
                    " review_status, is_active) VALUES "
                    "($1, $2, 'single_choice', $3, 'A', 1, 'new', TRUE)",
                    qid,
                    ids[code],
                    f'"q{i}"',
                )

            # Embeddings: exact-code rows plus legacy-alias rows (exam408/exam408-os).
            # Each row gets its own question so UNIQUE(question_id, embedding_model) holds.
            emb_rows = [
                (1, 1001, "ds"),
                (2, 1002, "os"),
                (3, 1003, "co"),
                (4, 1004, "computer"),
                (5, 1005, "exam408"),     # alias -> computer
                (6, 1006, "exam408-os"),  # alias -> os
            ]
            for eid, qid, subj in emb_rows:
                await conn.execute(
                    "INSERT INTO question_embeddings "
                    "(id, question_id, subject, question_type, embedding_model, "
                    " embedding_dim, content_hash, content_text, embedding) VALUES "
                    "($1, $2, $3, 'single_choice', 'test-model', 32, 'h', 't', 0.0)",
                    eid,
                    qid,
                    subj,
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


async def _fetch_column(query: str, *args) -> list[object]:
    conn = await asyncpg.connect(**_conn_kwargs(TEST_DB))
    try:
        rows = await conn.fetch(query, *args)
        return [r[0] for r in rows]
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def migrated_db():
    """Drop + create the dedicated DB, upgrade to a7b8c9d0e1f2, seed, upgrade to head."""
    _run(_drop_database())
    _run(_create_database())

    result = _alembic(["upgrade", "a7b8c9d0e1f2"], TEST_DB)
    assert result.returncode == 0, (
        f"upgrade to a7b8c9d0e1f2 failed:\n{result.stdout}\n{result.stderr}"
    )

    ids = _run(_seed())

    result = _alembic(["upgrade", "b2c3d4e5f6a7"], TEST_DB)
    assert result.returncode == 0, (
        f"upgrade to b2c3d4e5f6a7 failed:\n{result.stdout}\n{result.stderr}"
    )

    yield ids

    _run(_drop_database())


class TestQuestionEmbeddingsSubjectIdMigration:
    def test_head_reached(self, migrated_db):
        result = _alembic(["current"], TEST_DB)
        assert "b2c3d4e5f6a7" in result.stdout

    def test_subject_id_backfilled(self, migrated_db):
        ids = migrated_db
        expected = {
            1: ids["ds"],
            2: ids["os"],
            3: ids["co"],
            4: ids["computer"],
            5: ids["computer"],  # exam408 alias -> computer
            6: ids["os"],        # exam408-os alias -> os
        }
        got = dict(_run(_fetch_pairs(
            "SELECT id, subject_id FROM question_embeddings ORDER BY id"
        )))
        assert got == expected, f"question_embeddings subject_id mismatch: {got}"

    def test_subject_column_dropped(self, migrated_db):
        count = _run(_fetch_scalar(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='question_embeddings' AND column_name='subject'"
        ))
        assert count == 0, "legacy subject column should have been dropped"
        count = _run(_fetch_scalar(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='question_embeddings' AND column_name='subject_id'"
        ))
        assert count == 1, "subject_id column missing"

    def test_subject_id_not_null(self, migrated_db):
        result = _run(_fetch_scalar(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='question_embeddings' AND column_name='subject_id'",
        ))
        assert result == "NO"

    def test_fk_exists_once(self, migrated_db):
        count = _run(_fetch_scalar(
            "SELECT count(*) FROM pg_constraint WHERE conname = $1 "
            "AND conrelid = 'question_embeddings'::regclass",
            "fk_question_embeddings_subject_id",
        ))
        assert count == 1, "fk_question_embeddings_subject_id must exist exactly once"

    def test_subject_id_index_replaces_subject_index(self, migrated_db):
        indexes = set(_run(_fetch_column(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname='public' AND tablename='question_embeddings'"
        )))
        assert "ix_question_embeddings_subject_id" in indexes, "subject_id index missing"
        assert "ix_question_embeddings_subject" not in indexes, "legacy subject index should be gone"
