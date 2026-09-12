"""add merge tracking, reparse, queued_at, source_sha256 fields

Revision ID: 8cc0da3a47f1
Revises: e19d1945618f
Create Date: 2026-06-25 19:17:00.347145

P0-2: reparse tracking fields on ImportBatchJobItem
P0-5: merge tracking fields on ImportBatchJob
P0-4: source_sha256 on ImportBatchJobItem
P0-6: queued_at on ImportBatchJob
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8cc0da3a47f1"
down_revision: Union[str, Sequence[str], None] = "e19d1945618f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ImportBatchJob — P0-5 merge tracking + P0-6 queued_at
    op.add_column("import_batch_jobs", sa.Column("merge_status", sa.String(16), nullable=True))
    op.add_column("import_batch_jobs", sa.Column("merged_batch_id", sa.String(64), nullable=True))
    op.add_column("import_batch_jobs", sa.Column("merge_error", sa.Text(), nullable=True))
    op.add_column("import_batch_jobs", sa.Column("merge_started_at", sa.DateTime(), nullable=True))
    op.add_column("import_batch_jobs", sa.Column("merge_finished_at", sa.DateTime(), nullable=True))
    op.add_column("import_batch_jobs", sa.Column("queued_at", sa.DateTime(), nullable=True))

    # ImportBatchJobItem — P0-2 reparse tracking + P0-4 source_sha256
    op.add_column("import_batch_job_items", sa.Column("source_sha256", sa.String(64), nullable=True, index=True))
    op.add_column("import_batch_job_items", sa.Column("previous_review_batch_id", sa.String(64), nullable=True))
    op.add_column("import_batch_job_items", sa.Column("reparse_attempt", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("import_batch_job_items", sa.Column("reparse_started_at", sa.DateTime(), nullable=True))
    op.add_column("import_batch_job_items", sa.Column("reparse_finished_at", sa.DateTime(), nullable=True))
    op.add_column("import_batch_job_items", sa.Column("reparse_config_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    # ImportBatchJobItem rollback
    op.drop_column("import_batch_job_items", "reparse_config_hash")
    op.drop_column("import_batch_job_items", "reparse_finished_at")
    op.drop_column("import_batch_job_items", "reparse_started_at")
    op.drop_column("import_batch_job_items", "reparse_attempt")
    op.drop_column("import_batch_job_items", "previous_review_batch_id")
    op.drop_column("import_batch_job_items", "source_sha256")

    # ImportBatchJob rollback
    op.drop_column("import_batch_jobs", "queued_at")
    op.drop_column("import_batch_jobs", "merge_finished_at")
    op.drop_column("import_batch_jobs", "merge_started_at")
    op.drop_column("import_batch_jobs", "merge_error")
    op.drop_column("import_batch_jobs", "merged_batch_id")
    op.drop_column("import_batch_jobs", "merge_status")
