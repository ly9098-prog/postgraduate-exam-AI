"""merge v8_wrong_question_soft_delete and deleted_at_users

Revision ID: 32d214360cf1
Revises: v8_wrong_question_soft_delete, 6f7d91a01d3b
Create Date: 2026-07-12 20:44:26.662418

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '32d214360cf1'
down_revision: Union[str, Sequence[str], None] = ('v8_wrong_question_soft_delete', '6f7d91a01d3b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
