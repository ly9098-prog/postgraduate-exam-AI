from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Tag(Base):
    """轻量标签。保留 parent_id 供后续扩展层级，MVP 暂不使用。"""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subject_ref = relationship("Subject", back_populates="tags", lazy="noload")
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    sync_uuid: Mapped[str | None] = mapped_column(
        String(36), nullable=True, unique=True, index=True, default=lambda: str(uuid4())
    )
