"""v14: add review_sessions table

One row per (today-review group submission, subject).  Learning-time statistics
(pomodoro stats page duration metrics) merge ReviewSession alongside
PracticeSession, so time spent in 今日复习 counts toward 刷题时长.

Idempotency: ``(user_id, request_id)`` unique constraint prevents duplicate
rows from client network retries.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "v14_add_review_sessions"
down_revision = "v13_multi_blank_multiple_choice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "review_sessions" in inspector.get_table_names():
        return

    op.create_table(
        "review_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=160), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False),
        sa.Column("question_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("correct_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("wrong_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="completed", nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_review_sessions_user_id")
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subjects.id"],
            name=op.f("fk_review_sessions_subject_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_sessions")),
        sa.UniqueConstraint(
            "user_id", "request_id", name="uq_review_sessions_user_request"
        ),
        sa.CheckConstraint("duration_sec >= 0", name="ck_review_sessions_duration_sec"),
        sa.CheckConstraint(
            "finished_at >= started_at", name="ck_review_sessions_finished_at"
        ),
    )
    op.create_index(
        op.f("ix_review_sessions_user_id"), "review_sessions", ["user_id"]
    )
    op.create_index(
        "ix_review_sessions_user_started", "review_sessions", ["user_id", "started_at"]
    )
    op.create_index(
        "ix_review_sessions_user_finished",
        "review_sessions",
        ["user_id", "finished_at"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "review_sessions" not in inspector.get_table_names():
        return
    op.drop_table("review_sessions")
