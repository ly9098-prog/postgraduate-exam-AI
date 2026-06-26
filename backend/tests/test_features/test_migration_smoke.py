"""Migration smoke test: verify Alembic chain works on SQLite.

This test checks the basic integrity of the migration chain:
1. Single head (no unresolved merges)
2. Fresh DB can upgrade to head
3. Downgrade one step and re-upgrade
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # tests/test_features
BACKEND = HERE.parent.parent  # backend


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


def test_alembic_upgrade_downgrade_cycle(tmp_path):
    """Fresh SQLite DB: upgrade head → downgrade -1 → upgrade head."""
    db_path = tmp_path / "test_migration.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    # Upgrade to head
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True, text=True, cwd=BACKEND,
        env={**__import__("os").environ, "DATABASE_URL": db_url},
    )
    assert result.returncode == 0, f"upgrade head failed:\n{result.stderr}"

    # Downgrade one step
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "-1"],
        capture_output=True, text=True, cwd=BACKEND,
        env={**__import__("os").environ, "DATABASE_URL": db_url},
    )
    assert result.returncode == 0, f"downgrade -1 failed:\n{result.stderr}"

    # Re-upgrade
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True, text=True, cwd=BACKEND,
        env={**__import__("os").environ, "DATABASE_URL": db_url},
    )
    assert result.returncode == 0, f"re-upgrade head failed:\n{result.stderr}"
