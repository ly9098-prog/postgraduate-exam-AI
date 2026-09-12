"""add watermark rules table

Revision ID: l3b4c5d6e7f8
Revises: k2a3b4c5d6e7
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "l3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "k2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watermark_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("rule_type", sa.String(16), nullable=False, server_default="regex"),
        sa.Column("description", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("watermark_rules")
