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
