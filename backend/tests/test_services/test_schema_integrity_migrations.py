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
    / "v15_schema_integrity_core.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("schema_integrity_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _bind_migration(connection):
    migration = _load_migration()
    migration.op = Operations(MigrationContext.configure(connection))
    return migration


def test_duplicate_preflight_rejects_unsafe_unique_constraint():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE state (id INTEGER PRIMARY KEY, user_id INTEGER, item_id INTEGER)"
            )
        )
        connection.execute(sa.text("INSERT INTO state VALUES (1, 7, 9), (2, 7, 9)"))
        migration = _bind_migration(connection)

        with pytest.raises(RuntimeError, match="duplicate group"):
            migration._assert_no_duplicates("state", ("user_id", "item_id"))
    engine.dispose()


def test_reviewer_fk_preflight_rejects_orphan():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE admin_users (id INTEGER PRIMARY KEY)"))
        connection.execute(
            sa.text(
                "CREATE TABLE formula_graph_assets "
                "(id INTEGER PRIMARY KEY, reviewed_by INTEGER)"
            )
        )
        connection.execute(sa.text("INSERT INTO formula_graph_assets VALUES (1, 42)"))
        migration = _bind_migration(connection)

        with pytest.raises(RuntimeError, match="orphan reviewed_by"):
            migration._ensure_formula_asset_reviewer_fk()
    engine.dispose()
