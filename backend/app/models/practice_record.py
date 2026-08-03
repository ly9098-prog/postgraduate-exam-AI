from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.features.question_type import QT_SINGLE_CHOICE


class PracticeRecord(Base):
    """用户做题记录 — 每道题一条记录"""

    __tablename__ = "practice_records"
    __table_args__ = (
        Index("idx_practice_records_user_subject_id", "user_id", "subject_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id"), nullable=False
    )
    subject_ref = relationship("Subject", back_populates="practice_records", lazy="noload")
    question_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=QT_SINGLE_CHOICE
    )
    user_answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    used_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # ── Legacy session columns (prevent autogenerate DROP COLUMN) ──
    # These columns were in the original practice_records table before the
    # per-question schema refactor.  Keep them in the ORM so Alembic
    # autogenerate does not emit DROP COLUMN for them.
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    question_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    answers: Mapped[str | None] = mapped_column(Text, nullable=True)
    correct_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wrong_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
