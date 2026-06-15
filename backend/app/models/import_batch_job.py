"""批量导题任务模型（多图片 / 未来 PDF 拆页复用）。

设计目标：在不改动现有单图 OCR → AI 解析 → 待审核流水线的前提下，
把「一次批量任务」整体状态（ImportBatchJob）和「每张图片」的执行结果
（ImportBatchJobItem）落到 DB，用于：

1. 队列模式下的进度查询（总数 / 已完成 / 处理中 / 等待中）；
2. 单张图片失败隔离与日志记录，不影响整批继续；
3. 缓存 OCR 原始文本（ocr_raw_text），AI 解析失败 / Prompt 调整后可
   直接基于缓存文本重新解析，无需再次 OCR；
4. 进程重启后仍可查询历史任务。

每张图片走「自己独立的导入流水线 → 自己独立的 review batch」，因此
review_service.submit_to_review 的失败清理（按 batch_id 删除）天然只影响
单张图片，绝不会误删同批其它图片已写入的待审核题目。
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ImportBatchJob(Base):
    __tablename__ = "import_batch_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # "image" 现已支持；预留 "pdf"（PDF 拆页后复用同一批量流水线）。
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="image")
    subject: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # queued / running / completed / failed
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ImportBatchJobItem(Base):
    __tablename__ = "import_batch_job_items"
    __table_args__ = (
        UniqueConstraint("job_id", "seq", name="uq_batch_job_items_job_seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("import_batch_jobs.job_id"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # pending / processing / succeeded / failed
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    # OCR 原始文本缓存：后续 AI 解析失败 / Prompt 调整可直接复用，免重复 OCR。
    ocr_raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 单张图片对应的 review batch（review_service 内部生成的 REVIEW_xxx）。
    review_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pipeline_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
