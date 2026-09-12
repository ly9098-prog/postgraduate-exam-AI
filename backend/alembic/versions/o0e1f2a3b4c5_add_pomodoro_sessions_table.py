"""add pomodoro_sessions table

Revision ID: o0e1f2a3b4c5
Revises: n5d6e7f8a9b0
Create Date: 2026-06-09 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "o0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "8779bfb39e9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pomodoro_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(32), nullable=False, server_default=""),
        sa.Column("chapter_id", sa.String(64), nullable=True),
        sa.Column("preset", sa.String(16), nullable=False, server_default="standard"),
        sa.Column("work_duration", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("break_duration", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("actual_duration", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_pomodoro_sessions_user_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pomodoro_sessions")),
    )
    op.create_index(op.f("ix_pomodoro_sessions_user_id"), "pomodoro_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_pomodoro_sessions_user_id"), table_name="pomodoro_sessions")
    op.drop_table("pomodoro_sessions")
