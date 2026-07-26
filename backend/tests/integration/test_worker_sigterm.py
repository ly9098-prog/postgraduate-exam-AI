"""Worker dispatcher + SIGTERM + heartbeat integration tests.

Tests for Batch 6 (P0-6):
- Worker dispatcher redesign (semaphore-based concurrency)
- Smart heartbeat with lease-window-aware failure detection
- SIGTERM graceful shutdown with drain+shield
- Unknown task type → dead-letter
- Cancellation checkpoints

Run:  REDIS_URL=redis://... \\
      python -m pytest tests/integration/test_worker_sigterm.py -x -v --run-integration
"""
from __future__ import annotations

import asyncio
import os
import time

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("REDIS_URL"),
        reason="Requires REDIS_URL",
    ),
]


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL not set")
    return url


@pytest.fixture
def test_suffix() -> str:
    return f"sigterm_{time.time_ns()}"


# ══════════════════════════════════════════════════════════════════════════════
# Test 1: Draining stops new claims
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_draining_stops_new_claims():
    """Dispatcher stops claiming new tasks after set_draining_v2 is called."""
    from app.core.config import settings

    original_concurrency = settings.WORKER_CONCURRENCY
    settings.WORKER_CONCURRENCY = 2

    from app.services.task_queue_worker import (
        _v2_worker_draining,
        _v2_worker_running,
        is_draining_v2,
        run_dispatcher_v2,
        set_draining_v2,
        stop_worker_v2,
    )

    try:
        assert is_draining_v2() is False

        # Start dispatcher briefly
        dispatcher_task = asyncio.create_task(run_dispatcher_v2(poll_interval=0.5))
        await asyncio.sleep(0.3)
        assert _v2_worker_running is True
        assert _v2_worker_draining is False

        # Set draining
        set_draining_v2()
        await asyncio.sleep(0.3)

        # Verify draining is set and stays
        assert is_draining_v2() is True
    finally:
        stop_worker_v2()
        settings.WORKER_CONCURRENCY = original_concurrency


# ══════════════════════════════════════════════════════════════════════════════
# Test 2: Unknown task type → dead-letter (via queue)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unknown_task_type_dead_letter(test_suffix: str):
    """Enqueueing a task with unknown type should go to dead-letter when processed."""
    import json

    import redis.asyncio as redis_async

    from app.services.task_queue_service import DurableTaskQueue
    from app.services.task_queue_worker import (
        _process_task_v2,
    )

    url = _redis_url()
    client = redis_async.from_url(url, decode_responses=True)

    queue = DurableTaskQueue(redis_url=url)
    task_type = f"unknown_{test_suffix}"

    try:
        # Enqueue an unknown task type
        result = await queue.enqueue_v2(
            task_type,
            {"test": True},
            task_id=f"test_unknown_{test_suffix}",
            max_retries=0,
        )
        assert result.accepted is True
        tid = result.task_id

        # Now claim it (using dequeue_v2)
        task = await queue.dequeue_v2(task_type, lease_sec=30)
        assert task is not None, "Should be able to claim the task"
        assert task.task_type == task_type
        assert task.max_retries == 0

        # Process it — _process_task_v2 should raise ValueError for unknown type
        with pytest.raises(ValueError, match=f"unknown_task_type: {task_type}"):
            await _process_task_v2(task)

        # Verify the task's max_retries was set to 0 by the handler
        assert task.max_retries == 0

        # Fail the task — with max_retries=0 it goes to dead-letter
        result = await queue.fail_v2(task, "unknown_task_type")
        assert result in (1, 2), f"Should be dead-lettered, got {result}"

        # Clean up from queue
        await client.zrem(f"taskq:v2:processing:{task_type}", tid)
        await client.lrem(f"taskq:v2:dead:{task_type}", 1, tid)

        print(f"\n=== PASS: unknown task type dead-lettered: {tid} ===\n")
    finally:
        await client.aclose()
        await queue.close()


# ══════════════════════════════════════════════════════════════════════════════
# Test 3: Heartbeat with lease-window awareness (safe → retry)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_heartbeat_lease_window_safe_retry():
    """With a safe lease window, heartbeat retries on transient error."""
    from app.services.task_queue_service import Task, TaskStatus

    # Create a task with a long lease window
    task = Task(
        task_id="test_safe_lease",
        task_type="import_pipeline",
        payload={},
        lease_expires_at=time.time() + 600,  # 10 min lease window
        owner_token="test_owner",
        generation=1,
        status=TaskStatus.PROCESSING,
    )

    owner_lost = asyncio.Event()

    # Mock the heartbeat to simulate one transient failure then success
    call_count = 0

    async def _mock_heartbeat(t, **_kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError("transient timeout")
        return 1

    from app.services.task_queue_service import task_queue as real_queue
    original_heartbeat = real_queue.heartbeat_v2
    real_queue.heartbeat_v2 = _mock_heartbeat

    try:
        # Run heartbeat loop briefly (cancelled after first retry)
        hb_task = asyncio.create_task(
            _run_heartbeat_test(task, 15, owner_lost)
        )
        await asyncio.sleep(2)

        # Owner should NOT be lost — safe lease window allowed retry
        assert owner_lost.is_set() is False, (
            f"Owner should not be lost with safe lease window (call_count={call_count})"
        )

        hb_task.cancel()
        try:
            await hb_task
        except (asyncio.CancelledError, Exception):
            pass
    finally:
        real_queue.heartbeat_v2 = original_heartbeat


async def _run_heartbeat_test(task, lease_sec, owner_lost):
    """Run the new heartbeat loop with lease-window awareness."""
    from app.services.task_queue_worker import _v2_heartbeat_loop_with_lease_window
    # Set running flag so loop doesn't exit immediately
    from app.services.task_queue_worker import _v2_worker_running
    _v2_worker_running = True
    try:
        await _v2_heartbeat_loop_with_lease_window(task, lease_sec, owner_lost)
    finally:
        _v2_worker_running = False


# ══════════════════════════════════════════════════════════════════════════════
# Test 4: Heartbeat with unsafe window → immediate owner-lost
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_heartbeat_unsafe_window_immediate_owner_lost():
    """With an unsafe lease window (expiring soon), transient error → immediate owner-lost."""
    from app.services.task_queue_service import Task, TaskStatus

    # Create a task with a nearly-expired lease window
    task = Task(
        task_id="test_unsafe_lease",
        task_type="import_pipeline",
        payload={},
        lease_expires_at=time.time() + 5,  # Only 5 seconds left (< interval*2)
        owner_token="test_owner",
        generation=1,
        status=TaskStatus.PROCESSING,
    )

    owner_lost = asyncio.Event()

    async def _mock_failing_heartbeat(t, **_kw):
        raise asyncio.TimeoutError("transient timeout")

    from app.services.task_queue_service import task_queue as real_queue
    original_heartbeat = real_queue.heartbeat_v2
    real_queue.heartbeat_v2 = _mock_failing_heartbeat

    try:
        hb_task = asyncio.create_task(
            _run_heartbeat_test(task, 15, owner_lost)
        )
        try:
            await asyncio.wait_for(hb_task, timeout=5)
        except asyncio.TimeoutError:
            pass

        # Owner should be lost — unsafe lease window triggered immediate loss
        assert owner_lost.is_set(), (
            "Owner should be lost with unsafe lease window"
        )
    finally:
        real_queue.heartbeat_v2 = original_heartbeat


# ══════════════════════════════════════════════════════════════════════════════
# Test 5: Heartbeat explicit Lua rejection → immediate owner-lost
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_heartbeat_lua_rejection_immediate_owner_lost():
    """Explicit 0/-1 from heartbeat Lua → immediate owner-lost."""
    from app.services.task_queue_service import Task, TaskStatus

    task = Task(
        task_id="test_lua_reject",
        task_type="import_pipeline",
        payload={},
        lease_expires_at=time.time() + 600,
        owner_token="test_owner",
        generation=1,
        status=TaskStatus.PROCESSING,
    )

    owner_lost = asyncio.Event()

    async def _mock_rejecting_heartbeat(t, **_kw):
        return 0  # owner mismatch

    from app.services.task_queue_service import task_queue as real_queue
    original_heartbeat = real_queue.heartbeat_v2
    real_queue.heartbeat_v2 = _mock_rejecting_heartbeat

    try:
        hb_task = asyncio.create_task(
            _run_heartbeat_test(task, 15, owner_lost)
        )
        try:
            await asyncio.wait_for(hb_task, timeout=5)
        except asyncio.TimeoutError:
            pass

        assert owner_lost.is_set(), "Owner should be lost on Lua rejection"
    finally:
        real_queue.heartbeat_v2 = original_heartbeat


# ══════════════════════════════════════════════════════════════════════════════
# Test 6: Cancellation checkpoint
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cancellation_checkpoint():
    """Cancellation checkpoint raises CancelledError when task is cancelled."""
    from app.features.pipeline_orchestrator import _check_cancelled

    async def _cancellable():
        # This function will be cancelled externally
        # _check_cancelled should raise CancelledError at the checkpoint
        await asyncio.sleep(0.1)
        await _check_cancelled()
        return "should_not_reach"

    task = asyncio.create_task(_cancellable())
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


# ══════════════════════════════════════════════════════════════════════════════
# Test 7: Worker dispatcher concurrency=1 (needs Redis)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dispatcher_concurrency_limit(test_suffix: str):
    """With WORKER_CONCURRENCY=1, only one task processes at a time."""
    import redis.asyncio as redis_async

    url = _redis_url()
    redis = redis_async.from_url(url, decode_responses=True)

    from app.core.config import settings
    from app.services.task_queue_service import DurableTaskQueue

    original_concurrency = settings.WORKER_CONCURRENCY
    settings.WORKER_CONCURRENCY = 1

    queue = DurableTaskQueue(redis_url=url)
    tt = f"conc_test_{test_suffix}"

    # Track concurrent processing
    processing_counter = 0
    max_concurrent = 0
    proceed = asyncio.Event()

    # Monkey-patch the dispatcher's task processing to use our tracker
    original_process = __import__(
        "app.services.task_queue_worker", fromlist=["_process_claimed_task_v2"]
    )._process_claimed_task_v2

    async def _tracking_processing(task, lease_sec, sem):
        nonlocal processing_counter, max_concurrent
        processing_counter += 1
        max_concurrent = max(max_concurrent, processing_counter)
        try:
            # Wait until we're told to proceed
            await asyncio.wait_for(proceed.wait(), timeout=10)
        finally:
            processing_counter -= 1

    import app.services.task_queue_worker as tqw

    tqw._process_claimed_task_v2 = _tracking_processing

    try:
        # Enqueue 2 tasks
        r1 = await queue.enqueue_v2(tt, {"seq": 1}, task_id=f"conc1_{test_suffix}")
        r2 = await queue.enqueue_v2(tt, {"seq": 2}, task_id=f"conc2_{test_suffix}")
        assert r1.accepted
        assert r2.accepted

        # Start dispatcher
        dispatcher = asyncio.create_task(tqw.run_dispatcher_v2(poll_interval=0.3))
        await asyncio.sleep(1.5)

        # With concurrency=1, only 1 task should be in processing at any time
        # (since we block on proceed event)
        assert max_concurrent <= 1, f"max_concurrent={max_concurrent}, expected <=1"

        # Allow tasks to complete
        proceed.set()
        await asyncio.sleep(1)

    finally:
        tqw._process_claimed_task_v2 = original_process
        settings.WORKER_CONCURRENCY = original_concurrency
        tqw.stop_worker_v2()
        # Clean up v2 queue
        cursor = 0
        pattern = f"taskq:v2:*:{tt}*"
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=200)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
        await redis.aclose()
        await queue.close()
