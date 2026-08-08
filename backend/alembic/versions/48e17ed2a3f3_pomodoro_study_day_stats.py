"""pomodoro study day stats

Adds:
- ``user_pomodoro_settings`` (per-user day_start_minute)
- ``pomodoro_pause_intervals`` (exact pause positions for duration attribution)
- composite indexes on ``pomodoro_sessions(user_id, status, start_time|end_time)``

Idempotent: each step is skipped when the target already exists, so re-running
against an already-migrated database is a no-op.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "48e17ed2a3f3"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_index(inspector, table: str, index: str) -> bool:
    return index in {i["name"] for i in inspector.get_indexes(table)}


def _create_user_pomodoro_settings() -> None:
    op.create_table(
        "user_pomodoro_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day_start_minute", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_user_pomodoro_settings_user_id")),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_pomodoro_settings")),
    )


def _create_pause_intervals() -> None:
    op.create_table(
        "pomodoro_pause_intervals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["pomodoro_sessions.id"],
            ondelete="CASCADE", name=op.f("fk_pomodoro_pause_intervals_session_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pomodoro_pause_intervals")),
    )


def _create_pause_intervals_index() -> None:
    op.create_index(
        op.f("ix_pomodoro_pause_intervals_session_started"),
        "pomodoro_pause_intervals",
        ["session_id", "started_at"],
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "user_pomodoro_settings"):
        _create_user_pomodoro_settings()

    inspector = sa.inspect(bind)  # refresh

    if not _has_table(inspector, "pomodoro_pause_intervals"):
        _create_pause_intervals()
    if _has_table(inspector, "pomodoro_pause_intervals") and not _has_index(
        inspector, "pomodoro_pause_intervals", "ix_pomodoro_pause_intervals_session_started"
    ):
        _create_pause_intervals_index()

    if _has_table(inspector, "pomodoro_sessions"):
        if not _has_index(inspector, "pomodoro_sessions", "ix_pomodoro_sessions_user_status_start"):
            op.create_index(
                "ix_pomodoro_sessions_user_status_start",
                "pomodoro_sessions",
                ["user_id", "status", "start_time"],
            )
        if not _has_index(inspector, "pomodoro_sessions", "ix_pomodoro_sessions_user_status_end"):
            op.create_index(
                "ix_pomodoro_sessions_user_status_end",
                "pomodoro_sessions",
                ["user_id", "status", "end_time"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "pomodoro_pause_intervals"):
        if _has_index(inspector, "pomodoro_pause_intervals", "ix_pomodoro_pause_intervals_session_started"):
            op.drop_index("ix_pomodoro_pause_intervals_session_started", table_name="pomodoro_pause_intervals")
        op.drop_table("pomodoro_pause_intervals")

    if _has_table(inspector, "user_pomodoro_settings"):
        op.drop_table("user_pomodoro_settings")

    if _has_table(inspector, "pomodoro_sessions"):
        if _has_index(inspector, "pomodoro_sessions", "ix_pomodoro_sessions_user_status_start"):
            op.drop_index("ix_pomodoro_sessions_user_status_start", table_name="pomodoro_sessions")
        if _has_index(inspector, "pomodoro_sessions", "ix_pomodoro_sessions_user_status_end"):
            op.drop_index("ix_pomodoro_sessions_user_status_end", table_name="pomodoro_sessions")
