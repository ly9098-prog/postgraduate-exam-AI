"""Tests for BoundedExecutor — admission, timeout, shutdown, metrics."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.core.bounded_executor import BoundedExecutor, ExecutorQueueFullError


def _return_arg(arg: int) -> int:
    """Simple synchronous function used as an executor target."""
    return arg


def _slow(duration: float) -> str:
    """Block for *duration* seconds."""
    time.sleep(duration)
    return "done"


def _raise_value_error() -> None:
    raise ValueError("boom")


class TestBoundedExecutor:
    """BoundedExecutor unit tests — all paths."""

    # ── Happy path ──

    @pytest.mark.asyncio
    async def test_basic_execution(self) -> None:
        ex = BoundedExecutor("test", max_workers=1, max_queued=2, timeout=30)
        result = await ex.run(_return_arg, 42)
        assert result == 42
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_multiple_params(self) -> None:
        ex = BoundedExecutor("test", max_workers=1, max_queued=2, timeout=30)
        result = await ex.run(_return_arg, 99)
        assert result == 99
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_multiple_concurrent_runs(self) -> None:
        ex = BoundedExecutor("test", max_workers=2, max_queued=4, timeout=30)
        results = await asyncio.gather(
            ex.run(_return_arg, 1),
            ex.run(_return_arg, 2),
            ex.run(_return_arg, 3),
        )
        assert results == [1, 2, 3]
        await ex.shutdown()

    # ── Admission control ──

    @pytest.mark.asyncio
    async def test_rejects_when_queue_full(self) -> None:
        """Submit more than capacity (workers + queued) → ExecutorQueueFullError."""
        ex = BoundedExecutor("test", max_workers=1, max_queued=1, timeout=1)
        # Fill the executor: 1 running + 1 queued = 2 = capacity
        tasks = [asyncio.create_task(ex.run(_slow, 10)) for _ in range(2)]

        # Give tasks a moment to be admitted
        await asyncio.sleep(0.05)

        # This submission should be rejected immediately
        with pytest.raises(ExecutorQueueFullError):
            await ex.run(_return_arg, 99)

        # Cancel the slow tasks
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_rejects_when_exactly_at_capacity(self) -> None:
        """Exactly at capacity (active + queued == capacity) still rejects."""
        ex = BoundedExecutor("test", max_workers=1, max_queued=0, timeout=60)
        # Fill: 1 running = capacity
        task = asyncio.create_task(ex.run(_slow, 10))
        await asyncio.sleep(0.05)

        with pytest.raises(ExecutorQueueFullError):
            await ex.run(_return_arg, 99)

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await ex.shutdown()

    # ── Timeout ──

    @pytest.mark.asyncio
    async def test_times_out(self) -> None:
        """Short timeout raises asyncio.TimeoutError."""
        ex = BoundedExecutor("test", max_workers=1, max_queued=1, timeout=60)
        with pytest.raises(asyncio.TimeoutError):
            await ex.run(_slow, 10, timeout=0.01)
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_default_timeout_applied(self) -> None:
        """Default constructor timeout is used when no per-call timeout given."""
        ex = BoundedExecutor("test", max_workers=1, max_queued=1, timeout=0.01)
        with pytest.raises(asyncio.TimeoutError):
            await ex.run(_slow, 10)
        await ex.shutdown()

    # ── Shutdown ──

    @pytest.mark.asyncio
    async def test_shutdown_rejects_new_work(self) -> None:
        ex = BoundedExecutor("test", max_workers=1, max_queued=1, timeout=30)
        await ex.shutdown()
        with pytest.raises(RuntimeError, match="shut down"):
            await ex.run(_return_arg, 1)

    @pytest.mark.asyncio
    async def test_is_shutdown_flag(self) -> None:
        ex = BoundedExecutor("test", max_workers=1, max_queued=1, timeout=30)
        assert not ex.is_shutdown
        await ex.shutdown()
        assert ex.is_shutdown

    # ── Metrics ──

    @pytest.mark.asyncio
    async def test_metrics_success_path(self) -> None:
        ex = BoundedExecutor("test", max_workers=1, max_queued=1, timeout=30)
        await ex.run(_return_arg, 1)
        m = ex.metrics_snapshot()
        assert m["completed"] == 1
        assert m["failed"] == 0
        assert m["timed_out"] == 0
        assert m["cancelled"] == 0
        assert m["active"] == 0
        assert m["queued"] == 0
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_metrics_timeout_path(self) -> None:
        ex = BoundedExecutor("test", max_workers=1, max_queued=1, timeout=60)
        with pytest.raises(asyncio.TimeoutError):
            await ex.run(_slow, 10, timeout=0.01)
        m = ex.metrics_snapshot()
        assert m["timed_out"] == 1
        assert m["active"] == 0  # cleaned up
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_metrics_rejected_path(self) -> None:
        ex = BoundedExecutor("test", max_workers=1, max_queued=0, timeout=60)
        task = asyncio.create_task(ex.run(_slow, 10))
        await asyncio.sleep(0.05)

        with pytest.raises(ExecutorQueueFullError):
            await ex.run(_return_arg, 1)

        m = ex.metrics_snapshot()
        assert m["rejected"] >= 1
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_metrics_failed_path(self) -> None:
        """Function that raises → metrics['failed'] increments."""
        ex = BoundedExecutor("test", max_workers=1, max_queued=1, timeout=30)
        with pytest.raises(ValueError, match="boom"):
            await ex.run(_raise_value_error)
        m = ex.metrics_snapshot()
        assert m["failed"] == 1
        assert m["active"] == 0
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_metrics_cancelled_path(self) -> None:
        """Cancelled task → metrics['cancelled'] increments."""
        ex = BoundedExecutor("test", max_workers=1, max_queued=1, timeout=60)
        task = asyncio.create_task(ex.run(_slow, 10))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        m = ex.metrics_snapshot()
        assert m["cancelled"] == 1
        assert m["active"] == 0
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_metrics_all_paths_combined(self) -> None:
        """Multiple operations on one executor: all counters behave correctly."""
        ex = BoundedExecutor("test", max_workers=2, max_queued=2, timeout=60)

        # 1 success
        await ex.run(_return_arg, 42)
        m = ex.metrics_snapshot()
        assert m["completed"] == 1

        # 1 failure
        with pytest.raises(ValueError):
            await ex.run(_raise_value_error)
        m = ex.metrics_snapshot()
        assert m["failed"] == 1
        assert m["completed"] == 1

        # 1 timeout
        with pytest.raises(asyncio.TimeoutError):
            await ex.run(_slow, 10, timeout=0.01)
        m = ex.metrics_snapshot()
        assert m["timed_out"] == 1

        # 1 rejection (fill to capacity then submit)
        # max_workers=2 + max_queued=2 = capacity=4
        tasks = [asyncio.create_task(ex.run(_slow, 10)) for _ in range(4)]
        await asyncio.sleep(0.05)  # let all 4 be admitted (2 active + 2 queued)
        with pytest.raises(ExecutorQueueFullError):
            await ex.run(_return_arg, 1)
        m = ex.metrics_snapshot()
        assert m["rejected"] >= 1

        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await ex.shutdown()

    # ── Name ──

    @pytest.mark.asyncio
    async def test_name_property(self) -> None:
        ex = BoundedExecutor("my-exec", max_workers=1, max_queued=1, timeout=30)
        assert ex.name == "my-exec"
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_executor_queue_full_error(self) -> None:
        err = ExecutorQueueFullError("test", retry_after=30)
        assert err.executor_name == "test"
        assert err.retry_after == 30
        assert "test" in str(err)
        assert "30" in str(err)
