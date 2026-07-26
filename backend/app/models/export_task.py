"""Export task and snapshot ORM models for the wrong-questions export feature."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ExportTask(Base):
    """An export task for generating a PDF (future: DOCX) from wrong questions.

    State machine:
        pending → processing → completed
          ↓           ↓
        expired     failed → pending (retry creates new task)
          ↓
        completed → expired (via cleanup scheduler)

    Zombie recovery: tasks stuck in ``processing`` for longer than
    ``EXPORT_PROCESSING_TIMEOUT_SEC`` without heartbeat can be reclaimed
    by the processor (status → failed, retryable).
    """

    __tablename__ = "export_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── Status & format ──
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    file_format: Mapped[str] = mapped_column(String(10), nullable=False, default="pdf")

    # ── Export config ──
    range_type: Mapped[str] = mapped_column(String(20), nullable=False)
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    selected_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    show_date: Mapped[bool] = mapped_column(default=True)
    export_date: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_by: Mapped[str] = mapped_column(String(32), nullable=False, default="newest")
    group_by: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    answer_position: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none"
    )
    analysis_position: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none"
    )
    space_style: Mapped[str] = mapped_column(
        String(16), nullable=False, default="standard"
    )

    # ── Counts & results ──
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skip_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skip_reasons: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── File info ──
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Snapshot & lineage ──
    snapshot_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    source_task_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("export_tasks.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )

    # ── Processing metadata ──
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generator_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # ── Timestamps ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ExportSnapshot(Base):
    """Stable snapshot of exported questions and config for re-export.

    Created before PDF generation begins. Contains the resolved question
    order, full question data, and export configuration. Independent of
    the original questions — deletion / modification of source questions
    does not affect re-export from this snapshot.
    """

    __tablename__ = "export_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    data_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
