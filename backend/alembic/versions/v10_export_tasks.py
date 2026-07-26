"""v10: Create export_tasks and export_snapshots tables

Revision ID: v10_export_tasks
Revises: v9_formula_approved_to_published_migration
Create Date: 2026-07-25
"""

from alembic import op
import sqlalchemy as sa

revision = "v10_export_tasks"
down_revision = "v9_formula_approved_to_published_migration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # export_tasks
    op.create_table(
        "export_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("file_format", sa.String(10), nullable=False, server_default="pdf"),
        sa.Column("range_type", sa.String(20), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column("selected_ids", sa.JSON(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("show_date", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("export_date", sa.String(32), nullable=False),
        sa.Column("sort_by", sa.String(32), nullable=False, server_default="newest"),
        sa.Column("group_by", sa.String(32), nullable=False, server_default="none"),
        sa.Column("answer_position", sa.String(16), nullable=False, server_default="none"),
        sa.Column("analysis_position", sa.String(16), nullable=False, server_default="none"),
        sa.Column("space_style", sa.String(16), nullable=False, server_default="standard"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=True),
        sa.Column("skip_count", sa.Integer(), nullable=True),
        sa.Column("skip_reasons", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_key", sa.String(512), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("snapshot_id", sa.String(36), nullable=True, index=True),
        sa.Column("source_task_id", sa.Integer(), sa.ForeignKey("export_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True, unique=True),
        sa.Column("retry_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("processing_started_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("generator_version", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True, index=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_export_tasks_user_status", "export_tasks", ["user_id", "status"])
    op.create_index("ix_export_tasks_status_created", "export_tasks", ["status", "created_at"])

    # export_snapshots
    op.create_table(
        "export_snapshots",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("data_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("export_snapshots")
    op.drop_table("export_tasks")
