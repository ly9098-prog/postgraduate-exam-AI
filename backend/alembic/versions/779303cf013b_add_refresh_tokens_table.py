"""add refresh_tokens table

Revision ID: 779303cf013b
Revises: cfb10cad0382
Create Date: 2026-06-18 14:12:19.575818

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '779303cf013b'
down_revision: Union[str, Sequence[str], None] = 'cfb10cad0382'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('token_hash', sa.String(length=64), nullable=False, unique=True, index=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('refresh_tokens')
