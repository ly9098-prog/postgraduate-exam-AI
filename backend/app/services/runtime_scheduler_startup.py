"""Shared scheduler service startup with caller-owned logging and failures."""

import logging


async def start_audit_cleanup_scheduler(logger: logging.Logger) -> None:
    from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler

    await audit_log_cleanup_scheduler.start()
    logger.info("Audit log cleanup scheduler started")


async def start_recommendation_metrics_scheduler(logger: logging.Logger) -> None:
    from app.services.recommendation_metrics_scheduler import (
        recommendation_metrics_scheduler,
    )

    await recommendation_metrics_scheduler.start()
    logger.info("Recommendation metrics scheduler started")
