"""Start HTTP scheduler components with caller-owned references and policy."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.services.outbox_queue_adapter import build_outbox_enqueue

StartupFailureReporter = Callable[[str, Exception, bool], None]


@dataclass
class HttpSchedulerTasks:
    scheduler_heartbeat_task: asyncio.Task | None = None
    cleanup_task: asyncio.Task | None = None
    staging_cleanup_task: asyncio.Task | None = None
    export_processor_task: asyncio.Task | None = None
    export_cleanup_task: asyncio.Task | None = None
    outbox_dispatcher_task: asyncio.Task | None = None
    outbox_reconciler_task: asyncio.Task | None = None


def _create_periodic_tasks(tasks: HttpSchedulerTasks, logger: logging.Logger) -> None:
    from app.services.runtime_periodic_tasks import (
        run_export_cleanup,
        run_export_processor_loop,
        run_staging_cleanup,
        run_token_cleanup,
    )

    tasks.cleanup_task = asyncio.create_task(run_token_cleanup(), name="token-cleanup")
    tasks.staging_cleanup_task = asyncio.create_task(run_staging_cleanup(), name="staging-cleanup")
    tasks.export_processor_task = asyncio.create_task(
        run_export_processor_loop(logger), name="export-processor")
    tasks.export_cleanup_task = asyncio.create_task(run_export_cleanup(), name="export-cleanup")


async def _create_outbox_tasks(tasks: HttpSchedulerTasks, logger: logging.Logger) -> None:
    from app.services.outbox_service import run_outbox_dispatcher, run_outbox_reconciler
    from app.services.task_queue_service import task_queue

    enqueue = build_outbox_enqueue(task_queue)  # uses module-level import
    tasks.outbox_dispatcher_task = asyncio.create_task(
        run_outbox_dispatcher(enqueue), name="outbox-dispatcher")
    tasks.outbox_reconciler_task = asyncio.create_task(
        run_outbox_reconciler(), name="outbox-reconciler")
    logger.info("Outbox dispatcher + reconciler started")


async def start_http_scheduler_tasks(
    tasks: HttpSchedulerTasks, production_mode: bool, logger: logging.Logger,
    report_failure: StartupFailureReporter,
) -> None:
    """Start scheduler services and publish each task reference immediately."""
    try:
        from app.services.system_task_service import run_scheduler_heartbeat

        tasks.scheduler_heartbeat_task = asyncio.create_task(
            run_scheduler_heartbeat(), name="scheduler-heartbeat")
    except Exception as e:
        report_failure("Scheduler heartbeat", e, production_mode)

    try:
        from app.services.runtime_scheduler_startup import start_audit_cleanup_scheduler

        await start_audit_cleanup_scheduler(logger)
    except Exception as e:
        report_failure("Audit log cleanup scheduler", e, production_mode)

    try:
        from app.services.runtime_scheduler_startup import (
            start_recommendation_metrics_scheduler,
        )

        await start_recommendation_metrics_scheduler(logger)
    except Exception as e:
        report_failure("Recommendation metrics scheduler", e, production_mode)

    _create_periodic_tasks(tasks, logger)

    try:
        await _create_outbox_tasks(tasks, logger)
    except Exception as e:
        logger.warning("Outbox dispatcher start failed (non-fatal): %s", e)
