from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PomodoroSession(Base):
    __tablename__ = "pomodoro_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    chapter_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preset: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    work_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    break_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
