"""Phase 7/8: Add error_code, fix idempotency_key uniqueness, add version to export_tasks

Changes:
1. Add ``error_code`` VARCHAR(32) column (nullable) for structured error tracking
2. Drop UNIQUE constraint on ``idempotency_key``, add plain INDEX instead
3. Add ``version`` INTEGER column (default 1) for stale-event detection

Chains from v10-to-v14 mergepoint (already applied on production).

Revision ID: phase7_export_fixes
Revises: 812ba6628ff1
Create Date: 2026-07-27
"""
from __future__ import annotations

from typing import ClassVar, Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "phase7_export_fixes"
down_revision: Union[str, Sequence[str], None] = "812ba6628ff1"
branch_labels: ClassVar[tuple[str] | None] = None
depends_on: ClassVar[tuple[str] | None] = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    return column in [c["name"] for c in sa.inspect(conn).get_columns(table)]


def _get_export_indexes():
    """Return list of index dicts for export_tasks."""
    conn = op.get_bind()
    return sa.inspect(conn).get_indexes("export_tasks")


def upgrade() -> None:
    """Upgrade: add columns, fix uniqueness."""
    conn = op.get_bind()
    is_postgresql = conn.dialect.name == "postgresql"

    # Use batch mode for SQLite compatibility (need it for index changes)
    with op.batch_alter_table("export_tasks") as batch_op:
        # 1. Add error_code column
        if not _has_column("export_tasks", "error_code"):
            batch_op.add_column(sa.Column("error_code", sa.String(32), nullable=True))

        # 2. Add version column
        if not _has_column("export_tasks", "version"):
            batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

        # 3. Fix idempotency_key uniqueness
        new_ix_name = "ix_export_tasks_idempotency_key"
        current_indexes = _get_export_indexes()

        has_unique_constraint = any(
            ix.get("column_names", ix.get("columns", [])) == ["idempotency_key"]
            and ix.get("unique")
            for ix in current_indexes
        )

        if has_unique_constraint:
            # On PostgreSQL, a UNIQUE constraint creates a backing index.
            # We must drop the CONSTRAINT (not the index) to satisfy the dependency.
            if is_postgresql:
                constraint_name = None
                for ix in current_indexes:
                    cols = ix.get("column_names", ix.get("columns", []))
                    if cols == ["idempotency_key"] and ix.get("unique"):
                        constraint_name = ix["name"]
                        break
                if constraint_name:
                    batch_op.drop_constraint(constraint_name, type_="unique")
            else:
                # SQLite — batch mode can drop the unique index directly
                old_ix_name = None
                for ix in current_indexes:
                    cols = ix.get("column_names", ix.get("columns", []))
                    if cols == ["idempotency_key"] and ix.get("unique"):
                        old_ix_name = ix["name"]
                        break
                if old_ix_name:
                    batch_op.drop_index(old_ix_name)

            batch_op.create_index(new_ix_name, ["idempotency_key"])
        elif not _has_column("export_tasks", "idempotency_key"):
            pass  # column doesn't exist — skip
        else:
            # Non-unique index already exists — ensure it has the right name
            existing = [
                ix for ix in current_indexes
                if ix.get("column_names", ix.get("columns", [])) == ["idempotency_key"]
            ]
            if not existing:
                batch_op.create_index(new_ix_name, ["idempotency_key"])


def downgrade() -> None:
    """Reverse the Phase 7/8 export fixes."""
    conn = op.get_bind()
    is_postgresql = conn.dialect.name == "postgresql"
    new_ix_name = "ix_export_tasks_idempotency_key_unique"

    with op.batch_alter_table("export_tasks") as batch_op:
        current_indexes = _get_export_indexes()

        # Drop non-unique index
        non_unique = [
            ix for ix in current_indexes
            if ix.get("column_names", ix.get("columns", [])) == ["idempotency_key"]
            and not ix.get("unique")
        ]
        for ix in non_unique:
            batch_op.drop_index(ix["name"])

        # Recreate unique constraint/index
        unique_exists = any(
            ix.get("column_names", ix.get("columns", [])) == ["idempotency_key"]
            and ix.get("unique")
            for ix in current_indexes
        )
        if not unique_exists:
            if is_postgresql:
                batch_op.create_unique_constraint(new_ix_name, ["idempotency_key"])
            else:
                batch_op.create_index(new_ix_name, ["idempotency_key"], unique=True)

    # Drop version column
    if _has_column("export_tasks", "version"):
        op.drop_column("export_tasks", "version")

    # Drop error_code column
    if _has_column("export_tasks", "error_code"):
        op.drop_column("export_tasks", "error_code")
