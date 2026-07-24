from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class QuestionImport(Base):
    __tablename__ = "question_imports"

    __table_args__ = (
        Index("ix_question_imports_status_created_id", "status", "created_at", "id"),
        Index("ix_question_imports_batch_status_created_id", "batch_id", "status", "created_at", "id"),
        Index("ix_question_imports_answer_status", "answer_status"),
        Index("ix_question_imports_source_order", "batch_id", "source_image_seq", "source_order_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    subject_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("subjects.id"), nullable=True, index=True
    )

    subject_ref = relationship("Subject", back_populates="question_imports", lazy="selectin")
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

    # ── 导入审核定位与答案状态增强字段（2026-07） ──
    # 原始题号（如 "12"、"12-1"、"三"）
    source_question_no: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # 原始题号完整标签（如 "12."、"12、"）
    source_question_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 批量图片导入时，该题来自第几张图片（从 1 开始）
    source_image_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 来源图片文件名
    source_image_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # PDF 或文档中的起始 / 结束页码
    source_page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 同一批次内的稳定顺序索引
    source_order_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 原始题目文本预览（保留题号，如 "12.这是题干……"）
    raw_text_preview: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 答案状态：missing / imported / ai_filled / manual_filled / manual_verified / abnormal
    answer_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # 答案来源：ocr / parser / ai / manual / unknown
    answer_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 答案识别或 AI 补全的置信度
    answer_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 审核优先级：越高越优先
    review_priority: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
