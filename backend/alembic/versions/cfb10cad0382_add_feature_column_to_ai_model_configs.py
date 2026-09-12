"""Add feature column to ai model configs for per-feature model selection

Revision ID: cfb10cad0382
Revises: b27f22b9ccc7
Create Date: 2026-06-16 17:42:39.432014

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "cfb10cad0382"
down_revision: Union[str, Sequence[str], None] = "b27f22b9ccc7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("admin_ai_model_configs", sa.Column("feature", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("admin_ai_model_configs", "feature")
