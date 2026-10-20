"""Role-specific readiness without importing the HTTP application."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger("postgraduate-ai")


def _check_scheduler_dependencies(settings: "Settings") -> bool:
    # Check audit log cleanup scheduler running (if enabled)
    try:
        from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler

        if (
            settings.AUDIT_LOG_CLEANUP_ENABLED
            and not audit_log_cleanup_scheduler._running
        ):
            logger.warning("role_deps: audit log cleanup scheduler not running")
            return False
    except ImportError:
        logger.warning("role_deps: audit_cleanup_scheduler import failed")
        return False
    except Exception as e:
        logger.warning("role_deps: audit cleanup scheduler check error: %s", e)
        return False

    try:
        from app.services.recommendation_metrics_scheduler import (
            recommendation_metrics_scheduler,
        )

        if (
            settings.RECOMMENDATION_METRICS_AGG_ENABLED
            and not recommendation_metrics_scheduler._running
        ):
            logger.warning(
                "role_deps: recommendation metrics scheduler not running"
            )
            return False
    except ImportError:
        logger.warning("role_deps: recommendation_metrics_scheduler import failed")
        return False
    except Exception as e:
        logger.warning(
            "role_deps: recommendation metrics scheduler check error: %s", e
        )
        return False

    return True


async def check_role_dependencies(settings: "Settings") -> bool:
    """Check OCR isolation, worker draining and enabled scheduler loops by role."""
    role = settings.PROCESS_ROLE
    from app.core.ocr_isolation import (
        is_restricted_ocr_environment,
        loaded_local_ocr_modules,
    )

    is_cloud = is_restricted_ocr_environment()

    if role == "web":
        if is_cloud and loaded_local_ocr_modules():
            logger.warning(
                "role_deps: cloud web role detected banned OCR modules in sys.modules"
            )
            return False
        return True

    if role in {"worker", "all"}:
        # Draining check
        try:
            from app.services.task_queue_worker import is_draining_v2

            if is_draining_v2():
                logger.warning("role_deps: worker is draining")
                return False
        except Exception:
            pass

        # Cloud worker must not use local_process backend
        if is_cloud:
            exec_backend = (settings.OCR_EXECUTION_BACKEND or "").lower()
            if exec_backend == "local_process":
                logger.warning("role_deps: cloud worker with local_process OCR backend")
                return False

        if role != "all":
            return True

    if role in {"scheduler", "all"}:
        return _check_scheduler_dependencies(settings)

    return False  # Unknown role → fail probe
