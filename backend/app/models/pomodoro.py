from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PomodoroSession(Base):
    __tablename__ = "pomodoro_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True, index=True)
    chapter_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    subject_ref = relationship("Subject", back_populates="pomodoro_sessions")
    preset: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    work_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    break_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expected_end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    actual_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    notification_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notification_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    openid_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_paused_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
