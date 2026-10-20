"""Managed background task ownership without process configuration or resources."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable

logger = logging.getLogger("postgraduate-ai.bootstrap")


class ManagedTask:
    """A managed ``asyncio.Task`` with auto-exception-logging and cancellation.

    Usage::

        mt = ManagedTask.create(coro, name="my-task")
        ...
        mt.cancel()
        await mt.wait(timeout=30)
    """

    def __init__(self, task: asyncio.Task, name: str) -> None:
        self._task = task
        self._name = name
        self._task.add_done_callback(self._on_done)

    @property
    def name(self) -> str:
        return self._name

    @staticmethod
    def _on_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(
                "Background task %s failed: %s: %s",
                task.get_name(),
                type(exc).__name__,
                exc,
            )

    def cancel(self) -> None:
        if not self._task.done():
            self._task.cancel()

    async def wait(self, timeout: float = 30) -> None:
        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except asyncio.CancelledError:
            pass
        except TimeoutError:
            logger.warning(
                "Managed task %s: did not stop within %ss grace", self._name, timeout
            )
        except Exception as exc:
            logger.warning(
                "Managed task %s: %s: %s", self._name, type(exc).__name__, exc
            )

    @classmethod
    def create(cls, coro: Awaitable, name: str) -> ManagedTask:
        """Create a managed background task from a coroutine."""
        task = asyncio.create_task(coro, name=name)
        return cls(task, name)


class TaskRegistry:
    """Registry of managed background tasks for ordered shutdown."""

    def __init__(self) -> None:
        self._tasks: list[ManagedTask] = []

    def register(self, task: ManagedTask) -> None:
        self._tasks.append(task)

    def create(self, coro: Awaitable, name: str) -> ManagedTask:
        mt = ManagedTask.create(coro, name)
        self._tasks.append(mt)
        return mt

    def cancel_all(self) -> list[ManagedTask]:
        running = [t for t in self._tasks if not t._task.done()]
        for t in running:
            t.cancel()
        return running

    async def wait_all(self, timeout: float = 30) -> None:
        """Cancel all tasks and wait once for the whole registry.

        Waiting task-by-task multiplied shutdown latency by the number of
        registered loops (for example, six tasks × 30 seconds).  A single
        bounded wait keeps the process shutdown deadline predictable.
        """
        running = self.cancel_all()
        if not running:
            return

        tasks = {managed._task for managed in running}
        _done, pending = await asyncio.wait(tasks, timeout=timeout)
        if pending:
            names = sorted(task.get_name() for task in pending)
            logger.warning(
                "Managed tasks did not stop within %ss grace: %s",
                timeout,
                names,
            )
            for task in pending:
                task.cancel()

    def __len__(self) -> int:
        return len(self._tasks)
