"""HTTP startup diagnostics with explicit configuration and caller logging."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.core.ocr_profile import OCRProfile


def log_http_startup(
    config: Settings, role: str, profile: OCRProfile, logger: logging.Logger,
) -> None:
    """Log the resolved OCR profile and original role-specific component status."""
    logger.info(
        "Starting 2240AI \u2014 env=%s role=%s ocr_profile=%s (gpu=%s, workers=%d, max_pdf_pages=%d)",
        config.APP_ENV,
        role,
        profile.name,
        profile.use_gpu,
        profile.max_workers,
        profile.max_pdf_pages,
    )
    # Explicitly log which components are active per role. Keep ``all`` as a
    # separate branch so diagnostics never claim that its worker/scheduler are
    # disabled when they are actually running.
    if role == "web":
        logger.info(
            "Role=%s: API serving, OCR gateway active (no worker/dispatcher)", role
        )
    elif role == "worker":
        logger.info(
            "Role=%s: pipeline dispatcher, reaper, AI prewarm active (no API)", role
        )
    elif role == "scheduler":
        logger.info(
            "Role=%s: periodic tasks (token, staging, audit, recommendation metrics, "
            "export cleanup) active (no API, no worker)",
            role,
        )
    elif role == "all":
        logger.warning(
            "Role=%s: API + worker + scheduler components active in one process "
            "(development mode). In production, use web/worker/scheduler split.",
            role,
        )


def log_http_export_startup(role: str, config: Settings, logger: logging.Logger) -> None:
    """Report export access configuration and the original processor role policy."""
    try:
        from app.services.export.capability import log_export_config_on_startup

        log_export_config_on_startup()
    except Exception:
        logger.warning("Export config logging failed (non-fatal)", exc_info=True)

    # Log export processor status
    _has_processor = role in ("scheduler", "all")
    _has_redis = bool(config.REDIS_URL)
    if _has_processor:
        logger.info(
            "export_processor_enabled=true process_role=%s redis_available=%s",
            role,
            _has_redis,
        )
    elif role == "web":
        logger.warning(
            "process_role=web export_processor_enabled=false export_processor_mode=external "
            " \u2014 pending export tasks will NOT be processed. "
            "Start a scheduler process (PROCESS_ROLE=scheduler) or use PROCESS_ROLE=all for local dev."
        )
