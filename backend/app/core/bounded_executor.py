"""BoundedExecutor — limited thread-pool executor for async offloading.

All CPU-bound and blocking I/O operations in async code must go through
a BoundedExecutor rather than bare ``asyncio.to_thread()`` (which uses the
unbounded default thread pool).

Features:
- Fixed max_workers with a bounded queue depth
- Atomic admission control: rejects immediately when at capacity
- Per-call timeout (note: timeout cancels the await, not the thread)
- Concurrent-safe metrics (active, queued, rejected, completed, failed, timed_out, cancelled)
- Non-blocking shutdown (cancel_futures=True, does not block the event loop)
"""

from __future__ import annotations

import asyncio
import functools
import time
from concurrent.futures import ThreadPoolExecutor


class ExecutorQueueFullError(RuntimeError):
    """Raised when a BoundedExecutor has no capacity.

    The caller should propagate this to the API layer as a 503 with
    ``Retry-After``.
    """

    def __init__(self, executor_name: str, retry_after: int = 30) -> None:
        self.executor_name = executor_name
        self.retry_after = retry_after
        super().__init__(f"{executor_name}: queue full, retry after {retry_after}s")


class BoundedExecutor:
    """Fixed-capacity executor that rejects rather than queues beyond limit.

    Usage::

        exec = BoundedExecutor("pdf", max_workers=1, max_queued=2, timeout=120)
        result = await exec.run(fn, arg1, arg2)
    """

    def __init__(
        self,
        name: str,
        max_workers: int,
        max_queued: int,
        timeout: float,
    ) -> None:
        self._name = name
        self._max_workers = max_workers
        self._max_queued = max_queued
        self._default_timeout = timeout
        self._capacity = max_workers + max_queued
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=name,
        )
        self._lock = asyncio.Lock()
        self._active = 0
        self._queued = 0
        self._zombie = 0
        self._shutdown = False
        # Metrics — reset on construction
        self._metrics: dict[str, int | float] = {
            "active": 0,
            "queued": 0,
            "rejected": 0,
            "completed": 0,
            "failed": 0,
            "timed_out": 0,
            "cancelled": 0,
            "zombie": 0,
        }

    # ── Public API ──

    async def run(
        self,
        fn,
        *args,
        timeout: float | None = None,
        **kwargs,
    ):
        """Submit *fn(*args, **kwargs)* to the thread pool.

        Raises:
            ExecutorQueueFullError: if at capacity (active + queued >= capacity).
            asyncio.TimeoutError: if the call exceeds *timeout* seconds.
            RuntimeError: if the executor has been shut down.

        NOTE: ``asyncio.TimeoutError`` does **not** stop the underlying thread.
        The calling coroutine must discard the stale result and check
        cancellation/fencing tokens before acting on any returned value.
        """
        if self._shutdown:
            raise RuntimeError(f"{self._name}: executor shut down")

        # Admission control — atomic check under lock
        # zombie 计入容量：wait_for 超时/取消后底层线程仍在跑，若不算进占用，
        # 新任务会被放进 ThreadPoolExecutor 的无界队列、排在僵尸线程之后。
        async with self._lock:
            if self._active + self._queued + self._zombie >= self._capacity:
                self._metrics["rejected"] += 1
                raise ExecutorQueueFullError(self._name)
            self._queued += 1
            self._metrics["queued"] = self._queued

        queue_wait_start = time.monotonic()
        loop = asyncio.get_running_loop()

        try:
            # 直接用 pool.submit 拿到 concurrent.futures.Future：它的 done 状态
            # 只在线程真正结束（或排队任务被成功取消）时才为 True。wait_for
            # 超时会把 asyncio wrapper 标成 cancelled 而线程仍跑，若用 wrapper
            # 的 done 状态判断会误以为线程已归还。
            executor_future = self._pool.submit(
                functools.partial(fn, *args, **kwargs),
            )
            future = asyncio.wrap_future(executor_future, loop=loop)
        except Exception:
            # Thread pool rejected the submission
            async with self._lock:
                self._queued -= 1
                self._metrics["queued"] = self._queued
                self._metrics["failed"] += 1
            raise

        async with self._lock:
            self._queued -= 1
            self._active += 1
            self._metrics["queued"] = self._queued
            self._metrics["active"] = self._active

        effective_timeout = timeout if timeout is not None else self._default_timeout
        start = time.monotonic()

        try:
            result = await asyncio.wait_for(future, timeout=effective_timeout)
            duration = time.monotonic() - start
            # future 已 done，线程已归还，同步释放 active 槽位
            async with self._lock:
                self._active -= 1
                self._metrics["active"] = self._active
                self._metrics["completed"] += 1
                self._metrics["duration"] = duration
                self._metrics["queue_wait"] = start - queue_wait_start
            return result
        except TimeoutError:
            # wait_for 只取消 await，底层线程仍在跑 → 记为 zombie（计入准入
            # 容量），线程真正结束后经 concurrent future 回调归还。
            async with self._lock:
                self._active -= 1
                self._zombie += 1
                self._metrics["active"] = self._active
                self._metrics["zombie"] = self._zombie
                self._metrics["timed_out"] += 1
            executor_future.add_done_callback(
                lambda _f: self._schedule_zombie_done(loop)
            )
            raise
        except asyncio.CancelledError:
            async with self._lock:
                self._active -= 1
                self._zombie += 1
                self._metrics["active"] = self._active
                self._metrics["zombie"] = self._zombie
                self._metrics["cancelled"] += 1
            future.cancel()
            executor_future.add_done_callback(
                lambda _f: self._schedule_zombie_done(loop)
            )
            raise
        except Exception:
            async with self._lock:
                self._active -= 1
                self._metrics["active"] = self._active
                self._metrics["failed"] += 1
            raise

    def _schedule_zombie_done(self, loop) -> None:
        """把 zombie 归还调度回事件循环；loop 已关闭（进程退出）时跳过。"""
        if not loop.is_closed():
            loop.call_soon_threadsafe(self._on_zombie_done)

    def _on_zombie_done(self) -> None:
        """僵尸线程真正结束后归还其占用的准入容量（事件循环线程上执行）。"""
        if self._zombie > 0:
            self._zombie -= 1
            self._metrics["zombie"] = self._zombie

    async def shutdown(self) -> None:
        """Shut down the thread pool without blocking the event loop.

        Cancels queued futures and marks the executor as shut down.
        New submissions will be rejected.
        """
        self._shutdown = True
        self._pool.shutdown(wait=False, cancel_futures=True)

    def metrics_snapshot(self) -> dict[str, int | float]:
        """Return a copy of current metrics."""
        return dict(self._metrics)

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown
