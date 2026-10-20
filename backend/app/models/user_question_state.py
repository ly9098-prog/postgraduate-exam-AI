from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm_base import Base


class UserQuestionState(Base):
    """用户题目复习状态表：用于 Leitner 盒子和 next_review_at 调度。

    每个用户 + 每道题只有一条状态记录（UNIQUE 约束）。
    记录当前盒子等级、下次复习时间、连续答对/错次数等。
    """

    __tablename__ = "user_question_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("questions.id"),
        nullable=False,
        index=True,
    )

    # Leitner 盒子等级：0=很不熟/刚做错，5=稳定掌握
    box_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    correct_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wrong_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    answer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_answer_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "question_id",
            name="uq_user_question_state_user_question",
        ),
        Index(
            "ix_user_question_state_user_next_review",
            "user_id",
            "next_review_at",
        ),
    )
