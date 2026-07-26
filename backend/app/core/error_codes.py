"""Unified error codes for API responses.

All API errors use these codes so clients can reliably distinguish error types.
Internal queue-empty is NOT an HTTP error — it's normal polling behaviour.

Usage::

    from app.core.error_codes import ErrorCode, ApiError

    raise ApiError(
        ErrorCode.QUEUE_UNAVAILABLE,
        message="任务队列暂时不可用",
        retryable=True,
    )
"""

from __future__ import annotations

import uuid
from enum import StrEnum


class ErrorCode(StrEnum):
    """Unified error codes for all API error responses."""

    # ── Queue ──
    QUEUE_EMPTY = "QUEUE_EMPTY"                 # internal only, not an HTTP error
    QUEUE_UNAVAILABLE = "QUEUE_UNAVAILABLE"     # Redis down / unreachable
    QUEUE_FULL = "QUEUE_FULL"                   # capacity limit reached

    # ── Task ──
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_FENCING_REJECTED = "TASK_FENCING_REJECTED"
    TASK_LEASE_LOST = "TASK_LEASE_LOST"
    TASK_CANCELLED = "TASK_CANCELLED"
    TASK_RETRY_EXHAUSTED = "TASK_RETRY_EXHAUSTED"

    # ── Staging ──
    STAGING_OBJECT_MISSING = "STAGING_OBJECT_MISSING"
    STAGING_UNAVAILABLE = "STAGING_UNAVAILABLE"

    # ── Resource ──
    RESOURCE_MEMORY_LOW = "RESOURCE_MEMORY_LOW"
    RESOURCE_DISK_LOW = "RESOURCE_DISK_LOW"
    RESOURCE_QUEUE_FULL = "RESOURCE_QUEUE_FULL"
    RESOURCE_DB_POOL_BUSY = "RESOURCE_DB_POOL_BUSY"

    # ── OCR ──
    OCR_TIMEOUT = "OCR_TIMEOUT"
    OCR_RATE_LIMIT = "OCR_RATE_LIMIT"
    OCR_PROVIDER_ERROR = "OCR_PROVIDER_ERROR"

    # ── AI ──
    AI_TIMEOUT = "AI_TIMEOUT"
    AI_RATE_LIMIT = "AI_RATE_LIMIT"

    # ── Database ──
    DB_UNAVAILABLE = "DB_UNAVAILABLE"
    DB_CONFLICT = "DB_CONFLICT"

    # ── Pipeline ──
    PIPELINE_TIMEOUT = "PIPELINE_TIMEOUT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

    # ── Generic ──
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class ApiError(Exception):
    """Unified API error with structured error code.

    Attributes:
        code: ErrorCode enum member
        message: Human-readable message (Chinese or English)
        retryable: Whether the client should retry
        request_id: Correlation ID for log tracing
        details: Optional additional structured data
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str = "",
        retryable: bool = False,
        request_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message or code.value)
        self.code = code
        self.message = message or code.value
        self.retryable = retryable
        self.request_id = request_id or uuid.uuid4().hex[:12]
        self.details = details or {}

    def to_dict(self) -> dict:
        result: dict = {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "retryable": self.retryable,
                "request_id": self.request_id,
            }
        }
        if self.details:
            result["error"]["details"] = self.details
        return result


# ── Convenience constructors ──


def queue_unavailable(message: str = "任务队列暂时不可用", retry_after: int = 30) -> ApiError:
    return ApiError(
        ErrorCode.QUEUE_UNAVAILABLE,
        message=message,
        retryable=True,
        details={"retry_after": retry_after},
    )


def task_not_found(task_id: str) -> ApiError:
    return ApiError(
        ErrorCode.TASK_NOT_FOUND,
        message=f"任务不存在: {task_id}",
        retryable=False,
    )


def fencing_rejected() -> ApiError:
    return ApiError(
        ErrorCode.TASK_FENCING_REJECTED,
        message="任务已被其他 Worker 接管",
        retryable=False,
    )


def staging_object_missing(object_id: str) -> ApiError:
    return ApiError(
        ErrorCode.STAGING_OBJECT_MISSING,
        message=f"暂存文件不存在: {object_id}",
        retryable=False,
    )


def ocr_timeout(details: dict | None = None) -> ApiError:
    return ApiError(
        ErrorCode.OCR_TIMEOUT,
        message="OCR 识别超时",
        retryable=True,
        details=details,
    )


def ocr_provider_error(details: dict | None = None) -> ApiError:
    return ApiError(
        ErrorCode.OCR_PROVIDER_ERROR,
        message="OCR 服务暂时不可用",
        retryable=True,
        details=details,
    )


def db_unavailable() -> ApiError:
    return ApiError(
        ErrorCode.DB_UNAVAILABLE,
        message="数据库暂时不可用",
        retryable=True,
    )


def review_required(pipeline_id: str) -> ApiError:
    return ApiError(
        ErrorCode.REVIEW_REQUIRED,
        message=f"导入需要人工审核: {pipeline_id}",
        retryable=False,
        details={"pipeline_id": pipeline_id},
    )
