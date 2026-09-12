"""merge fix_v8 and ocr_jobs heads

Revision ID: c392c0978aca
Revises: fix_v8_wrong_question_columns, 0d608fe34f9d
Create Date: 2026-07-19 13:21:29.448683

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'c392c0978aca'
down_revision: Union[str, Sequence[str], None] = ('fix_v8_wrong_question_columns', '0d608fe34f9d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
