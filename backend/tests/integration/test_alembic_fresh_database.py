"""Fresh Alembic migration test — verifies ``alembic upgrade head`` from empty DB.

Phase 8 §5-6: This test must NOT use ``Base.metadata.create_all()``.
It proves the Alembic migration chain is complete and the application
can boot against a migrated database.

Run with:
    pytest tests/integration/test_alembic_fresh_database.py --run-integration -v
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

TEST_POSTGRES_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5433/testdb",
)
# Alembic needs sync URL
TEST_POSTGRES_SYNC_URL = os.environ.get(
    "TEST_DATABASE_SYNC_URL",
    "postgresql+asyncpg://test:test@localhost:5433/testdb",
)

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# Every ORM table must be created by Alembic. PostgreSQL also owns the
# pgvector table and Alembic revision table.
import app.models  # noqa: E402,F401
from app.core.database import Base  # noqa: E402

EXPECTED_TABLES = set(Base.metadata.tables) | {"question_embeddings", "alembic_version"}

# Fencing columns that must exist on specific tables
FENCING_COLUMNS = {
    "import_pipelines": [
        "current_task_id",
        "current_owner_token",
        "execution_generation",
    ],
    "import_batch_jobs": [
        "current_task_id",
        "current_owner_token",
        "execution_generation",
    ],
    "formula_import_jobs": [
        "current_task_id",
        "current_owner_token",
        "execution_generation",
    ],
}

# Critical indexes that must exist.
# ix_users_is_banned is created by migration g7b8c9d0e1f2. ix_import_pipelines_pipeline_id
# is runtime _ensure_* DDL only, so it is not expected here.
EXPECTED_INDEXES = [
    "ix_users_openid",
    "ix_questions_question_hash",
    "ix_question_imports_question_hash",
    "ix_question_imports_duplicate_status",
    "ix_users_is_banned",
    "ix_questions_sync_uuid",
    "ix_tags_sync_uuid",
]


def _run_alembic(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    """Run alembic in the backend directory."""
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True, text=True, timeout=60,
        cwd=str(BACKEND_DIR), env=full_env,
    )


def _admin_conn_kwargs() -> dict:
    url = make_url(TEST_POSTGRES_SYNC_URL)
    return {
        "user": url.username,
        "password": url.password,
        "host": url.host,
        "port": url.port,
        "database": "postgres",
    }


async def _reset_db() -> None:
    """Drop + recreate the target test database so every run starts pristine."""
    target = make_url(TEST_POSTGRES_SYNC_URL).database
    conn = await asyncpg.connect(**_admin_conn_kwargs())
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{target}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{target}"')
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def fresh_db():
    """Module-scoped: recreate an empty DB, then alembic upgrade head."""
    _run(_reset_db())

    result = _run_alembic(["upgrade", "head"], {"DATABASE_URL": TEST_POSTGRES_SYNC_URL})
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    print("[alembic upgrade head] OK")

    yield

    _run(_reset_db())


def _pg_conn_kwargs() -> dict:
    url = make_url(TEST_POSTGRES_URL)
    return {
        "user": url.username,
        "password": url.password,
        "host": url.host,
        "port": url.port,
        "database": url.database,
    }


def _run(coro):
    return asyncio.run(coro)


async def _fetch(query: str, *args) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(**_pg_conn_kwargs())
    try:
        return await conn.fetch(query, *args)
    finally:
        await conn.close()


class TestFreshAlembicMigration:
    """Verify that alembic upgrade head produces a complete, bootable database."""

    @pytest.mark.asyncio
    async def test_alembic_heads_single(self):
        """There must be exactly one alembic head (no branch divergence)."""
        result = _run_alembic(["heads"], {"DATABASE_URL": TEST_POSTGRES_SYNC_URL})
        assert result.returncode == 0
        # "heads" prints each head revision on its own line; count non-empty lines
        heads = [h.strip() for h in result.stdout.strip().split("\n") if h.strip()]
        assert len(heads) == 1, f"Expected single alembic head, got: {heads}"

    @pytest.mark.asyncio
    async def test_alembic_current_matches_head(self, fresh_db):
        """alembic current must equal alembic head."""
        # Get head
        head_result = _run_alembic(["heads"], {"DATABASE_URL": TEST_POSTGRES_SYNC_URL})
        head = head_result.stdout.strip().split()[0]

        # Get current
        cur_result = _run_alembic(["current"], {"DATABASE_URL": TEST_POSTGRES_SYNC_URL})
        # current output format: "<rev> (head)"
        assert head in cur_result.stdout, (
            f"alembic current does not match head.\n  head: {head}\n  current: {cur_result.stdout}"
        )

    def test_all_expected_tables_exist(self, fresh_db):
        """Every expected table must exist after alembic upgrade head."""
        rows = _run(_fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ))
        existing = {row["table_name"] for row in rows}

        missing = EXPECTED_TABLES - existing
        assert not missing, f"Missing tables after alembic upgrade: {sorted(missing)}"

        # Log extra tables (not in expected set) as info
        extra = existing - EXPECTED_TABLES - {"spatial_ref_sys"}  # PostGIS built-in
        if extra:
            print(f"[info] Extra tables in database: {sorted(extra)}")

    def test_fencing_columns_exist(self, fresh_db):
        """All fencing columns must exist on their respective tables."""
        for table_name, required_columns in FENCING_COLUMNS.items():
            rows = _run(_fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=$1",
                table_name,
            ))
            existing_columns = {row["column_name"] for row in rows}
            missing = set(required_columns) - existing_columns
            assert not missing, (
                f"Table '{table_name}' missing fencing columns: {sorted(missing)}"
            )

    def test_critical_indexes_exist(self, fresh_db):
        """All critical indexes must exist."""
        rows = _run(_fetch(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname='public' AND indexname NOT LIKE 'pg%'"
        ))
        existing_indexes = {row["indexname"] for row in rows}

        missing = set(EXPECTED_INDEXES) - existing_indexes
        assert not missing, f"Missing indexes: {sorted(missing)}"

    def test_schema_contract_has_no_autogenerate_drift(self, fresh_db):
        """ORM metadata and the migrated PostgreSQL schema must agree."""
        result = _run_alembic(["check"], {"DATABASE_URL": TEST_POSTGRES_SYNC_URL})
        assert result.returncode == 0, (
            f"alembic check failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_no_exact_duplicate_indexes(self, fresh_db):
        """A unique index must not be shadowed by an identical ordinary index."""
        rows = _run(_fetch(
            """
            WITH indexes AS (
                SELECT indrelid, indkey, indclass, indcollation, indoption,
                       COALESCE(pg_get_expr(indexprs, indrelid), '') AS expressions,
                       COALESCE(pg_get_expr(indpred, indrelid), '') AS predicate
                FROM pg_index
                WHERE indisvalid
            )
            SELECT indrelid::regclass::text AS table_name
            FROM indexes
            GROUP BY indrelid, indkey, indclass, indcollation, indoption,
                     expressions, predicate
            HAVING COUNT(*) > 1
            """
        ))
        assert not rows, f"Exact duplicate index groups: {rows}"

    def test_application_boots_against_migrated_db(self, fresh_db):
        """The application's table metadata should be compatible with the migrated DB."""
        rows = _run(_fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ))
        tables = {row["table_name"] for row in rows}
        for tbl in ["users", "questions", "wrong_questions", "review_records"]:
            assert tbl in tables, f"Key table '{tbl}' not found in migrated DB"
