"""Add FK constraint batch_job_trace_events.job_id → import_batch_jobs.job_id.

This FK was deferred from migration r3c4d5e6f7g8 because import_batch_jobs
lives on a parallel branch (q1b2c3d4e5f6) that may not have been merged yet.
Now that both branches are merged (via e19d1945618f), we can safely add the FK.

Revision ID: f9e0d1c2b3a4
Revises: 812ba6628ff1
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op


revision: str = "f9e0d1c2b3a4"
down_revision: str | Sequence[str] | None = "812ba6628ff1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk_exists(table: str, fk_name: str) -> bool:
    """Check if a foreign key constraint already exists."""
    conn = op.get_bind()
    from sqlalchemy import inspect

    inspector = inspect(conn)
    for fk in inspector.get_foreign_keys(table):
        if fk.get("name") == fk_name:
            return True
    return False


def upgrade() -> None:
    conn = op.get_bind()

    # Guard: both tables must exist
    if not conn.dialect.has_table(conn, "import_batch_jobs"):
        return
    if not conn.dialect.has_table(conn, "batch_job_trace_events"):
        return

    # Guard: FK may already exist (production DB had it from original r3c4d5e6f7g8)
    if _fk_exists("batch_job_trace_events", "batch_job_trace_events_job_id_fkey"):
        return

    op.create_foreign_key(
        "batch_job_trace_events_job_id_fkey",
        "batch_job_trace_events",
        "import_batch_jobs",
        ["job_id"],
        ["job_id"],
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not conn.dialect.has_table(conn, "batch_job_trace_events"):
        return
    if not _fk_exists("batch_job_trace_events", "batch_job_trace_events_job_id_fkey"):
        return
    op.drop_constraint(
        "batch_job_trace_events_job_id_fkey",
        "batch_job_trace_events",
        type_="foreignkey",
    )
