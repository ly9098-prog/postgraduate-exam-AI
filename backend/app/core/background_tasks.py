"""Background task registry for lifecycle-managed asyncio tasks.

Provides a centralized registry for background ``asyncio.Task`` references so
that the lifespan shutdown code can cancel all tracked tasks cleanly.

Usage::

    from app.core.background_tasks import create_background_task

    # Instead of: asyncio.create_task(some_coro())
    task = create_background_task(some_coro(), name="my-worker")

    # All tracked tasks are cancelled during shutdown via cancel_all_tasks().
    # Individual tasks are auto-removed from the registry on completion via
    # add_done_callback, so the set doesn't grow unboundedly.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("postgraduate-ai.background-tasks")

_background_tasks: set[asyncio.Task] = set()


def create_background_task(
    coro,
    *,
    name: str | None = None,
) -> asyncio.Task:
    """Create a tracked background task.

    The task is registered in a global set and automatically removed
    when it completes (via ``add_done_callback``).

    Returns the created task.
    """
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    logger.debug(
        "Background task %s registered (total=%d)",
        name or task.get_name(),
        len(_background_tasks),
    )
    return task


async def cancel_all_tasks(timeout: float = 30.0) -> None:
    """Cancel all tracked background tasks and wait for them to complete.

    Each task is individually cancelled and awaited with a per-task timeout.
    Tasks that don't stop within the timeout are logged as warnings.
    """
    if not _background_tasks:
        logger.debug("No background tasks to cancel")
        return

    task_list = list(_background_tasks)
    _background_tasks.clear()

    logger.info("Cancelling %d background tasks", len(task_list))
    for task in task_list:
        if task.done():
            continue

        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
            logger.info("Background task %s: completed after cancel", task.get_name())
        except asyncio.CancelledError:
            logger.info("Background task %s: cancelled", task.get_name())
        except TimeoutError:
            logger.warning(
                "Background task %s: did not stop within %ss grace period",
                task.get_name(),
                timeout,
            )
        except Exception as e:
            logger.warning(
                "Background task %s: error during cancel: %s", task.get_name(), e
            )
