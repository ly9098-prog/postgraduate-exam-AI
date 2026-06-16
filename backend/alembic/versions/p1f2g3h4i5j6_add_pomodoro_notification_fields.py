"""Add pomodoro notification fields (stub — already applied to DB)

Revision ID: p1f2g3h4i5j6
Revises: q1b2c3d4e5f6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p1f2g3h4i5j6"
down_revision: Union[str, Sequence[str], None] = "q1b2c3d4e5f6"


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
