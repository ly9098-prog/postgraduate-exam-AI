from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ExamPaper(Base):
    """Immutable-after-publish choice-only 408 exam definition."""

    __tablename__ = "exam_papers"
    __table_args__ = (
        CheckConstraint(
            "paper_type IN ('past_exam_choice','mock_choice')",
            name="ck_exam_papers_type",
        ),
        CheckConstraint(
            "status IN ('draft','published','archived')",
            name="ck_exam_papers_status",
        ),
        CheckConstraint("version >= 1", name="ck_exam_papers_version_positive"),
        CheckConstraint(
            "duration_sec IS NULL OR duration_sec > 0",
            name="ck_exam_papers_duration_positive",
        ),
        Index("ix_exam_papers_status_active_year", "status", "is_active", "year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    paper_type: Mapped[str] = mapped_column(String(32), nullable=False)
    year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    items: Mapped[list["ExamPaperQuestion"]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ExamPaperQuestion.position",
        lazy="noload",
    )
    attempts: Mapped[list["ExamAttempt"]] = relationship(
        back_populates="paper",
        lazy="noload",
    )


class ExamPaperQuestion(Base):
    __tablename__ = "exam_paper_questions"
    __table_args__ = (
        UniqueConstraint("paper_id", "position", name="uq_exam_paper_questions_position"),
        UniqueConstraint("paper_id", "question_id", name="uq_exam_paper_questions_question"),
        CheckConstraint("position > 0", name="ck_exam_paper_questions_position_positive"),
        CheckConstraint("score > 0", name="ck_exam_paper_questions_score_positive"),
        Index("ix_exam_paper_questions_paper_position", "paper_id", "position"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("exam_papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    question_version_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("question_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    section_subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    paper: Mapped[ExamPaper] = relationship(back_populates="items", lazy="noload")


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress','submitted','expired','abandoned')",
            name="ck_exam_attempts_status",
        ),
        CheckConstraint("paper_version >= 1", name="ck_exam_attempts_paper_version_positive"),
        CheckConstraint("duration_sec >= 0", name="ck_exam_attempts_duration_nonnegative"),
        CheckConstraint("answered_count >= 0", name="ck_exam_attempts_answered_nonnegative"),
        CheckConstraint("correct_count >= 0", name="ck_exam_attempts_correct_nonnegative"),
        CheckConstraint("score >= 0", name="ck_exam_attempts_score_nonnegative"),
        UniqueConstraint("user_id", "request_id", name="uq_exam_attempts_user_request"),
        Index(
            "uq_exam_attempts_user_paper_in_progress",
            "user_id",
            "paper_id",
            unique=True,
            postgresql_where=text("status = 'in_progress'"),
            sqlite_where=text("status = 'in_progress'"),
        ),
        Index("ix_exam_attempts_user_status_started", "user_id", "status", "started_at"),
        Index("ix_exam_attempts_user_paper_started", "user_id", "paper_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("exam_papers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    paper_version: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_progress", server_default="in_progress")
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    answered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    score: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0, server_default="0")
    result_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    paper: Mapped[ExamPaper] = relationship(back_populates="attempts", lazy="noload")
    answers: Mapped[list["ExamAnswer"]] = relationship(
        back_populates="attempt",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="noload",
    )


class ExamAnswer(Base):
    __tablename__ = "exam_answers"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "exam_paper_question_id",
            name="uq_exam_answers_attempt_item",
        ),
        CheckConstraint("used_time >= 0", name="ck_exam_answers_used_time_nonnegative"),
        CheckConstraint("score IS NULL OR score >= 0", name="ck_exam_answers_score_nonnegative"),
        Index("ix_exam_answers_attempt_item", "attempt_id", "exam_paper_question_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    attempt_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("exam_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exam_paper_question_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("exam_paper_questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    question_version_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("question_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    selected_answer: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    used_time: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    marked_for_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    practice_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("practice_records.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    attempt: Mapped[ExamAttempt] = relationship(back_populates="answers", lazy="noload")
