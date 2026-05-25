from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    question_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="choice"
    )
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    difficulty: Mapped[int] = mapped_column(SmallInteger, default=3)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    import_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[list | None] = mapped_column(JSON, nullable=True)
    year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    review_status: Mapped[str] = mapped_column(String(16), default="approved")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
