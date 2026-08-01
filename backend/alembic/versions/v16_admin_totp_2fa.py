"""Add TOTP 2FA columns to admin_users

Revision ID: v16_admin_totp_2fa
Revises: c9d8e7f6a5b4
Create Date: 2026-08-01
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "v16_admin_totp_2fa"
down_revision: Union[str, Sequence[str], None] = "c9d8e7f6a5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("admin_users", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column(
        "admin_users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("admin_users", sa.Column("totp_confirmed_at", sa.DateTime(), nullable=True))
    op.add_column("admin_users", sa.Column("totp_backup_codes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("admin_users", "totp_backup_codes")
    op.drop_column("admin_users", "totp_confirmed_at")
    op.drop_column("admin_users", "totp_enabled")
    op.drop_column("admin_users", "totp_secret")
