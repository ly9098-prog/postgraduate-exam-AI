"""add import batch job tables

Revision ID: q1b2c3d4e5f6
Revises: p0a1b2c3d4e5
Create Date: 2026-06-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "p0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(table_name):
        return False
    return index_name in {item["name"] for item in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if not _has_table("import_batch_jobs"):
        op.create_table(
            "import_batch_jobs",
            sa.Column("job_id", sa.String(64), primary_key=True),
            sa.Column("source_type", sa.String(16), nullable=False, server_default="image"),
            sa.Column("subject", sa.String(32), nullable=True),
            sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("concurrency", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
    if not _has_index("import_batch_jobs", "ix_import_batch_jobs_status"):
        op.create_index("ix_import_batch_jobs_status", "import_batch_jobs", ["status"])
    if not _has_index("import_batch_jobs", "ix_import_batch_jobs_created_by"):
        op.create_index("ix_import_batch_jobs_created_by", "import_batch_jobs", ["created_by"])

    if not _has_table("import_batch_job_items"):
        op.create_table(
            "import_batch_job_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "job_id",
                sa.String(64),
                sa.ForeignKey("import_batch_jobs.job_id"),
                nullable=False,
            ),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("source_file", sa.String(256), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("ocr_raw_text", sa.Text(), nullable=True),
            sa.Column("ocr_cleaned_text", sa.Text(), nullable=True),
            sa.Column("review_batch_id", sa.String(64), nullable=True),
            sa.Column("pipeline_id", sa.String(64), nullable=True),
            sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("job_id", "seq", name="uq_batch_job_items_job_seq"),
        )
    if not _has_index("import_batch_job_items", "ix_import_batch_job_items_job_id"):
        op.create_index(
            "ix_import_batch_job_items_job_id", "import_batch_job_items", ["job_id"]
        )
    if not _has_index("import_batch_job_items", "ix_import_batch_job_items_status"):
        op.create_index(
            "ix_import_batch_job_items_status", "import_batch_job_items", ["status"]
        )


def downgrade() -> None:
    if _has_index("import_batch_job_items", "ix_import_batch_job_items_status"):
        op.drop_index("ix_import_batch_job_items_status", table_name="import_batch_job_items")
    if _has_index("import_batch_job_items", "ix_import_batch_job_items_job_id"):
        op.drop_index("ix_import_batch_job_items_job_id", table_name="import_batch_job_items")
    if _has_table("import_batch_job_items"):
        op.drop_table("import_batch_job_items")
    if _has_index("import_batch_jobs", "ix_import_batch_jobs_created_by"):
        op.drop_index("ix_import_batch_jobs_created_by", table_name="import_batch_jobs")
    if _has_index("import_batch_jobs", "ix_import_batch_jobs_status"):
        op.drop_index("ix_import_batch_jobs_status", table_name="import_batch_jobs")
    if _has_table("import_batch_jobs"):
        op.drop_table("import_batch_jobs")
