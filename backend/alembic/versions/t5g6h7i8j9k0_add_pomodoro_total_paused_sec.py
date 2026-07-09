"""Add total_paused_sec to pomodoro_sessions.

Revision ID: t5g6h7i8j9k0
Revises: s4g5h6i7j8k9
Create Date: 2026-07-09 23:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "t5g6h7i8j9k0"
down_revision = "s4g5h6i7j8k9"
branch_labels = None
depends_on = None


def _is_sqlite() -> bool:
    try:
        return op.get_bind().dialect.name == "sqlite"
    except Exception:
        return False


def upgrade() -> None:
    op.add_column("pomodoro_sessions", sa.Column("total_paused_sec", sa.Integer(), nullable=False, server_default="0"))
    if not _is_sqlite():
        op.alter_column("pomodoro_sessions", "total_paused_sec", server_default=None)


def downgrade() -> None:
    op.drop_column("pomodoro_sessions", "total_paused_sec")
