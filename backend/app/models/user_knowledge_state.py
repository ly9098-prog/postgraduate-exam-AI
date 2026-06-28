from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserKnowledgeState(Base):
    """用户知识点掌握度状态 — 持久化用户对每个知识点的掌握情况"""

    __tablename__ = "user_knowledge_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    mastery_score: Mapped[float] = mapped_column(Float, default=0.0)
    weakness_level: Mapped[str] = mapped_column(
        String(16), default="unknown"
    )
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_wrong_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "knowledge_point_id", name="uq_uks_user_kp"),
        Index("ix_uks_user_subject", "user_id", "subject"),
    )
