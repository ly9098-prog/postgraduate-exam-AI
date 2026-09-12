"""merge two heads

Revision ID: 812ba6628ff1
Revises: v10_export_tasks, v14_execution_generation_fencing
Create Date: 2026-07-26 11:26:41.716209

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '812ba6628ff1'
down_revision: Union[str, Sequence[str], None] = ('v10_export_tasks', 'v14_execution_generation_fencing')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
