"""Export task Pydantic schemas — request validation, response models, and enums."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ═══════════════════════════════════════════════════
# Enums (central state definitions — single source)
# ═══════════════════════════════════════════════════


class ExportTaskStatus(StrEnum):
    """Legal state transitions are enforced by the service layer."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"

    # Allowed transitions:
    #   pending     → processing  (processor claims)
    #   processing  → completed   (success)
    #   processing  → failed      (error / timeout)
    #   failed      → pending     (retry — creates new task)
    #   pending     → failed      (processor gives up)
    #   completed   → expired     (cleanup scheduler)
    #   pending     → expired     (cleanup scheduler)
    #   failed      → expired     (cleanup scheduler)


class ExportFileFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"


class ExportRangeType(StrEnum):
    ALL = "all"
    FILTERED = "filtered"
    SELECTED = "selected"


class ExportSortBy(StrEnum):
    NEWEST = "newest"
    OLDEST = "oldest"
    ORIGINAL = "original"
    RANDOM = "random"
    KNOWLEDGE_POINT = "knowledge_point"
    QUESTION_TYPE = "question_type"


class ExportErrorCode(StrEnum):
    """Structured error codes for export API responses."""
    FEATURE_DISABLED = "feature_disabled"
    USER_NOT_ALLOWED = "user_not_allowed"
    DOCX_DISABLED = "docx_disabled"
    TOO_MANY_QUESTIONS = "too_many_questions"
    NO_QUESTIONS = "no_questions"
    TOO_MANY_CONCURRENT = "too_many_concurrent"
    TASK_NOT_FOUND = "task_not_found"
    ACCESS_DENIED = "access_denied"
    FILE_NOT_READY = "file_not_ready"
    FILE_NOT_FOUND = "file_not_found"
    FILE_EXPIRED = "file_expired"
    GENERATION_FAILED = "generation_failed"
    TASK_TIMEOUT = "task_timeout"
    STORAGE_FAILED = "storage_failed"
    SERVICE_UNAVAILABLE = "service_unavailable"
    TASK_ALREADY_EXISTS = "task_already_exists"


class ExportGroupBy(StrEnum):
    NONE = "none"
    SUBJECT = "subject"
    CHAPTER = "chapter"
    KNOWLEDGE_POINT = "knowledge_point"
    QUESTION_TYPE = "question_type"


class ExportAnswerPosition(StrEnum):
    NONE = "none"
    AFTER_QUESTION = "after_question"
    AT_END = "at_end"


class ExportSpaceStyle(StrEnum):
    COMPACT = "compact"
    STANDARD = "standard"
    SPACIOUS = "spacious"


# ═══════════════════════════════════════════════════
# Request schemas
# ═══════════════════════════════════════════════════


class ExportConfigRequest(BaseModel):
    """Core export configuration — shared by preview + create."""

    range_type: ExportRangeType
    filters: dict[str, Any] | None = None  # {subject, error_type, topic}
    selected_ids: list[int] | None = Field(None, max_length=100)
    title: str = Field("", max_length=120)
    show_date: bool = True
    export_date: str = ""  # YYYY-MM-DD, empty = today
    sort_by: ExportSortBy = ExportSortBy.NEWEST
    group_by: ExportGroupBy = ExportGroupBy.NONE
    answer_position: ExportAnswerPosition = ExportAnswerPosition.NONE
    analysis_position: ExportAnswerPosition = ExportAnswerPosition.NONE
    space_style: ExportSpaceStyle = ExportSpaceStyle.STANDARD

    @field_validator("title")
    @classmethod
    def sanitize_title(cls, v: str) -> str:
        return v.strip()[:120]

    @field_validator("export_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if v and not v.strip():
            return ""
        # Simple YYYY-MM-DD format check
        if v:
            import re
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", v.strip()):
                raise ValueError("日期格式必须为 YYYY-MM-DD")
        return v.strip() if v else ""

    @field_validator("selected_ids")
    @classmethod
    def deduplicate_ids(cls, v: list[int] | None) -> list[int] | None:
        if v is not None:
            return list(dict.fromkeys(v))
        return v


class PreviewCountRequest(ExportConfigRequest):
    """Same fields — used to preview the number of questions in a range."""


class CreateExportTaskRequest(ExportConfigRequest):
    """Extended with format selection for task creation."""
    file_format: str = "pdf"

    @field_validator("file_format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        if v not in ("pdf", "docx"):
            raise ValueError(f"不支持的导出格式: {v}")
        return v


# ═══════════════════════════════════════════════════
# Response schemas
# ═══════════════════════════════════════════════════


class PreviewCountResponse(BaseModel):
    count: int
    range_type: str


class ExportTaskResponse(BaseModel):
    id: int
    status: str
    file_format: str
    file_name: str
    file_size: int | None = None
    title: str
    range_type: str
    sort_by: str
    group_by: str
    total_count: int
    success_count: int | None = None
    skip_count: int | None = None
    error_message: str | None = None
    status_reason: str | None = None
    status_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    source_task_id: int | None = None
    retry_count: int = 0
    generator_version: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DownloadInfoResponse(BaseModel):
    """Download information — abstracts local streaming vs COS signed URL."""
    url: str | None = None
    method: str = "stream"  # "stream" | "signed_url"
    file_name: str
    file_size: int | None = None
    content_type: str = "application/pdf"  # overridden per format by the API handler


class ExportRecordListItem(BaseModel):
    """Compact view for the records list."""
    id: int
    status: str
    file_format: str
    file_name: str
    file_size: int | None = None
    total_count: int
    success_count: int | None = None
    skip_count: int | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    expires_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ExportCapabilityResponse(BaseModel):
    """Per-user export capability — returned by the capabilities endpoint.

    Does NOT leak internal config or whitelist contents.
    When ``export_enabled`` is ``False``, ``reason_code`` and ``message``
    provide a diagnostic hint for the frontend (no sensitive info leaked).
    """
    export_enabled: bool = False
    pdf_enabled: bool = False
    docx_enabled: bool = False
    websocket_enabled: bool = False
    max_question_count: int = 100
    retention_days: int = 7
    reason_code: str | None = None
    message: str | None = None
