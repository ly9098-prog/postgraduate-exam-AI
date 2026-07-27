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


def _parse_allowed_ids(raw: str) -> set[int]:
    """Parse the comma-separated allowed-user-IDs string.

    Handles spaces, empty strings, duplicates, and non-integer values
    gracefully — any unparsable segment is silently skipped.
    """
    if not raw or not raw.strip():
        return set()
    result: set[int] = set()
    for part in raw.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        try:
            result.add(int(stripped))
        except (ValueError, TypeError):
            logger.warning("Ignoring invalid EXPORT_ALLOWED_USER_IDS entry: %r", stripped)
    return result


def is_user_allowed(user_id: int) -> bool:
    """Check if a user is allowed to create new export tasks."""
    from app.core.config import settings

    if not settings.EXPORT_FEATURE_ENABLED:
        return False
    if settings.EXPORT_ALLOW_ALL_USERS:
        return True
    if settings.EXPORT_ALLOWED_USER_IDS:
        allowed = _parse_allowed_ids(settings.EXPORT_ALLOWED_USER_IDS)
        return user_id in allowed
    return False


def build_capability(user: object) -> ExportCapabilityResponse:
    """Build capability response for the given user.

    The response tells the frontend what the current user can do, without
    leaking internal config or whitelist contents. Configurable constants
    (max question count, retention days) are populated from settings.
    """
    from app.core.config import settings

    uid = getattr(user, "id", 0) or 0
    allowed = is_user_allowed(uid)
    return ExportCapabilityResponse(
        export_enabled=allowed,
        pdf_enabled=allowed,
        docx_enabled=allowed and settings.EXPORT_DOCX_ENABLED,
        websocket_enabled=allowed and settings.EXPORT_WEBSOCKET_ENABLED,
        max_question_count=settings.EXPORT_MAX_QUESTIONS,
        retention_days=_get_retention_days(),
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
    """Raise if the user is not allowed to create export tasks.

    Returns different error codes depending on the reason:
    - ``feature_disabled`` when the global feature flag is off
    - ``user_not_allowed`` when the user is not on the whitelist
    """
    from app.core.config import settings

    if not settings.EXPORT_FEATURE_ENABLED:
        logger.info(
            "export_capability_checked",
            extra={"user_id": user_id, "allowed": False, "reason": "feature_disabled"},
        )
        raise_export_error(403, ExportErrorCode.FEATURE_DISABLED, "导出功能已关闭")
    if not is_user_allowed(user_id):
        logger.info(
            "export_capability_checked",
            extra={"user_id": user_id, "allowed": False, "reason": "user_not_allowed"},
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


def validate_export_range(range_type: str, selected_ids: list[int] | None, count: int) -> None:
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
