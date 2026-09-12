"""b3d4e5f6a7b8 + c4e5f6a7b8c9 question_embeddings model_id FK migration tests.

Runs against a real PostgreSQL (localhost:5433, dedicated database).  The test
DB has no pgvector, so the question_embeddings table is created with a stub
non-vector ``embedding`` column (the migrations never touch it).

Spec coverage (next_task.md §23):
  * create embedding with model_id = X, read model config via relation
  * FK failure on non-existent model_id
  * model_id NOT NULL
  * ON DELETE behavior of fk_question_embeddings_model (NO ACTION: deleting
    a model config with dependent embeddings must fail)
  * stage 2 (c4e5f6a7b8c9) drops the legacy embedding_model column only after
    model_id is fully backfilled

Run with:
    pytest tests/integration/test_migration_question_embeddings_model_fk.py --run-integration -v
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

TEST_DB = "question_embeddings_model_fk_test"

_ZERO_VEC = "[" + ",".join(["0"] * 1536) + "]"


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
    # str(make_url(...)) masks the password as ***; render it explicitly.
    url = make_url(SYNC_URL).set(database=db)
    url_str = url.render_as_string(hide_password=False)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        timeout=240,
        cwd=str(BACKEND),
        env={**os.environ, "DATABASE_URL": url_str},
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
    """Seed into the table already created by p5_3_vector_schema (the
    pgvector test image has the extension available, so the real table
    with embedding vector(1536) exists after upgrading to
    r408kpunique20260912); returns config ids."""
    zero_vec = _ZERO_VEC
    conn = await asyncpg.connect(**_conn_kwargs(TEST_DB))
    try:
        async with conn.transaction():
            await conn.execute("DELETE FROM question_embeddings")
            await conn.execute(
                "INSERT INTO users (id, openid) VALUES (1, 'qe_model_fk_test_user') "
                "ON CONFLICT (id) DO NOTHING"
            )
            # s408canonical20260907 already seeds the canonical 408 catalog
            # during upgrade; reuse its data_structure row.
            subject_id = await conn.fetchval(
                "SELECT id FROM subjects WHERE code = 'data_structure'"
            )

            for qid in (2001, 2002, 2003):
                await conn.execute(
                    "INSERT INTO questions "
                    "(id, subject_id, question_type, content, answer, difficulty, "
                    " review_status, is_active) VALUES "
                    "($1, $2, 'single_choice', $3, 'A', 1, 'new', TRUE)",
                    qid,
                    subject_id,
                    f'"q{qid}"',
                )

            # Two model configs: one that matches display_name, one that
            # matches name (tests the mapping precedence + ambiguity check).
            config_display = await conn.fetchval(
                "INSERT INTO admin_ai_model_configs "
                "(name, display_name, provider) VALUES "
                "('qwen3.7-text-embedding-flash', 'qwen3.7-text-embedding', 'dashscope') "
                "RETURNING id"
            )
            config_by_name = await conn.fetchval(
                "INSERT INTO admin_ai_model_configs "
                "(name, display_name, provider) VALUES "
                "('other-model', 'other-display', 'deepseek') RETURNING id"
            )
            await conn.execute(
                "INSERT INTO question_embeddings "
                "(id, question_id, subject_id, question_type, embedding_model, "
                " embedding_dim, content_hash, content_text, embedding) VALUES "
                "(1, 2001, $1, 'single_choice', 'qwen3.7-text-embedding', 1536, 'h', 't', $2::vector),"
                "(2, 2002, $1, 'single_choice', 'qwen3.7-text-embedding', 1536, 'h', 't', $2::vector)",
                subject_id,
                zero_vec,
            )
        return {"display": config_display, "name": config_by_name, "subject": subject_id}
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
    """Drop + create the dedicated DB, upgrade to r408kpunique20260912,
    seed, upgrade to stage 1 (b3d4e5f6a7b8) then head (c4e5f6a7b8c9)."""
    _run(_drop_database())
    _run(_create_database())

    result = _alembic(["upgrade", "r408kpunique20260912"], TEST_DB)
    assert result.returncode == 0, (
        f"upgrade to r408kpunique20260912 failed:\n{result.stdout}\n{result.stderr}"
    )

    ids = _run(_seed())

    result = _alembic(["upgrade", "b3d4e5f6a7b8"], TEST_DB)
    assert result.returncode == 0, (
        f"upgrade to b3d4e5f6a7b8 (stage 1) failed:\n{result.stdout}\n{result.stderr}"
    )

    yield ids

    _run(_drop_database())


class TestStage1ModelIdBackfill:
    def test_stage1_head_reached(self, migrated_db):
        result = _alembic(["current"], TEST_DB)
        assert "b3d4e5f6a7b8" in result.stdout

    def test_model_id_backfilled_from_display_name(self, migrated_db):
        ids = migrated_db
        got = dict(_run(_fetch_pairs(
            "SELECT id, model_id FROM question_embeddings ORDER BY id"
        )))
        assert got == {1: ids["display"], 2: ids["display"]}, got

    def test_model_id_not_null(self, migrated_db):
        nullable = _run(_fetch_scalar(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='question_embeddings' AND column_name='model_id'"
        ))
        assert nullable == "NO"

    def test_fk_exists(self, migrated_db):
        count = _run(_fetch_scalar(
            "SELECT count(*) FROM pg_constraint WHERE conname = $1 "
            "AND conrelid = 'question_embeddings'::regclass",
            "fk_question_embeddings_model",
        ))
        assert count == 1

    def test_fk_not_cascade(self, migrated_db):
        action = _run(_fetch_scalar(
            "SELECT confdeltype FROM pg_constraint WHERE conname = $1",
            "fk_question_embeddings_model",
        ))
        assert action == b"a", f"expected NO ACTION, got {action}"

    def test_unique_swapped(self, migrated_db):
        got = set(_run(_fetch_pairs(
            "SELECT conname, 1 FROM pg_constraint "
            "WHERE conrelid = 'question_embeddings'::regclass AND contype='u'"
        )))
        assert ("uq_question_embeddings_question_id_model_id", 1) in got
        assert ("question_embeddings_question_id_embedding_model_key", 1) not in got


class TestSpecRequirements:
    def test_create_with_model_id(self, migrated_db):
        ids = migrated_db
        model_id = _run(_fetch_scalar(
            "INSERT INTO question_embeddings "
            "(id, question_id, subject_id, question_type, embedding_model, "
            " model_id, embedding_dim, content_hash, content_text, embedding) "
            "VALUES (101, 2003, $1, 'single_choice', 'qwen3.7-text-embedding', "
            "$2, 1536, 'h2', 't2', $3::vector) "
            "RETURNING model_id",
            ids["subject"],
            ids["display"],
            _ZERO_VEC,
        ))
        assert model_id == ids["display"]

    def test_read_via_relation(self, migrated_db):
        row = _run(_fetch_scalar(
            "SELECT c.name FROM question_embeddings qe "
            "JOIN admin_ai_model_configs c ON c.id = qe.model_id "
            "WHERE qe.id = 1"
        ))
        assert row == "qwen3.7-text-embedding-flash"

    def test_fk_failure_on_invalid_id(self, migrated_db):
        async def _go():
            conn = await asyncpg.connect(**_conn_kwargs(TEST_DB))
            try:
                with pytest.raises(asyncpg.ForeignKeyViolationError):
                    await conn.execute(
                        "INSERT INTO question_embeddings "
                        "(id, question_id, subject_id, question_type, "
                        " embedding_model, model_id, embedding_dim, "
                        " content_hash, content_text, embedding) "
                        "VALUES (102, 2002, $1, 'single_choice', "
                        "'qwen3.7-text-embedding', 999999, 1536, 'h3', "
                        "'t3', $2::vector)",
                        migrated_db["subject"],
                        _ZERO_VEC,
                    )
            finally:
                await conn.close()

        _run(_go())

    def test_model_id_not_null_enforced(self, migrated_db):
        async def _go():
            conn = await asyncpg.connect(**_conn_kwargs(TEST_DB))
            try:
                with pytest.raises(asyncpg.NotNullViolationError):
                    await conn.execute(
                        "INSERT INTO question_embeddings "
                        "(id, question_id, subject_id, question_type, "
                        " embedding_model, model_id, embedding_dim, "
                        " content_hash, content_text, embedding) "
                        "VALUES (103, 2002, $1, 'single_choice', "
                        "'qwen3.7-text-embedding', NULL, 1536, 'h3', "
                        "'t3', $2::vector)",
                        migrated_db["subject"],
                        _ZERO_VEC,
                    )
            finally:
                await conn.close()

        _run(_go())

    def test_delete_model_config_with_embeddings_fails(self, migrated_db):
        async def _go():
            conn = await asyncpg.connect(**_conn_kwargs(TEST_DB))
            try:
                with pytest.raises(asyncpg.ForeignKeyViolationError):
                    await conn.execute(
                        "DELETE FROM admin_ai_model_configs WHERE id = $1",
                        migrated_db["display"],
                    )
            finally:
                await conn.close()

        _run(_go())

    def test_upsert_lookup_by_model_id(self, migrated_db):
        ids = migrated_db
        # dedup/upsert path: (question_id, model_id) unique — updating an
        # existing (question_id, model_id) pair must not create a new row.
        async def _go():
            conn = await asyncpg.connect(**_conn_kwargs(TEST_DB))
            try:
                async with conn.transaction():
                    await conn.execute(
                        "UPDATE question_embeddings SET content_hash = 'updated' "
                        "WHERE question_id = 2001 AND model_id = $1",
                        ids["display"],
                    )
            finally:
                await conn.close()

        _run(_go())
        count = _run(_fetch_scalar(
            "SELECT count(*) FROM question_embeddings "
            "WHERE question_id = 2001 AND model_id = $1",
            ids["display"],
        ))
        assert count == 1
        content_hash = _run(_fetch_scalar(
            "SELECT content_hash FROM question_embeddings WHERE question_id = 2001"
        ))
        assert content_hash == "updated"

    def test_search_by_model_id(self, migrated_db):
        ids = migrated_db
        count = _run(_fetch_scalar(
            "SELECT count(*) FROM question_embeddings qe "
            "WHERE qe.model_id = $1 AND qe.embedding_dim = 1536",
            ids["display"],
        ))
        assert count >= 2


class TestStage2DowngradeRoundtrip:
    def test_upgrade_to_head_drops_column(self, migrated_db):
        result = _alembic(["upgrade", "head"], TEST_DB)
        assert result.returncode == 0, (
            f"upgrade to c4e5f6a7b8c9 (stage 2) failed:\n{result.stdout}\n{result.stderr}"
        )

        count = _run(_fetch_scalar(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='question_embeddings' AND column_name='embedding_model'"
        ))
        assert count == 0, "legacy embedding_model column should have been dropped"

        total = _run(_fetch_scalar("SELECT count(*) FROM question_embeddings"))
        assert total == 3, f"row count changed during stage 2: {total}"

    def test_stage2_head_reached(self, migrated_db):
        result = _alembic(["current"], TEST_DB)
        assert "c4e5f6a7b8c9" in result.stdout

    def test_downgrade_restores_column(self, migrated_db):
        result = _alembic(["downgrade", "b3d4e5f6a7b8"], TEST_DB)
        assert result.returncode == 0, (
            f"downgrade to b3d4e5f6a7b8 failed:\n{result.stdout}\n{result.stderr}"
        )

        values = _run(_fetch_pairs(
            "SELECT id, embedding_model FROM question_embeddings ORDER BY id"
        ))
        # downgrade reconstructs via COALESCE(display_name, name), matching
        # the prod semantics where embedding_model stored the display_name.
        expected = "qwen3.7-text-embedding"
        assert values == [
            (1, expected),
            (2, expected),
            (101, expected),
        ], values

    def test_reupgrade_to_head(self, migrated_db):
        result = _alembic(["upgrade", "head"], TEST_DB)
        assert result.returncode == 0, (
            f"re-upgrade to head failed:\n{result.stdout}\n{result.stderr}"
        )
        count = _run(_fetch_scalar(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='question_embeddings' AND column_name='embedding_model'"
        ))
        assert count == 0
