from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QuestionImport(Base):
    __tablename__ = "question_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(32), nullable=True)
    question_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    parsed_content: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parsed_options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parsed_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_hash: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    duplicate_status: Mapped[str] = mapped_column(String(32), nullable=False, default="normal", index=True)
    duplicate_of_question_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duplicate_of_import_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # AI 辅助导题字段（阶段七）
    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ai_answer_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 数学公式图片化（Stage 3）
    math_regions: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Merge supersede tracking (P0-4): when an old batch is superseded by a merge,
    # these fields record which batch superseded it and when.
    superseded_by_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
