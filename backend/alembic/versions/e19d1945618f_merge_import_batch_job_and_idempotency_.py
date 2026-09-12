"""merge import batch job and idempotency heads

Revision ID: e19d1945618f
Revises: q1b2c3d4e5f6, r3c4d5e6f7g8
Create Date: 2026-06-24 18:28:35.996296

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'e19d1945618f'
down_revision: Union[str, Sequence[str], None] = ('q1b2c3d4e5f6', 'r3c4d5e6f7g8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
