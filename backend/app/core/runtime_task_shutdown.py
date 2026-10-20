"""Cancel lifecycle-owned tasks in order and wait with one shared grace period."""

import asyncio
import logging
from collections.abc import Sequence

logger = logging.getLogger("postgraduate-ai")


async def cancel_and_wait_runtime_tasks(
    tasks: Sequence[tuple[str, asyncio.Task | None]],
) -> None:
    shutdown_tasks = []
    for name, task in tasks:
        if task and not task.done():
            task.cancel()
            shutdown_tasks.append((name, task))
    if shutdown_tasks:
        task_names = {task: name for name, task in shutdown_tasks}
        done, pending = await asyncio.wait(task_names, timeout=30)
        for task in done:
            name = task_names[task]
            if task.cancelled():
                logger.info("Task %s: cancelled", name)
                continue
            try:
                exc = task.exception()
            except asyncio.CancelledError:
                logger.info("Task %s: cancelled", name)
                continue
            if exc is None:
                logger.info("Task %s: completed after cancel", name)
            else:
                logger.warning("Task %s: cancel error: %s", name, exc)
        for task in pending:
            logger.warning(
                "Task %s: did not stop within shared 30s grace period",
                task_names[task],
            )
            task.cancel()
