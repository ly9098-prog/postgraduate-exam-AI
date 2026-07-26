"""v11: Add version column to export_tasks for stale-event detection

Revision ID: v11_export_version
Revises: v10_export_tasks
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa

revision = "v11_export_version"
down_revision = "812ba6628ff1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "export_tasks",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("export_tasks", "version")
