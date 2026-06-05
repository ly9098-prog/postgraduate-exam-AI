"""add import_pipeline tables

Revision ID: n5d6e7f8a9b0
Revises: m4c5d6e7f8g9
Create Date: 2026-06-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "m4c5d6e7f8g9"
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
    if not _has_table("import_pipelines"):
        op.create_table(
            "import_pipelines",
            sa.Column("pipeline_id", sa.String(64), primary_key=True),
            sa.Column("source_type", sa.String(16), nullable=False),
            sa.Column("source_file", sa.String(256), nullable=True),
            sa.Column("total_pages", sa.Integer(), nullable=True),
            sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="40"),
            sa.Column("status", sa.String(16), nullable=False, server_default="running"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
    if not _has_index("import_pipelines", "ix_import_pipelines_status"):
        op.create_index(
            "ix_import_pipelines_status", "import_pipelines", ["status"]
        )

    if not _has_table("import_pipeline_chunks"):
        op.create_table(
            "import_pipeline_chunks",
            sa.Column(
                "id", sa.Integer(), primary_key=True, autoincrement=True
            ),
            sa.Column(
                "pipeline_id",
                sa.String(64),
                sa.ForeignKey("import_pipelines.pipeline_id"),
                nullable=False,
            ),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("page_start", sa.Integer(), nullable=False),
            sa.Column("page_end", sa.Integer(), nullable=False),
            sa.Column(
                "status", sa.String(16), nullable=False, server_default="pending"
            ),
            sa.Column("batch_id", sa.String(64), nullable=True),
            sa.Column(
                "question_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "pipeline_id",
                "chunk_index",
                name="uq_pipeline_chunks_pipeline_index",
            ),
        )
    if not _has_index("import_pipeline_chunks", "ix_import_pipeline_chunks_pipeline_id"):
        op.create_index(
            "ix_import_pipeline_chunks_pipeline_id",
            "import_pipeline_chunks",
            ["pipeline_id"],
        )
    if not _has_index("import_pipeline_chunks", "ix_import_pipeline_chunks_status"):
        op.create_index(
            "ix_import_pipeline_chunks_status",
            "import_pipeline_chunks",
            ["status"],
        )


def downgrade() -> None:
    if _has_index("import_pipeline_chunks", "ix_import_pipeline_chunks_status"):
        op.drop_index(
            "ix_import_pipeline_chunks_status", table_name="import_pipeline_chunks"
        )
    if _has_index("import_pipeline_chunks", "ix_import_pipeline_chunks_pipeline_id"):
        op.drop_index(
            "ix_import_pipeline_chunks_pipeline_id",
            table_name="import_pipeline_chunks",
        )
    if _has_table("import_pipeline_chunks"):
        op.drop_table("import_pipeline_chunks")
    if _has_index("import_pipelines", "ix_import_pipelines_status"):
        op.drop_index("ix_import_pipelines_status", table_name="import_pipelines")
    if _has_table("import_pipelines"):
        op.drop_table("import_pipelines")
