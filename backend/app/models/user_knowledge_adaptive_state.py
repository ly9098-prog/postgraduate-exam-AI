"""V6 知识点自适应间隔倍率 — 记录用户在每个知识点上的遗忘速度。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm_base import Base


class UserKnowledgeAdaptiveState(Base):
    """知识点级别的自适应间隔倍率。

    与 UserAdaptiveProfile（用户全局）互补：
    某些知识点用户遗忘快（factor < 1），某些遗忘慢（factor > 1）。
    """

    __tablename__ = "user_knowledge_adaptive_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    knowledge_point_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knowledge_points.id"),
        nullable=False,
        index=True,
    )

    interval_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    due_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_review_correct_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    overdue_wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_adjusted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "knowledge_point_id",
            name="uq_ukas_user_kp",
        ),
    )
