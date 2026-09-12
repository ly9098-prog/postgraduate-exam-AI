"""v11: Add version column to export_tasks for stale-event detection

Chains after ``f9e0d1c2b3a4`` (the migration already applied on production
at deploy time), keeping the history linear.

Revision ID: v11_export_version
Revises: f9e0d1c2b3a4
Create Date: 2026-07-27
"""

import sqlalchemy as sa

from alembic import op

revision = "v11_export_version"
down_revision = "f9e0d1c2b3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "export_tasks",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("export_tasks", "version")
