"""merge heads

Revision ID: c1d2e3f4a5b6
Revises: b4e3d2c1f0a9, e5b62f3a4c7d
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str]] = ('b4e3d2c1f0a9', 'e5b62f3a4c7d')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
