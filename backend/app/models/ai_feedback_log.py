from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm_base import Base


class AiFeedbackLog(Base):
    __tablename__ = "ai_feedback_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # 'dashboard' | 'wrong_book'
    feedback_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # user-selected type
    question_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
