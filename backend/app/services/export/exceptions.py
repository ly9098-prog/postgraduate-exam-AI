"""Unified export domain exceptions with structured error codes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.schemas.export_task import ExportErrorCode


class ExportDomainError(HTTPException):
    """Base exception for all export domain errors.

    Contains:
    - status_code: HTTP status code
    - error_code: ExportErrorCode enum value
    - message: User-safe message (returned to frontend)
    - context: Internal-only extra context (logged, never sent to client)

    Extends HTTPException so FastAPI handles it automatically without extra
    exception-handler registration.
    """

    def __init__(
        self,
        status_code: int = 400,
        error_code: ExportErrorCode = ExportErrorCode.SERVICE_UNAVAILABLE,
        message: str = "导出服务异常",
        context: dict[str, Any] | None = None,
    ):
        self.error_code = error_code
        self.message = message
        self.context = context or {}
        super().__init__(
            status_code=status_code,
            detail={"message": self.message, "error_code": self.error_code.value},
        )


class ExportValidationError(ExportDomainError):
    """Validation errors (400) — invalid input, too many questions, etc."""

    def __init__(self, error_code: ExportErrorCode, message: str, **context):
        super().__init__(status_code=400, error_code=error_code, message=message, context=context)


class ExportPermissionError(ExportDomainError):
    """Permission errors (403) — feature disabled, user not allowed, etc."""

    def __init__(self, error_code: ExportErrorCode, message: str, **context):
        super().__init__(status_code=403, error_code=error_code, message=message, context=context)
