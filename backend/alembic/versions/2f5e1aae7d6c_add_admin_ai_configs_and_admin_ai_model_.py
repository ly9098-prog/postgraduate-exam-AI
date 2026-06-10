"""add admin_ai_configs and admin_ai_model_configs

Revision ID: 2f5e1aae7d6c
Revises: o0e1f2a3b4c5
Create Date: 2026-06-10 16:43:23.815778

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2f5e1aae7d6c'
down_revision: Union[str, Sequence[str], None] = 'o0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('admin_ai_configs',
        sa.Column('config_key', sa.String(length=64), nullable=False),
        sa.Column('config_value', sa.Text(), nullable=False, server_default=''),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('config_key'),
    )
    op.create_table('admin_ai_model_configs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('display_name', sa.String(length=64), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('api_base_url', sa.String(length=256), nullable=True),
        sa.Column('api_key_encrypted', sa.String(length=512), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )


def downgrade() -> None:
    op.drop_table('admin_ai_model_configs')
    op.drop_table('admin_ai_configs')
