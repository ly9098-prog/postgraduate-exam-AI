"""
Database-backed OCR job model — control plane for thin production server and the legacy local OCR worker.

Design:
- String primary key (UUID) so IDs are globally unique between server and worker.
- Status values defined in pipeline_enums.OCRJobStatus — use the enum, not raw strings.
- Lease fields for atomic worker claim: lease_owner, lease_token_hash, lease_expires_at.
- Idempotency via unique constraint on request_id and complete_idempotency_key.
- Retry tracking via attempt_count, max_attempts, next_retry_at, last_error_code/message.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm_base import Base
from app.models.pipeline_enums import OCRJobStatus


class OCRJob(Base):
    __tablename__ = "ocr_jobs"

    __table_args__ = (
        UniqueConstraint("request_id", name="uq_ocr_jobs_request_id"),
        UniqueConstraint("complete_idempotency_key", name="uq_ocr_jobs_complete_key"),
        Index("ix_ocr_jobs_claim", "status", "priority", "next_retry_at", "created_at"),
        Index("ix_ocr_jobs_lease_expires_at", "lease_expires_at"),
        Index("ix_ocr_jobs_document_sha256", "document_sha256"),
    )

    # ── Identity ─────────────────────────────────────────
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # ── Status ───────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=OCRJobStatus.PENDING.value, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Input ────────────────────────────────────────────
    input_artifact_key: Mapped[str] = mapped_column(String(256), nullable=False)
    input_mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    input_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Output ───────────────────────────────────────────
    output_artifact_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    output_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Lease ────────────────────────────────────────────
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── Retry ────────────────────────────────────────────
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Fingerprint ──────────────────────────────────────
    pipeline_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    required_document_ir_schema: Mapped[str] = mapped_column(
        String(16), nullable=False, default="1.0"
    )
    worker_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Idempotency ──────────────────────────────────────
    complete_idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    # ── Timestamps ───────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
