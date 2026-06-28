from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QuestionKnowledgePoint(Base):
    """题目-知识点映射表 — 关联题目和规范化知识点"""

    __tablename__ = "question_knowledge_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    knowledge_point_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), default="main")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(16), default="imported")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("question_id", "knowledge_point_id", name="uq_qkp_question_kp"),
    )
