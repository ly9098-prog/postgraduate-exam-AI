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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.orm_base import Base


class QuestionKnowledgePoint(Base):
    """题目-知识点映射表 — 关联题目和规范化知识点"""

    __tablename__ = "question_knowledge_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_point_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_points.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), default="main")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(16), default="imported")
    # 原 questions.knowledge_points JSON 数组内的下标（0 基），保留知识点展示顺序。
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    question = relationship(
        "Question", back_populates="knowledge_point_links", lazy="noload"
    )
    knowledge_point = relationship("KnowledgePoint", lazy="noload")

    __table_args__ = (
        UniqueConstraint(
            "question_id", "knowledge_point_id", name="uq_qkp_question_kp"
        ),
        UniqueConstraint(
            "question_id", "position", name="uq_qkp_question_position"
        ),
    )
