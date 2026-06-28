"""add quality_report and alerts columns to import_pipelines

P7-4: persist pipeline quality report and alerts in DB so the
maintenance page health summary and alerts section work across
server restarts.

Revision ID: t4c5d6e7f8g9
Revises: 5edb3d7d7c1f
Create Date: 2026-06-28 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t4c5d6e7f8g9"
down_revision: Union[str, Sequence[str], None] = "5edb3d7d7c1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("import_pipelines", sa.Column("quality_report", sa.JSON(), nullable=True))
    op.add_column("import_pipelines", sa.Column("alerts", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("import_pipelines", "alerts")
    op.drop_column("import_pipelines", "quality_report")
