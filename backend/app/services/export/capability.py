"""Export capability and validation helpers.

Export is available to every authenticated user.  This module only exposes
format capabilities and operational limits; it does not perform audience
rollout checks.
"""

from __future__ import annotations

import logging

from app.schemas.export_task import ExportCapabilityResponse, ExportErrorCode
from app.services.export.exceptions import (
    ExportDomainError,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# Capability helpers (no DB dependency)
# ═══════════════════════════════════════════════════


def build_capability(user: object) -> ExportCapabilityResponse:
    """Build the globally available export capability response."""
    from app.core.config import settings

    return ExportCapabilityResponse(
        export_enabled=True,
        pdf_enabled=True,
        docx_enabled=settings.EXPORT_DOCX_ENABLED,
        websocket_enabled=settings.EXPORT_WEBSOCKET_ENABLED,
        max_question_count=settings.EXPORT_MAX_QUESTIONS,
        retention_days=_get_retention_days(),
        reason_code=None,
        message=None,
    )


def _get_retention_days() -> int:
    """Return the configured retention period in days.

    Looks for a setting in order of preference:
    1. EXPORT_RETENTION_DAYS (if defined)
    2. Falls back to 7 days
    """
    from app.core.config import settings

    return getattr(settings, "EXPORT_RETENTION_DAYS", 7)


# ═══════════════════════════════════════════════════
# Validation helpers (raise HTTPException on failure)
# ═══════════════════════════════════════════════════


def raise_export_error(
    status_code: int,
    error_code: ExportErrorCode,
    message: str,
):
    """Raise a structured ``ExportDomainError``.

    Since ``ExportDomainError`` extends ``HTTPException``, FastAPI converts it
    automatically to an HTTP response with body
    ``{"detail": {"message": ..., "error_code": ...}}``.
    The frontend ``api.js`` extracts ``message`` for display.
    """
    raise ExportDomainError(
        status_code=status_code,
        error_code=error_code,
        message=message,
    )


def ensure_format_allowed(file_format: str):
    """Raise if the requested format is disabled."""
    if file_format != "pdf":
        from app.core.config import settings

        if file_format == "docx" and not settings.EXPORT_DOCX_ENABLED:
            raise_export_error(
                403, ExportErrorCode.DOCX_DISABLED, "Word 导出功能已关闭"
            )


def log_export_config_on_startup():
    """Log the globally enabled export configuration at startup.

    Output format::

        export_access_config feature_enabled=true access_mode=all docx_enabled=true websocket_enabled=true
    """
    from app.core.config import settings

    logger.info(
        "export_access_config feature_enabled=true access_mode=all "
        "docx_enabled=%s websocket_enabled=%s",
        settings.EXPORT_DOCX_ENABLED,
        settings.EXPORT_WEBSOCKET_ENABLED,
    )


def validate_export_range(
    range_type: str, selected_ids: list[int] | None, count: int
) -> None:
    """Validate the export range before creating a task.

    Raises ``HTTPException`` if the range is invalid:
    - 0 questions → ``no_questions``
    - count exceeds max → ``too_many_questions``

    The max count comes from settings.EXPORT_MAX_QUESTIONS.
    """
    from app.core.config import settings

    max_count = settings.EXPORT_MAX_QUESTIONS

    if count == 0:
        raise_export_error(400, ExportErrorCode.NO_QUESTIONS, "没有可导出的错题")
    if count > max_count:
        raise_export_error(
            400,
            ExportErrorCode.TOO_MANY_QUESTIONS,
            f"单次最多导出 {max_count} 道，当前共 {count} 道，请调整导出范围。",
        )
