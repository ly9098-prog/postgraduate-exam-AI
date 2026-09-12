"""drop unused plaintext WeChat session key storage

Revision ID: b7c8d9e0f1a2
Revises: ae58f02b0567
Create Date: 2026-07-29

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "ae58f02b0567"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE users SET session_key = NULL WHERE session_key IS NOT NULL")
    op.drop_column("users", "session_key")


def downgrade() -> None:
    # The column is restored empty; sensitive credentials are never reconstructed.
    op.add_column("users", sa.Column("session_key", sa.String(length=256), nullable=True))
