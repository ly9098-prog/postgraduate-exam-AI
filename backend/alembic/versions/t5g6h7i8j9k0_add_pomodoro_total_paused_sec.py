"""Add total_paused_sec to pomodoro_sessions (idempotent).

Revision ID: t5g6h7i8j9k0
Revises: s4g5h6i7j8k9
Create Date: 2026-07-09 23:00:00.000000

Idempotent: skips if table/column already exist.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "t5g6h7i8j9k0"
down_revision = "s4g5h6i7j8k9"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _is_sqlite() -> bool:
    try:
        return op.get_bind().dialect.name == "sqlite"
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "pomodoro_sessions"):
        return
    if _has_column(inspector, "pomodoro_sessions", "total_paused_sec"):
        return

    if _is_sqlite():
        with op.batch_alter_table("pomodoro_sessions") as batch_op:
            batch_op.add_column(sa.Column("total_paused_sec", sa.Integer(), nullable=False, server_default="0"))
    else:
        op.add_column("pomodoro_sessions", sa.Column("total_paused_sec", sa.Integer(), nullable=False, server_default="0"))
        op.alter_column("pomodoro_sessions", "total_paused_sec", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "pomodoro_sessions") and _has_column(inspector, "pomodoro_sessions", "total_paused_sec"):
        if _is_sqlite():
            with op.batch_alter_table("pomodoro_sessions") as batch_op:
                batch_op.drop_column("total_paused_sec")
        else:
            op.drop_column("pomodoro_sessions", "total_paused_sec")
