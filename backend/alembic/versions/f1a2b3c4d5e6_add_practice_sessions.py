"""add practice_sessions table

Adds ``practice_sessions`` — one row per completed practice batch (a user's
single practice session from start to successful submit).  Learning-time
statistics (pomodoro stats page duration metrics) merge PracticeSession with
PomodoroSession, while PracticeRecord stays per-question behavior analytics.

Idempotency: ``(user_id, request_id)`` partial unique index prevents duplicate
sessions from client network retries.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision = "f6e7a8b9c0d1"
branch_labels = None
depends_on = None


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _create_practice_sessions() -> None:
    op.create_table(
        "practice_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=256), nullable=True),
        sa.Column("mode", sa.String(length=16), server_default="random", nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False),
        sa.Column("question_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("answered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("correct_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("wrong_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="completed", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"],
            name=op.f("fk_practice_sessions_subject_id"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_practice_sessions_user_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_sessions")),
        sa.CheckConstraint(
            "duration_sec >= 0", name="ck_practice_sessions_duration_sec"
        ),
        sa.CheckConstraint(
            "finished_at >= started_at", name="ck_practice_sessions_finished_at"
        ),
    )


def _create_practice_sessions_indexes() -> None:
    op.create_index(
        op.f("ix_practice_sessions_user_id"),
        "practice_sessions",
        ["user_id"],
    )
    op.create_index(
        op.f("ix_practice_sessions_subject_id"),
        "practice_sessions",
        ["subject_id"],
    )
    op.create_index(
        op.f("ix_practice_sessions_user_started"),
        "practice_sessions",
        ["user_id", "started_at"],
    )
    op.create_index(
        op.f("ix_practice_sessions_user_finished"),
        "practice_sessions",
        ["user_id", "finished_at"],
    )
    # Partial unique index: only rows with a non-null request_id are deduplicated
    # (old clients never write a session row, so they are unaffected).
    op.create_index(
        op.f("ux_practice_sessions_user_request"),
        "practice_sessions",
        ["user_id", "request_id"],
        unique=True,
        sqlite_where=sa.text("request_id IS NOT NULL"),
        postgresql_where=sa.text("request_id IS NOT NULL"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "practice_sessions"):
        return

    _create_practice_sessions()
    _create_practice_sessions_indexes()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "practice_sessions"):
        return

    op.drop_table("practice_sessions")
