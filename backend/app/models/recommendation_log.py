from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RecommendationLog(Base):
    """推荐日志 — 记录推荐给用户题目及其后续反馈"""

    __tablename__ = "recommendation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scene: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_question_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommend_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Phase 4: 实验分组 + 策略配置 + 掌握度变化
    experiment_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    variant_key: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    strategy_config_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    mastery_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    mastery_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    mastery_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    shown_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
