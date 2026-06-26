"""add notification columns to pomodoro_sessions (backfill for deprecated feature)

Revision ID: p0a1b2c3d4e5
Revises: 3a8b7c9d1e2f
Create Date: 2026-06-14 00:00:00.000000
"""
from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "p0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "3a8b7c9d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    conn = op.get_bind()
    return conn.dialect.has_table(conn, name)


def _has_column(table: str, column: str) -> bool:
    from sqlalchemy import inspect
    conn = op.get_bind()
    if not conn.dialect.has_table(conn, table):
        return False
    inspector = inspect(conn)
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_index(table: str, index: str) -> bool:
    from sqlalchemy import inspect
    conn = op.get_bind()
    if not conn.dialect.has_table(conn, table):
        return False
    inspector = inspect(conn)
    return any(i["name"] == index for i in inspector.get_indexes(table))


_COLUMNS: list[tuple[str, sa.Column]] = [
    ("expected_end_time", sa.Column("expected_end_time", sa.DateTime(), nullable=True)),
    ("notification_enabled", sa.Column("notification_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
    ("notification_sent", sa.Column("notification_sent", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
    ("notification_sent_at", sa.Column("notification_sent_at", sa.DateTime(), nullable=True)),
    ("notification_error", sa.Column("notification_error", sa.Text(), nullable=True)),
    ("openid_snapshot", sa.Column("openid_snapshot", sa.String(64), nullable=True)),
    ("paused_at", sa.Column("paused_at", sa.DateTime(), nullable=True)),
]


def upgrade() -> None:
    if not _has_table("pomodoro_sessions"):
        return
    for col_name, col in _COLUMNS:
        if not _has_column("pomodoro_sessions", col_name):
            op.add_column("pomodoro_sessions", col)
    if not _has_index("pomodoro_sessions", "ix_pomodoro_sessions_expected_end_time"):
        op.create_index("ix_pomodoro_sessions_expected_end_time", "pomodoro_sessions", ["expected_end_time"])


def downgrade() -> None:
    if not _has_table("pomodoro_sessions"):
        return
    if _has_index("pomodoro_sessions", "ix_pomodoro_sessions_expected_end_time"):
        op.drop_index("ix_pomodoro_sessions_expected_end_time", table_name="pomodoro_sessions")
    for col_name, _ in reversed(_COLUMNS):
        if _has_column("pomodoro_sessions", col_name):
            op.drop_column("pomodoro_sessions", col_name)
