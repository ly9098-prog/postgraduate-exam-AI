"""
Batch image import job models.

Design goals:
- Track overall job status (ImportBatchJob) and per-image results (ImportBatchJobItem).
- Support queue-mode progress queries (total / completed / processing / pending).
- Per-image failure isolation and logging.
- Cache OCR raw text for reparse without re-OCR.
- Process restart survivable query.

Each image gets its own import pipeline -> its own review batch,
so cleanup per batch_id never affects other images in the same job.

Status values defined in app.models.pipeline_enums — use the enum, not raw strings.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ImportBatchJob(Base):
    __tablename__ = "import_batch_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="image")
    subject: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # Status values defined in pipeline_enums.BatchJobStatus
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_event_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # P0-5: merge tracking fields
    merge_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    merged_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    merge_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    merge_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    merge_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ImportBatchJobItem(Base):
    __tablename__ = "import_batch_job_items"
    __table_args__ = (
        UniqueConstraint("job_id", "seq", name="uq_batch_job_items_job_seq"),
        UniqueConstraint("batch_import_id", "image_import_id", name="uq_batch_import_id_image"),
        Index("ix_batch_job_items_job_id_status", "job_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("import_batch_jobs.job_id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    batch_import_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_import_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Status values defined in pipeline_enums.BatchItemStatus
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    ocr_raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    # P0-2: reparse tracking — preserved across reparse attempts
    previous_review_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reparse_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reparse_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reparse_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reparse_config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class BatchJobTraceEvent(Base):
    """
    Append-only trace event log for batch image import jobs.

    Status values defined in pipeline_enums.TraceEventStatus (running|success|failed only).
    Step values defined in pipeline_enums.TraceStep.
    """

    __tablename__ = "batch_job_trace_events"
    __table_args__ = (
        Index("ix_batch_trace_events_job_id_id", "job_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("import_batch_jobs.job_id"), nullable=False, index=True
    )
    item_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_import_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    batch_import_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
