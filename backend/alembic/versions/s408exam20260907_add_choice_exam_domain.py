"""add independent 408 choice-only exam domain

Revision ID: s408exam20260907
Revises: s408canonical20260907
Create Date: 2026-09-07

The exam domain intentionally stores immutable question_version_id bindings and
its own attempt/answer facts.  PracticeRecord is only an explicit downstream
learning projection created after a successful exam submission.
"""
import sqlalchemy as sa

from alembic import op

revision = "s408exam20260907"
down_revision = "s408canonical20260907"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_papers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("paper_type", sa.String(length=32), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "paper_type IN ('past_exam_choice','mock_choice')",
            name="ck_exam_papers_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft','published','archived')",
            name="ck_exam_papers_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_exam_papers_version_positive"),
        sa.CheckConstraint(
            "duration_sec IS NULL OR duration_sec > 0",
            name="ck_exam_papers_duration_positive",
        ),
    )
    op.create_index("ix_exam_papers_year", "exam_papers", ["year"])
    op.create_index(
        "ix_exam_papers_status_active_year",
        "exam_papers",
        ["status", "is_active", "year"],
    )

    op.create_table(
        "exam_paper_questions",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "paper_id",
            sa.Integer(),
            sa.ForeignKey("exam_papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey("questions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "question_version_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("question_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("score", sa.Numeric(8, 2), nullable=False),
        sa.Column(
            "section_subject_id",
            sa.Integer(),
            sa.ForeignKey("subjects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("paper_id", "position", name="uq_exam_paper_questions_position"),
        sa.UniqueConstraint("paper_id", "question_id", name="uq_exam_paper_questions_question"),
        sa.CheckConstraint("position > 0", name="ck_exam_paper_questions_position_positive"),
        sa.CheckConstraint("score > 0", name="ck_exam_paper_questions_score_positive"),
    )
    op.create_index("ix_exam_paper_questions_paper_id", "exam_paper_questions", ["paper_id"])
    op.create_index("ix_exam_paper_questions_question_id", "exam_paper_questions", ["question_id"])
    op.create_index("ix_exam_paper_questions_question_version_id", "exam_paper_questions", ["question_version_id"])
    op.create_index("ix_exam_paper_questions_section_subject_id", "exam_paper_questions", ["section_subject_id"])
    op.create_index("ix_exam_paper_questions_paper_position", "exam_paper_questions", ["paper_id", "position"])

    op.create_table(
        "exam_attempts",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "paper_id",
            sa.Integer(),
            sa.ForeignKey("exam_papers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("paper_version", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="in_progress"),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("answered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("result_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "request_id", name="uq_exam_attempts_user_request"),
        sa.CheckConstraint(
            "status IN ('in_progress','submitted','expired','abandoned')",
            name="ck_exam_attempts_status",
        ),
        sa.CheckConstraint("paper_version >= 1", name="ck_exam_attempts_paper_version_positive"),
        sa.CheckConstraint("duration_sec >= 0", name="ck_exam_attempts_duration_nonnegative"),
        sa.CheckConstraint("answered_count >= 0", name="ck_exam_attempts_answered_nonnegative"),
        sa.CheckConstraint("correct_count >= 0", name="ck_exam_attempts_correct_nonnegative"),
        sa.CheckConstraint("score >= 0", name="ck_exam_attempts_score_nonnegative"),
    )
    op.create_index("ix_exam_attempts_paper_id", "exam_attempts", ["paper_id"])
    op.create_index("ix_exam_attempts_user_id", "exam_attempts", ["user_id"])
    op.create_index(
        "uq_exam_attempts_user_paper_in_progress",
        "exam_attempts",
        ["user_id", "paper_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
        sqlite_where=sa.text("status = 'in_progress'"),
    )
    op.create_index("ix_exam_attempts_user_status_started", "exam_attempts", ["user_id", "status", "started_at"])
    op.create_index("ix_exam_attempts_user_paper_started", "exam_attempts", ["user_id", "paper_id", "started_at"])

    op.create_table(
        "exam_answers",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "attempt_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("exam_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exam_paper_question_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("exam_paper_questions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "question_version_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("question_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("selected_answer", sa.String(length=32), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Numeric(8, 2), nullable=True),
        sa.Column("used_time", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("marked_for_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.Column(
            "practice_record_id",
            sa.Integer(),
            sa.ForeignKey("practice_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("attempt_id", "exam_paper_question_id", name="uq_exam_answers_attempt_item"),
        sa.UniqueConstraint("practice_record_id", name="uq_exam_answers_practice_record"),
        sa.CheckConstraint("used_time >= 0", name="ck_exam_answers_used_time_nonnegative"),
        sa.CheckConstraint("score IS NULL OR score >= 0", name="ck_exam_answers_score_nonnegative"),
    )
    op.create_index("ix_exam_answers_attempt_id", "exam_answers", ["attempt_id"])
    op.create_index("ix_exam_answers_exam_paper_question_id", "exam_answers", ["exam_paper_question_id"])
    op.create_index("ix_exam_answers_question_id", "exam_answers", ["question_id"])
    op.create_index("ix_exam_answers_question_version_id", "exam_answers", ["question_version_id"])
    op.create_index("ix_exam_answers_practice_record_id", "exam_answers", ["practice_record_id"])
    op.create_index("ix_exam_answers_attempt_item", "exam_answers", ["attempt_id", "exam_paper_question_id"])


def downgrade() -> None:
    op.drop_table("exam_answers")
    op.drop_table("exam_attempts")
    op.drop_table("exam_paper_questions")
    op.drop_table("exam_papers")
