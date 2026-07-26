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

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration

TEST_POSTGRES_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5433/testdb",
)
# Alembic needs sync URL
TEST_POSTGRES_SYNC_URL = os.environ.get(
    "TEST_DATABASE_SYNC_URL",
    "postgresql+psycopg2://test:test@localhost:5433/testdb",
)

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# Tables expected after alembic upgrade head
EXPECTED_TABLES = {
    # Core
    "users",
    "questions",
    "tags",
    "question_tags",
    "review_records",
    "wrong_questions",
    "practice_sessions",
    "practice_session_items",
    # Import
    "question_imports",
    "import_pipelines",
    "import_pipeline_pages",
    "import_pipeline_chunks",
    "import_batch_jobs",
    "import_batch_job_items",
    # Admin
    "admins",
    "admin_sessions",
    "audit_logs",
    "question_versions",
    "app_user_admin_bindings",
    "admin_vector_configs",
    # Auth
    "refresh_tokens",
    # Export
    "export_tasks",
    "export_task_files",
    # Knowledge
    "knowledge_points",
    "knowledge_edges",
    "question_knowledge_points",
    "user_knowledge_states",
    # Formulas
    "formula_categories",
    "formula_tags",
    "formula_cards",
    "formula_card_tags",
    "formula_card_versions",
    "formula_graph_specs",
    "formula_graph_assets",
    "formula_graph_previews",
    "formula_import_jobs",
    "formula_import_items",
    "user_formula_favorites",
    # Recommendations
    "recommendation_experiments",
    "recommendation_experiment_assignments",
    "recommendation_logs",
    "recommendation_metrics_dailies",
    "recommendation_strategy_configs",
    # Feedback / AI
    "ai_feedback_logs",
    # Pomodoro
    "pomodoro_sessions",
    # Alembic
    "alembic_version",
}

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

# Critical indexes that must exist
EXPECTED_INDEXES = [
    "ix_users_openid",
    "ix_questions_question_hash",
    "ix_question_imports_question_hash",
    "ix_question_imports_duplicate_status",
    "ix_import_pipelines_pipeline_id",
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


def _clean_db():
    """Drop all tables in the test database to start completely fresh."""
    result = _run_alembic(["downgrade", "base"], {"DATABASE_URL": TEST_POSTGRES_SYNC_URL})
    # downgrade may fail if already at base — that's fine
    return result


@pytest.fixture(scope="module")
def fresh_db_engine():
    """Module-scoped: downgrade to base, then upgrade head, verify, yield engine."""
    # 1. Downgrade to empty
    result = _run_alembic(["downgrade", "base"], {"DATABASE_URL": TEST_POSTGRES_SYNC_URL})
    # It's OK if this fails — means we're already at base or tables don't exist
    print(f"[alembic downgrade base] rc={result.returncode} stderr={result.stderr[:200]}")

    # 2. Upgrade head
    result = _run_alembic(["upgrade", "head"], {"DATABASE_URL": TEST_POSTGRES_SYNC_URL})
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    print(f"[alembic upgrade head] OK")

    # Create engine for verification
    engine = create_async_engine(TEST_POSTGRES_URL, echo=False)
    yield engine

    # Cleanup: downgrade to base
    _run_alembic(["downgrade", "base"], {"DATABASE_URL": TEST_POSTGRES_SYNC_URL})


@pytest.fixture
def pg_session(fresh_db_engine):
    """Session factory against the fresh-migrated DB."""
    return async_sessionmaker(fresh_db_engine, class_=AsyncSession, expire_on_commit=False)


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
    async def test_alembic_current_matches_head(self, fresh_db_engine):
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

    @pytest.mark.asyncio
    async def test_all_expected_tables_exist(self, fresh_db_engine):
        """Every expected table must exist after alembic upgrade head."""
        async with fresh_db_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
            )
            existing = {row[0] for row in await result.fetchall()}

        missing = EXPECTED_TABLES - existing
        assert not missing, f"Missing tables after alembic upgrade: {sorted(missing)}"

        # Log extra tables (not in expected set) as info
        extra = existing - EXPECTED_TABLES - {"spatial_ref_sys"}  # PostGIS built-in
        if extra:
            print(f"[info] Extra tables in database: {sorted(extra)}")

    @pytest.mark.asyncio
    async def test_fencing_columns_exist(self, fresh_db_engine):
        """All fencing columns must exist on their respective tables."""
        async with fresh_db_engine.connect() as conn:
            for table_name, required_columns in FENCING_COLUMNS.items():
                result = await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name=:tbl"
                    ),
                    {"tbl": table_name},
                )
                existing_columns = {row[0] for row in await result.fetchall()}
                missing = set(required_columns) - existing_columns
                assert not missing, (
                    f"Table '{table_name}' missing fencing columns: {sorted(missing)}"
                )

    @pytest.mark.asyncio
    async def test_critical_indexes_exist(self, fresh_db_engine):
        """All critical indexes must exist."""
        async with fresh_db_engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname='public' AND indexname NOT LIKE 'pg%'"
                )
            )
            existing_indexes = {row[0] for row in await result.fetchall()}

        missing = set(EXPECTED_INDEXES) - existing_indexes
        assert not missing, f"Missing indexes: {sorted(missing)}"

    @pytest.mark.asyncio
    async def test_application_boots_against_migrated_db(self, fresh_db_engine):
        """The application's table metadata should be compatible with the migrated DB.

        We verify by checking that the ORM can reflect key tables without error.
        """
        def _verify(sync_conn):
            inspector = inspect(sync_conn)
            tables = inspector.get_table_names()
            # Key tables that must be reflectable
            for tbl in ["users", "questions", "wrong_questions", "review_records"]:
                assert tbl in tables, f"Key table '{tbl}' not found in migrated DB"
            return True

        async with fresh_db_engine.connect() as conn:
            result = await conn.run_sync(_verify)
            assert result is True
