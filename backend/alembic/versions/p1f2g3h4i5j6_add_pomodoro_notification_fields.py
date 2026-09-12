"""add pomodoro notification fields

Revision ID: p1f2g3h4i5j6
Revises: 3a8b7c9d1e2f
Create Date: 2026-06-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "p1f2g3h4i5j6"
down_revision: Union[str, Sequence[str], None] = "3a8b7c9d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pomodoro_sessions",
        sa.Column("expected_end_time", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "pomodoro_sessions",
        sa.Column(
            "notification_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "pomodoro_sessions",
        sa.Column(
            "notification_sent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "pomodoro_sessions",
        sa.Column("notification_sent_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "pomodoro_sessions",
        sa.Column("notification_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "pomodoro_sessions",
        sa.Column("openid_snapshot", sa.String(64), nullable=True),
    )
    op.create_index(
        op.f("ix_pomodoro_sessions_expected_end_time"),
        "pomodoro_sessions",
        ["expected_end_time"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_pomodoro_sessions_expected_end_time"),
        table_name="pomodoro_sessions",
    )
    op.drop_column("pomodoro_sessions", "openid_snapshot")
    op.drop_column("pomodoro_sessions", "notification_error")
    op.drop_column("pomodoro_sessions", "notification_sent_at")
    op.drop_column("pomodoro_sessions", "notification_sent")
    op.drop_column("pomodoro_sessions", "notification_enabled")
    op.drop_column("pomodoro_sessions", "expected_end_time")
