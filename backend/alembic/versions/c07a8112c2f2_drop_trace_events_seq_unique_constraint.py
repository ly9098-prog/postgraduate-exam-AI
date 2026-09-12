"""drop trace events seq unique constraint

SQLite does not support ALTER TABLE DROP CONSTRAINT, so we use
batch_alter_table which recreates the table internally.

Revision ID: c07a8112c2f2
Revises: b1b2c3d4e5f6
Create Date: 2026-06-26 14:11:43.839861

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c07a8112c2f2'
down_revision: Union[str, Sequence[str], None] = 'b1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_constraint(table_name: str, constraint_name: str) -> bool:
    """Check if a named constraint exists (SQLite + PostgreSQL compatible)."""
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "sqlite":
        row = conn.execute(
            sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),
            {"name": table_name},
        ).scalar()
        return row is not None and constraint_name in row
    # PostgreSQL
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name=:table_name AND constraint_name=:constraint_name"
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    ).scalar()
    return row is not None


def upgrade() -> None:
    """Drop the unique constraint if it exists.

    On databases where the constraint was never created (e.g. fresh DBs
    where r3c4d5e6f7g8 create_table already omitted it), this is a no-op.
    """
    if _has_constraint("batch_job_trace_events", "uq_trace_events_job_seq"):
        with op.batch_alter_table("batch_job_trace_events") as batch_op:
            batch_op.drop_constraint("uq_trace_events_job_seq", type_="unique")


def downgrade() -> None:
    """Re-create the constraint (no-op on DBs that never had it)."""
    if not _has_constraint("batch_job_trace_events", "uq_trace_events_job_seq"):
        with op.batch_alter_table("batch_job_trace_events") as batch_op:
            batch_op.create_unique_constraint(
                "uq_trace_events_job_seq", ["job_id", "seq"]
            )
