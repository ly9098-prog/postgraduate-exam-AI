"""Unified capability service for export feature flag and whitelist checks.

All creation-adjacent endpoints (capabilities, preview-count, create, retry,
re-export, WebSocket) must use these helpers so the access-control rules
are defined in one place.

Rule semantics (in order):
1. ``EXPORT_FEATURE_ENABLED=False`` → no one can create.
2. ``EXPORT_ALLOW_ALL_USERS=True`` → everyone can create.
3. ``EXPORT_ALLOWED_USER_IDS`` is non-empty and user_id is in it → allowed.
4. ``EXPORT_ALLOWED_USER_IDS`` is non-empty and user_id is NOT in it → blocked.
5. Both are empty/default → blocked (safe default).
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from app.schemas.export_task import ExportCapabilityResponse, ExportErrorCode

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# Pure helpers (no DB dependency)
# ═══════════════════════════════════════════════════


def is_user_allowed(user_id: int) -> bool:
    """Check if a user is allowed to create new export tasks."""
    from app.core.config import settings

    if not settings.EXPORT_FEATURE_ENABLED:
        return False
    if settings.EXPORT_ALLOW_ALL_USERS:
        return True
    if settings.EXPORT_ALLOWED_USER_IDS:
        allowed = {
            int(x.strip())
            for x in settings.EXPORT_ALLOWED_USER_IDS.split(",")
            if x.strip()
        }
        return user_id in allowed
    return False


def build_capability(user: object) -> ExportCapabilityResponse:
    """Build capability response for the given user.

    The response tells the frontend what the current user can do, without
    leaking internal config or whitelist contents.
    """
    from app.core.config import settings

    uid = getattr(user, "id", 0) or 0
    allowed = is_user_allowed(uid)
    return ExportCapabilityResponse(
        export_enabled=allowed,
        pdf_enabled=allowed,
        docx_enabled=allowed and settings.EXPORT_DOCX_ENABLED,
        websocket_enabled=allowed and settings.EXPORT_WEBSOCKET_ENABLED,
    )


# ═══════════════════════════════════════════════════
# Assertion helpers (raise HTTPException on failure)
# ═══════════════════════════════════════════════════


def raise_export_error(
    status_code: int, error_code: ExportErrorCode, message: str,
):
    """Raise a structured ``HTTPException``.

    The response body is ``{"message": ..., "error_code": ...}``.
    The frontend ``api.js`` extracts ``message`` for display.
    """
    raise HTTPException(
        status_code=status_code,
        detail={"message": message, "error_code": error_code.value},
    )


def ensure_export_allowed(user_id: int):
    """Raise if the user is not allowed to create export tasks."""
    if not is_user_allowed(user_id):
        logger.info(
            "export_capability_checked",
            extra={"user_id": user_id, "allowed": False},
        )
        raise_export_error(403, ExportErrorCode.USER_NOT_ALLOWED, "导出功能未开放")


def ensure_format_allowed(file_format: str):
    """Raise if the requested format is disabled."""
    if file_format != "pdf":
        from app.core.config import settings

        if file_format == "docx" and not settings.EXPORT_DOCX_ENABLED:
            raise_export_error(403, ExportErrorCode.DOCX_DISABLED, "Word 导出功能已关闭")


def log_capability_check(user_id: int, allowed: bool, **extra):
    """Log a capability check event."""
    logger.info(
        "export_capability_checked",
        extra={"user_id": user_id, "allowed": allowed, **extra},
    )
