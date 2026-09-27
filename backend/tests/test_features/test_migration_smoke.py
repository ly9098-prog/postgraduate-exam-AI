"""Migration smoke test: verify Alembic chain works on SQLite.

This test checks the basic integrity of the migration chain:
1. Single head (no unresolved merges)
2. Fresh DB can upgrade to head
3. Downgrade one step and re-upgrade
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent  # tests/test_features
BACKEND = HERE.parent.parent  # backend


def _has_postgres() -> bool:
    """True when the active DATABASE_URL targets PostgreSQL."""
    return (os.environ.get("DATABASE_URL") or "").startswith("postgresql")


def test_alembic_single_head():
    """Migration chain must have exactly one head."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        capture_output=True, text=True, cwd=BACKEND,
        env={**__import__("os").environ, "DATABASE_URL": "sqlite+aiosqlite://"},
    )
    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    lines = [l.strip() for l in result.stdout.splitlines() if l.strip() and not l.startswith("INFO")]
    # Each head is on its own line; count non-empty, non-INFO lines → must be 1
    assert len(lines) == 1, f"Expected 1 head, got {len(lines)}:\n{lines}"


def test_alembic_upgrade_head_sqlite(tmp_path):
    """Fresh SQLite databases can traverse the complete migration chain."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": db_url},
    )
    assert result.returncode == 0, (
        f"SQLite upgrade head failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


@pytest.mark.skipif(
    not _has_postgres(),
    reason="migration chain uses Postgres-specific ALTER/FK operations, not SQLite-compatible",
)
def test_alembic_upgrade_downgrade_cycle(tmp_path):
    """Fresh Postgres DB: upgrade head → downgrade -1 → upgrade head."""
    db_url = os.environ["DATABASE_URL"]

    # Upgrade to head
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True, text=True, cwd=BACKEND,
        env={**__import__("os").environ, "DATABASE_URL": db_url},
    )
    assert result.returncode == 0, f"upgrade head failed:\n{result.stderr}"

    # Downgrade one step using a specific merge parent to avoid "Ambiguous walk"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "v10_v9_merge"],
        capture_output=True, text=True, cwd=BACKEND,
        env={**__import__("os").environ, "DATABASE_URL": db_url},
    )
    assert result.returncode == 0, f"downgrade to v10_v9_merge failed:\n{result.stderr}"

    # Re-upgrade
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True, text=True, cwd=BACKEND,
        env={**__import__("os").environ, "DATABASE_URL": db_url},
    )
    assert result.returncode == 0, f"re-upgrade head failed:\n{result.stderr}"


def test_v14_to_head_preserves_existing_schema_data(tmp_path):
    """Legacy create_all tables and v14 business rows survive schema repair."""
    import sqlite3

    db_path = tmp_path / "v14-upgrade.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    env = {**os.environ, "DATABASE_URL": db_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "v14_add_review_sessions"],
        capture_output=True,
        text=True,
        cwd=BACKEND,
        env=env,
    )
    assert result.returncode == 0, result.stderr

    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE ai_feedback_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source VARCHAR(32) NOT NULL,
                feedback_type VARCHAR(32) NOT NULL,
                question_id INTEGER,
                detail TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX ix_ai_feedback_logs_user_id ON ai_feedback_logs(user_id);
            INSERT INTO ai_feedback_logs(user_id, source, feedback_type, detail)
            VALUES (77, 'dashboard', 'incorrect', 'preserve me');

            CREATE TABLE worker_credentials (
                id VARCHAR(64) PRIMARY KEY,
                worker_id VARCHAR(64) NOT NULL,
                key_hash VARCHAR(64) NOT NULL,
                is_active BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                rotated_at DATETIME,
                expires_at DATETIME
            );
            CREATE INDEX ix_worker_credentials_worker_id
                ON worker_credentials(worker_id);

            INSERT INTO formula_graph_specs(
                id, formula_card_id, slug, source_ref, title, spec_json,
                spec_hash, schema_version, renderer_version, status, sort_order
            ) VALUES (
                991, 999, 'legacy', 'legacy-ref', 'Legacy', '{}',
                'hash', 1, 1, 'draft', 0
            );
            INSERT INTO user_knowledge_adaptive_state(
                id, user_id, knowledge_point_id, interval_factor,
                due_review_count, due_review_correct_count, overdue_wrong_count
            ) VALUES (991, 999, 999, 1.0, 0, 0, 0);
            INSERT INTO user_question_difficulty_state(
                id, user_id, question_id, personal_difficulty_score,
                difficulty_label, answer_count, correct_count, wrong_count,
                fast_correct_count, slow_correct_count, slow_wrong_count,
                overdue_wrong_count
            ) VALUES (991, 999, 999, 50, 'normal', 0, 0, 0, 0, 0, 0, 0);
            """
        )

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=BACKEND,
        env=env,
    )
    assert result.returncode == 0, result.stderr

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ai_feedback_logs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM formula_graph_specs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM user_knowledge_adaptive_state").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM user_question_difficulty_state").fetchone()[0] == 1
        assert [row[1] for row in connection.execute("PRAGMA table_info(formula_graph_specs)") if row[5]] == ["id"]
        assert any(
            row[1] == "sqlite_autoindex_user_knowledge_adaptive_state_1"
            for row in connection.execute("PRAGMA index_list(user_knowledge_adaptive_state)")
        )
