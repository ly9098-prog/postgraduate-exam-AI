"""Start HTTP worker components with caller-owned task references and policy."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

StartupFailureReporter = Callable[[str, Exception, bool], None]


@dataclass
class HttpWorkerTasks:
    pipeline_worker_task: asyncio.Task | None = None
    reaper_task: asyncio.Task | None = None


async def start_http_worker_tasks(
    tasks: HttpWorkerTasks, production_mode: bool, logger: logging.Logger,
    report_failure: StartupFailureReporter,
) -> None:
    """Publish each task immediately, preserving independent startup failures."""
    try:
        from app.services.task_queue_worker import run_dispatcher_v2

        tasks.pipeline_worker_task = asyncio.create_task(
            run_dispatcher_v2(), name="pipeline-dispatcher-v2"
        )
    except Exception as e:
        report_failure("Pipeline dispatcher v2", e, production_mode)

    try:
        from app.services.task_queue_worker import run_reaper_loop_v2

        tasks.reaper_task = asyncio.create_task(
            run_reaper_loop_v2(), name="task-reaper-v2"
        )
    except Exception as e:
        report_failure("Reaper", e, production_mode)

    # AI prewarm worker uses the durable queue independently of the scheduler.
    try:
        from app.services.ai_prewarm_worker import start_worker

        await start_worker()
        logger.info("AI prewarm worker started")
    except Exception as e:
        report_failure("AI prewarm worker", e, production_mode)
