from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReviewSchedule(Base):
    __tablename__ = "review_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False
    )
    subject: Mapped[str | None] = mapped_column(String(16), nullable=True)
    interval: Mapped[int] = mapped_column(Integer, default=0)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ReviewRecord(Base):
    __tablename__ = "review_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False
    )
    schedule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("review_schedules.id"), nullable=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ease_factor_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    ease_factor_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
