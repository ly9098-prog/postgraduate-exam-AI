from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserKnowledgeState(Base):
    """用户知识点掌握度状态 — 持久化用户对每个知识点的掌握情况。

    V3: 新增 confidence、recent_* 系列、last_is_correct、last_answer_time_seconds。
    mastery_score 范围 0-100，初始 50（未知状态）。
    """

    __tablename__ = "user_knowledge_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subject_ref = relationship(
        "Subject", back_populates="user_knowledge_states", lazy="noload"
    )
    knowledge_point_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    mastery_score: Mapped[float] = mapped_column(Float, default=50.0)
    weakness_level: Mapped[str] = mapped_column(String(16), default="unknown")

    # V3 新增字段
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recent_answer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recent_correct_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    recent_wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_answer_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_wrong_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "knowledge_point_id", name="uq_uks_user_kp"),
        Index("ix_uks_user_subject_id", "user_id", "subject_id"),
    )
