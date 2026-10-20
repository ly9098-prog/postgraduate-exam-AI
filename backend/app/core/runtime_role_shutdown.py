"""Stop role-specific queue and scheduler protocols without app assembly."""

import logging

logger = logging.getLogger("postgraduate-ai")


async def drain_queue_for_role(role: str) -> None:
    if role in ("worker", "all"):
        try:
            from app.services.task_queue_worker import graceful_shutdown_v2

            await graceful_shutdown_v2()
        except Exception as e:
            logger.warning("v2 Graceful shutdown failed: %s", e)

        try:
            from app.services.task_queue_worker import stop_reaper_v2

            await stop_reaper_v2()
        except Exception as e:
            logger.warning("Reaper v2 stop failed: %s", e)
    else:
        # Non-worker roles still drain if any v1 tasks are active
        try:
            from app.services.task_queue_worker import set_draining_v2

            await set_draining_v2()
        except Exception as e:
            logger.warning("set_draining_v2 failed: %s", e)


async def stop_role_services(role: str) -> None:
    if role in ("scheduler", "all"):
        try:
            from app.services.audit_cleanup_scheduler import (
                audit_log_cleanup_scheduler,
            )

            await audit_log_cleanup_scheduler.stop()
            logger.info("Audit log cleanup scheduler stopped")
        except Exception as e:
            logger.warning("Audit log cleanup scheduler stop error: %s", e)

        try:
            from app.services.recommendation_metrics_scheduler import (
                recommendation_metrics_scheduler,
            )

            await recommendation_metrics_scheduler.stop()
            logger.info("Recommendation metrics scheduler stopped")
        except Exception as e:
            logger.warning("Recommendation metrics scheduler stop error: %s", e)

    # 4b. Stop AI prewarm worker (runs in worker role, not scheduler)
    if role in ("worker", "all"):
        try:
            from app.services.ai_prewarm_worker import stop_worker

            await stop_worker()
            logger.info("AI prewarm worker stopped")
        except Exception as e:
            logger.warning("AI prewarm worker stop error: %s", e)
