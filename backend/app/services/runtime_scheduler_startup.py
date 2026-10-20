"""Scheduler service and task startup with caller-owned logging and failures."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.outbox_queue_adapter import build_outbox_enqueue

if TYPE_CHECKING:
    from app.core.runtime_task_registry import TaskRegistry


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


def start_scheduler_outbox_tasks(registry: TaskRegistry, logger: logging.Logger) -> None:
    try:
        from app.services.outbox_service import (
            run_outbox_dispatcher,
            run_outbox_reconciler,
        )
        from app.services.task_queue_service import task_queue

        _enqueue_from_outbox = build_outbox_enqueue(task_queue)

        registry.create(
            run_outbox_dispatcher(_enqueue_from_outbox), "outbox-dispatcher"
        )
        registry.create(run_outbox_reconciler(), "outbox-reconciler")
        logger.info("Outbox dispatcher + DB/Redis reconciler started")
    except Exception as e:
        logger.warning("Outbox init failed (non-fatal): %s", e)


def start_answer_projection_task(registry: TaskRegistry, logger: logging.Logger) -> None:
    try:
        from app.services.practice.projection_reconciliation_service import (
            run_answer_projection_reconciler,
        )

        registry.create(
            run_answer_projection_reconciler(),
            "answer-projection-reconciler",
        )
        logger.info("Answer projection business reconciler started")
    except Exception as e:
        logger.warning("Answer projection reconciler init failed (non-fatal): %s", e)


def start_scheduler_health_task(registry: TaskRegistry, logger: logging.Logger) -> None:
    try:
        from app.services.task_observability_service import run_task_health_monitor

        registry.create(run_task_health_monitor(), "async-task-health-monitor")
        logger.info("Async task health monitor started")
    except Exception as e:
        logger.warning("Async task health monitor init failed (non-fatal): %s", e)
