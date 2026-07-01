"""V6 用户自适应间隔画像 — 记录用户整体遗忘速度倍率。"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserAdaptiveProfile(Base):
    """用户级别的自适应间隔倍率。

    interval_factor 根据到期复习正确率动态调整：
    - 到期答错 → factor *= 0.92（缩短间隔）
    - 到期答对 → factor *= 1.04（小幅拉长）
    - 逾期答对 → factor *= 1.08（明显拉长）
    范围：[min_interval_factor, max_interval_factor]
    """

    __tablename__ = "user_adaptive_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True,
    )

    interval_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    min_interval_factor: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    max_interval_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.6)

    target_recall_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    recent_due_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recent_due_correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_adjusted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_uap_user_id"),
    )
