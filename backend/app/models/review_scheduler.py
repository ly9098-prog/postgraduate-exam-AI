from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ReviewSchedule(Base):
    __tablename__ = "review_schedules"
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_review_schedules_user_question"),
        Index("ix_review_schedules_user_subject_id", "user_id", "subject_id"),
        Index("ix_review_schedules_user_version", "user_id", "question_version_id"),
        CheckConstraint("occurrence_seq >= 0", name="ck_review_schedules_occurrence_nonnegative"),
        CheckConstraint("interval >= 0", name="ck_review_schedules_interval_nonnegative"),
        CheckConstraint("repetitions >= 0", name="ck_review_schedules_repetitions_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    question_version_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("question_versions.id"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    subject_ref = relationship("Subject", back_populates="review_schedules", lazy="noload")
    interval: Mapped[int] = mapped_column(Integer, default=0)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mastered: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Monotonic server-owned identity of the next review occurrence. Each
    # successful submission consumes exactly one occurrence and increments it.
    occurrence_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ReviewRecord(Base):
    __tablename__ = "review_records"
    __table_args__ = (
        Index("ix_review_records_user_version", "user_id", "question_version_id"),
        UniqueConstraint("schedule_id", "occurrence_seq", name="uq_review_records_schedule_occurrence"),
        UniqueConstraint("user_id", "request_id", name="uq_review_records_user_request"),
        CheckConstraint("occurrence_seq >= 0", name="ck_review_records_occurrence_nonnegative"),
        CheckConstraint("rating >= 0 AND rating <= 5", name="ck_review_records_rating_range"),
        CheckConstraint(
            "mastery_percent IS NULL OR (mastery_percent >= 0 AND mastery_percent <= 100)",
            name="ck_review_records_mastery_percent_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    question_version_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("question_versions.id"),
        nullable=False,
        index=True,
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurrence_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mastery_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mastered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    schedule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("review_schedules.id"), nullable=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ease_factor_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    ease_factor_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
