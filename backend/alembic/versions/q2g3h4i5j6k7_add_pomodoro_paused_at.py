"""Add pomodoro paused_at (stub — already applied to DB)

Revision ID: q2g3h4i5j6k7
Revises: p1f2g3h4i5j6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q2g3h4i5j6k7"
down_revision: Union[str, Sequence[str], None] = "p1f2g3h4i5j6"


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
