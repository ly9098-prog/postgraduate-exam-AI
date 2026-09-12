"""fix missing idempotency columns on batch job tables

Migration r3c4d5e6f7g8 was supposed to add request_id/batch_import_id/
image_import_id to import_batch_job_items and next_event_seq to
import_batch_jobs, but it ran before those tables existed (merge-branch
race condition), so its _has_column/_has_table guards skipped the
additions. This migration applies the missing columns unconditionally.

Revision ID: f2e3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-27 11:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError

from alembic import op

revision: str = "f2e3a4b5c6d7"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    # --- import_batch_job_items: missing idempotency columns ---
    for col in ("request_id", "batch_import_id", "image_import_id"):
        if not _has_column("import_batch_job_items", col):
            op.add_column(
                "import_batch_job_items",
                sa.Column(col, sa.String(64), nullable=True),
            )

    # Unique constraint on (batch_import_id, image_import_id)
    try:
        op.create_unique_constraint(
            "uq_batch_import_id_image",
            "import_batch_job_items",
            ["batch_import_id", "image_import_id"],
        )
    except NotImplementedError:
        pass  # SQLite may not support named unique constraints via ALTER
    except ProgrammingError:
        pass  # PostgreSQL: constraint may already exist from init_db() repair

    # --- import_batch_jobs: missing next_event_seq ---
    if not _has_column("import_batch_jobs", "next_event_seq"):
        op.add_column(
            "import_batch_jobs",
            sa.Column("next_event_seq", sa.Integer(), nullable=False, server_default=sa.text("1")),
        )


def downgrade() -> None:
    # Drop unique constraint
    try:
        op.drop_constraint("uq_batch_import_id_image", "import_batch_job_items")
    except NotImplementedError:
        pass

    # Drop columns from import_batch_job_items
    for col in ("request_id", "batch_import_id", "image_import_id"):
        if _has_column("import_batch_job_items", col):
            op.drop_column("import_batch_job_items", col)

    # Drop next_event_seq from import_batch_jobs
    if _has_column("import_batch_jobs", "next_event_seq"):
        op.drop_column("import_batch_jobs", "next_event_seq")
