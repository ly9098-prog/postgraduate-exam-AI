"""OCR Job schemas — API request/response models for the control plane."""

from __future__ import annotations
from app.schemas.base import BaseModel

from datetime import datetime

from pydantic import ConfigDict, Field


class OCRJobCreate(BaseModel):
    """Request to create a new OCR job."""
    request_id: str = Field(..., min_length=1, max_length=64)
    document_id: str = Field(..., min_length=1, max_length=64)
    document_sha256: str = Field(..., min_length=64, max_length=64)
    input_artifact_key: str = Field(..., min_length=1, max_length=256)
    input_mime_type: str = Field(..., min_length=1, max_length=64)
    input_size_bytes: int = Field(..., ge=1)
    input_page_count: int | None = Field(None, ge=1)
    pipeline_fingerprint: str = Field(..., min_length=1, max_length=64)
    required_document_ir_schema: str = Field("1.0", max_length=16)
    priority: int = Field(0, ge=0, le=100)


class OCRJobResponse(BaseModel):
    """OCR job status response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_id: str
    document_id: str
    document_sha256: str
    status: str
    priority: int
    input_artifact_key: str
    input_mime_type: str
    input_size_bytes: int
    input_page_count: int | None = None
    output_artifact_key: str | None = None
    output_sha256: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    last_error_code: str | None = None
    last_error_message: str | None = None
    pipeline_fingerprint: str
    required_document_ir_schema: str
    worker_fingerprint: str | None = None
    model_fingerprint: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class OCRClaimResponse(BaseModel):
    """Response returned when a worker claims a job."""
    job_id: str
    lease_token: str
    lease_expires_at: datetime
    input_artifact_key: str
    input_mime_type: str
    input_size_bytes: int
    input_page_count: int | None = None
    required_document_ir_schema: str
    pipeline_fingerprint: str
    execution_config: dict = Field(default_factory=dict)


class OCRHeartbeatRequest(BaseModel):
    """Worker heartbeat request."""
    lease_token: str


class OCRStartRequest(BaseModel):
    """Worker marks job as started (downloading → running)."""
    lease_token: str
    worker_fingerprint: str | None = None
    model_fingerprint: str | None = None


class OCRCompleteRequest(BaseModel):
    """Worker uploads completed OCR result."""
    lease_token: str
    output_artifact_key: str = Field(..., min_length=1, max_length=256)
    output_sha256: str = Field(..., min_length=64, max_length=64)
    worker_fingerprint: str | None = None
    model_fingerprint: str | None = None
    complete_idempotency_key: str | None = Field(None, max_length=64)


class OCRFailRequest(BaseModel):
    """Worker reports a job failure."""
    lease_token: str
    error_code: str = Field(..., max_length=32)
    error_message: str = Field(default="", max_length=1024)
    is_retryable: bool = True
    worker_fingerprint: str | None = None


class OCRJobListResponse(BaseModel):
    """Paginated list of OCR jobs."""
    items: list[OCRJobResponse]
    total: int
