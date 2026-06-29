"""merge p5_2_1_practice_records_fk into main

Revision ID: 25b0a2fea77a
Revises: p5_2_1_practice_records_fk, 7386c399b670
Create Date: 2026-06-29 14:28:27.897331

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25b0a2fea77a'
down_revision: Union[str, Sequence[str], None] = ('p5_2_1_practice_records_fk', '7386c399b670')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
