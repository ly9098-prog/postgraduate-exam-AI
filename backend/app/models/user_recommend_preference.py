"""V6.4 用户推荐权重偏好 — 个性化 smart 推荐各维度权重。"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserRecommendPreference(Base):
    """用户对 smart 推荐各评分维度的个性化权重。

    每个权重范围 [0.7, 1.3]，默认 1.0。
    系统根据近期表现自动微调，也可由用户手动覆盖（未来）。
    """

    __tablename__ = "user_recommend_preference"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True,
    )

    due_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    weakness_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    wrong_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    new_question_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    diversity_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    difficulty_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    path_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    last_adjusted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_urp_user_id"),
    )
