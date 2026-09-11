from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class KnowledgePoint(Base):
    """知识点主表 — 科目级别的规范化知识点定义"""

    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id"), nullable=False, index=True
    )
    subject_ref = relationship(
        "Subject", back_populates="knowledge_points", lazy="noload"
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty_level: Mapped[int] = mapped_column(SmallInteger, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "subject_id", "normalized_name", name="uq_kp_subject_id_normalized_name"
        ),
    )
