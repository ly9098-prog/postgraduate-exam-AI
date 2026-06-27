"""add composite indexes for question_imports list queries

Revision ID: 5edb3d7d7c1f
Revises: f2e3a4b5c6d7
Create Date: 2026-06-27 12:40:42.148686

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5edb3d7d7c1f'
down_revision: Union[str, Sequence[str], None] = 'f2e3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_question_imports_status_created_id', 'question_imports',
        ['status', 'created_at', 'id'], unique=False,
    )
    op.create_index(
        'ix_question_imports_batch_status_created_id', 'question_imports',
        ['batch_id', 'status', 'created_at', 'id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_question_imports_status_created_id', table_name='question_imports')
    op.drop_index('ix_question_imports_batch_status_created_id', table_name='question_imports')
