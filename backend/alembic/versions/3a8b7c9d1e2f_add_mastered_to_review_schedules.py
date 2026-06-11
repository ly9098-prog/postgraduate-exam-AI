"""add_mastered_to_review_schedules

Revision ID: 3a8b7c9d1e2f
Revises: 2f5e1aae7d6c
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3a8b7c9d1e2f'
down_revision: Union[str, Sequence[str], None] = '2f5e1aae7d6c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('review_schedules', sa.Column('mastered', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('review_schedules', 'mastered')
