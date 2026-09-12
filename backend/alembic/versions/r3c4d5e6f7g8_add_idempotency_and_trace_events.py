"""add idempotency columns and trace_events table.

Revision ID: r3c4d5e6f7g8
Revises: cadb56b6cd95
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "r3c4d5e6f7g8"
down_revision: str | Sequence[str] | None = "cadb56b6cd95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    conn = op.get_bind()
    return conn.dialect.has_table(conn, name)


def _has_column(table: str, column: str) -> bool:
    from sqlalchemy import inspect
    conn = op.get_bind()
    if not conn.dialect.has_table(conn, table):
        return False
    inspector = inspect(conn)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def _has_index(table: str, index: str) -> bool:
    from sqlalchemy import inspect
    conn = op.get_bind()
    if not conn.dialect.has_table(conn, table):
        return False
    inspector = inspect(conn)
    indexes = [i["name"] for i in inspector.get_indexes(table)]
    return index in indexes


def upgrade() -> None:
    # --- ImportBatchJob: next_event_seq counter ---
    if _has_table("import_batch_jobs") and not _has_column("import_batch_jobs", "next_event_seq"):
        op.add_column(
            "import_batch_jobs",
            sa.Column("next_event_seq", sa.Integer(), nullable=False, server_default=sa.text("1")),
        )

    # --- ImportBatchJobItem: idempotency columns ---
    if _has_table("import_batch_job_items"):
        for col in ("batch_import_id", "image_import_id", "request_id"):
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

    # --- BatchJobTraceEvent table ---
    if not _has_table("batch_job_trace_events"):
        op.create_table(
            "batch_job_trace_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("job_id", sa.String(64), nullable=False),
            sa.Column("item_seq", sa.Integer(), nullable=True),
            sa.Column("request_id", sa.String(64), nullable=True),
            sa.Column("image_import_id", sa.String(64), nullable=True),
            sa.Column("batch_import_id", sa.String(64), nullable=True),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("step", sa.String(32), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("message", sa.String(512), nullable=False, server_default=""),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            # FK to import_batch_jobs deferred — that table lives on branch q1b2c3d4e5f6
            # and may not exist yet. FK is added in migration f9e0d1c2b3a4 after the merge.
            sa.PrimaryKeyConstraint("id"),
        )

    # Indexes
    if not _has_index("batch_job_trace_events", "ix_batch_job_trace_events_job_id"):
        op.create_index(
            "ix_batch_job_trace_events_job_id",
            "batch_job_trace_events",
            ["job_id"],
        )


def downgrade() -> None:
    # Drop trace events table
    op.drop_table("batch_job_trace_events")

    # Drop unique constraint
    try:
        op.drop_constraint("uq_batch_import_id_image", "import_batch_job_items")
    except NotImplementedError:
        pass

    # Drop idempotency columns
    for col in ("request_id", "image_import_id", "batch_import_id"):
        if _has_column("import_batch_job_items", col):
            op.drop_column("import_batch_job_items", col)

    # Drop next_event_seq
    if _has_column("import_batch_jobs", "next_event_seq"):
        op.drop_column("import_batch_jobs", "next_event_seq")
