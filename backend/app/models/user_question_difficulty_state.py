"""V6 个人题目难度状态 — 根据用户作答表现自动校准每道题的个人难度。"""
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserQuestionDifficultyState(Base):
    """用户视角下的题目难度。

    personal_difficulty_score 范围 0~100：
    - 0~30: easy（对该用户简单）
    - 30~70: normal
    - 70~100: hard（对该用户困难）

    每次答题后根据对错 + 耗时动态更新。
    """

    __tablename__ = "user_question_difficulty_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True,
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True,
    )

    personal_difficulty_score: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    difficulty_label: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")

    answer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_answer_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    fast_correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    slow_correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    slow_wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overdue_wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "question_id",
            name="uq_uqds_user_question",
        ),
    )
