from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AnswerBehavior(Base):
    __tablename__ = "answer_behaviors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("questions.id"), nullable=False)
    practice_record_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("practice_records.id"), nullable=True)
    subject_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subject_ref = relationship("Subject", back_populates="answer_behaviors", lazy="noload")

    # 答题行为
    time_spent_sec: Mapped[int] = mapped_column(Integer, default=0)
    is_first_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_final_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    view_answer_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    switch_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_abandoned: Mapped[bool] = mapped_column(Boolean, default=False)

    # 答案
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 元信息
    session_type: Mapped[str] = mapped_column(String(32), default="random")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
