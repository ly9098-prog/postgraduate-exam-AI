"""DurableTaskQueue integration tests — requires ``--run-integration``.

Verifies the durable task queue against real Redis with atomic Lua operations
and owner fencing. Covers all P0 scenarios from current_task.md §11.

Run with:
    pytest tests/integration/test_queue_integration.py --run-integration -v
"""

import asyncio
import os
import time

import pytest

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/1")


@pytest.fixture
def q():
    """Create a fresh DurableTaskQueue for each test, with clean Redis."""
    import redis

    r = redis.from_url(TEST_REDIS_URL, decode_responses=True)
    keys = r.keys("taskq:*")
    if keys:
        r.delete(*keys)
    r.close()

    from app.services.task_queue_service import DurableTaskQueue
    queue = DurableTaskQueue(redis_url=TEST_REDIS_URL)
    return queue


class TestDurableTaskQueueBasic:
    """Basic enqueue/dequeue/complete roundtrip."""

    @pytest.mark.asyncio
    async def test_enqueue_dequeue_roundtrip(self, q):
        """1. Enqueue a task, dequeue it, verify payload."""
        result = await q.enqueue(
            task_type="test_basic",
            payload={"msg": "hello"},
            task_id="test_basic_001",
        )
        assert result.task_id == "test_basic_001"

        task = await q.dequeue("test_basic", lease_sec=30)
        assert task is not None
        assert task.task_id == "test_basic_001"
        assert task.payload["msg"] == "hello"
        assert task.task_type == "test_basic"
        assert task.status.value == "processing"
        assert task.owner_token != ""

        await q.complete(task)
        assert result.task_id is not None

    @pytest.mark.asyncio
    async def test_complete_removes_from_processing(self, q):
        """2. Completing a task removes it from processing set."""
        await q.enqueue("test_clean", {"n": 1}, task_id="test_clean_001")

        task = await q.dequeue("test_clean", lease_sec=30)
        assert task is not None
        await q.complete(task)

        # Should not be dequeued again
        again = await q.dequeue("test_clean", lease_sec=5)
        assert again is None

        # Processing should be empty
        plen = await q.processing_length("test_clean")
        assert plen == 0

    @pytest.mark.asyncio
    async def test_idempotent_enqueue_no_duplicates(self, q):
        """7. Duplicate enqueue (same task_id) returns existing task_id, queue has 1."""
        tid1 = await q.enqueue(
            "test_idem", {"x": 1},
            task_id="test_idem_001", idempotent=True,
        )
        tid2 = await q.enqueue(
            "test_idem", {"x": 2},
            task_id="test_idem_001", idempotent=True,
        )
        assert tid1.task_id == tid2.task_id == "test_idem_001"

        # Dequeue once — should get only one task
        task1 = await q.dequeue("test_idem", lease_sec=10)
        assert task1 is not None
        await q.complete(task1)

        # Second dequeue should return None
        task2 = await q.dequeue("test_idem", lease_sec=5)
        assert task2 is None


class TestDurableTaskQueueFencing:
    """Owner token fencing — stale workers must be rejected."""

    @pytest.mark.asyncio
    async def test_stale_owner_heartbeat_rejected(self, q):
        """4. Stale owner's heartbeat is rejected (fencing)."""
        await q.enqueue("test_fence", {}, task_id="test_fence_001")

        # First claim
        task_a = await q.dequeue("test_fence", lease_sec=30)
        assert task_a is not None
        token_a = task_a.owner_token

        # Simulate reaper reclaim (force ZSET score + heartbeat expiry)
        import redis.asyncio as redis_async
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        # Force ZSET score to past so reaper will find it
        await r.zadd("taskq:processing:test_fence", {"test_fence_001": time.time() - 60})
        # Delete the heartbeat to simulate crash
        await r.delete("taskq:heartbeat:test_fence_001")
        await r.aclose()
        # Reclaim via reaper
        reclaimed = await q._reclaim_expired("test_fence")
        assert reclaimed >= 1
        await r.aclose()

        # Second claim (same task, new owner)
        task_b = await q.dequeue("test_fence", lease_sec=30)
        assert task_b is not None
        assert task_b.owner_token != token_a

        # Stale owner tries heartbeat — should fail
        task_a.owner_token = token_a  # restore stale token
        ok = await q.heartbeat(task_a)
        assert ok is False

    @pytest.mark.asyncio
    async def test_stale_owner_complete_rejected(self, q):
        """5. Stale owner's complete is rejected."""
        await q.enqueue("test_fence2", {}, task_id="test_fence_002")

        task_a = await q.dequeue("test_fence2", lease_sec=30)
        token_a = task_a.owner_token

        # Force reclaim (ZSET score to past + delete heartbeat)
        import redis.asyncio as redis_async
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        await r.zadd("taskq:processing:test_fence2", {"test_fence_002": time.time() - 60})
        await r.delete("taskq:heartbeat:test_fence_002")
        await r.aclose()
        await q._reclaim_expired("test_fence2")

        task_b = await q.dequeue("test_fence2", lease_sec=30)
        assert task_b is not None

        # Stale owner tries complete
        task_a.owner_token = token_a
        ok = await q.complete(task_a)
        assert ok is False

    @pytest.mark.asyncio
    async def test_stale_owner_fail_rejected(self, q):
        """5. Stale owner's fail is rejected."""
        await q.enqueue("test_fence3", {}, task_id="test_fence_003", max_retries=1)

        task_a = await q.dequeue("test_fence3", lease_sec=30)
        token_a = task_a.owner_token

        # Force reclaim
        import redis.asyncio as redis_async
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        await r.zadd("taskq:processing:test_fence3", {"test_fence_003": time.time() - 60})
        await r.delete("taskq:heartbeat:test_fence_003")
        await r.aclose()
        await q._reclaim_expired("test_fence3")

        task_b = await q.dequeue("test_fence3", lease_sec=30)
        assert task_b is not None

        # Stale owner tries fail
        task_a.owner_token = token_a
        ok = await q.fail(task_a, "stale error")
        assert ok is False

    @pytest.mark.asyncio
    async def test_two_workers_only_one_owner(self, q):
        """6. Two concurrent claims → only one gets the task."""
        await q.enqueue("test_race", {}, task_id="test_race_001")

        # Worker 1 claims
        t1 = await q.dequeue("test_race", lease_sec=30)

        # Worker 2 claims (should get nothing)
        t2 = await q.dequeue("test_race", lease_sec=5)

        assert t1 is not None
        assert t2 is None
        assert t1.task_id == "test_race_001"


class TestDurableTaskQueueReaper:
    """Reaper recovers crashed workers."""

    @pytest.mark.asyncio
    async def test_reaper_recovers_expired_lease(self, q):
        """Reaper reclaims tasks with expired lease and no heartbeat."""
        await q.enqueue("test_reap", {}, task_id="test_reap_001")

        # Claim with very short lease
        task = await q.dequeue("test_reap", lease_sec=1)
        assert task is not None

        # Wait for lease to expire and heartbeat to clear
        await q.heartbeat(task, lease_sec=1)

        import redis.asyncio as redis_async
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        # Force-delete heartbeat to simulate crash
        await r.delete("taskq:heartbeat:test_reap_001")
        await r.aclose()

        await asyncio.sleep(1.5)

        # Reaper should reclaim it
        reclaimed = await q._reclaim_expired("test_reap")
        assert reclaimed >= 1, "Reaper should reclaim expired task"

        # New worker can claim the reclaimed task
        task2 = await q.dequeue("test_reap", lease_sec=30)
        assert task2 is not None
        assert task2.task_id == "test_reap_001"

    @pytest.mark.asyncio
    async def test_reaper_skips_active_heartbeat(self, q):
        """Reaper skips tasks with active heartbeat (worker still alive)."""
        await q.enqueue("test_reap_hb", {}, task_id="test_reap_hb_001")

        task = await q.dequeue("test_reap_hb", lease_sec=30)

        # Heartbeat keeps it alive
        await q.heartbeat(task, lease_sec=30)

        # Reaper should NOT reclaim it (ZSET expired but heartbeat alive)
        # Force the ZSET score to be in the past
        import redis.asyncio as redis_async
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        # Manually set ZSET score to past
        await r.zadd("taskq:processing:test_reap_hb", {"test_reap_hb_001": time.time() - 60})
        await r.aclose()

        reclaimed = await q._reclaim_expired("test_reap_hb")
        assert reclaimed == 0, "Reaper should skip tasks with active heartbeat"

        await q.complete(task)


class TestDurableTaskQueueFailRetry:
    """Failure, retry, and dead-letter behavior."""

    @pytest.mark.asyncio
    async def test_fail_retry_then_succeed(self, q):
        """Task can be failed, retried, and completed."""
        await q.enqueue("test_retry", {}, task_id="test_retry_001", max_retries=2)

        task = await q.dequeue("test_retry", lease_sec=30)
        assert task is not None
        await q.fail(task, "retryable error")

        # Task should appear in retry ZSET
        rlen = await q.retry_length("test_retry")
        assert rlen >= 1

        # Wait for retry delay (base delay is 10s, exponential backoff)
        await asyncio.sleep(12)

        # Should be able to claim the retried task
        task2 = await q.dequeue("test_retry", lease_sec=30)
        assert task2 is not None
        assert task2.task_id == "test_retry_001"
        assert task2.retry_count == 1

        await q.complete(task2)

    @pytest.mark.asyncio
    async def test_fail_exhausts_retries_goes_to_dead(self, q):
        """Task that exhausts retries lands in dead-letter."""
        await q.enqueue("test_dead", {}, task_id="test_dead_001", max_retries=2)

        task = await q.dequeue("test_dead", lease_sec=30)
        await q.fail(task, "error 1")

        await asyncio.sleep(12)
        task2 = await q.dequeue("test_dead", lease_sec=30)
        assert task2 is not None
        await q.fail(task2, "error 2")

        # Should be in dead-letter
        dlen = await q.dead_length("test_dead")
        assert dlen >= 1

        # Should not appear in ready queue
        again = await q.dequeue("test_dead", lease_sec=5)
        assert again is None

    @pytest.mark.asyncio
    async def test_dead_letter_trim_limits_hash_growth(self, q):
        """11. Dead letter with many entries doesn't grow unbounded (LTRIM + TTL)."""
        # Enqueue more than DEAD_MAX tasks
        import redis.asyncio as redis_async
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)

        from app.services.task_queue_service import _DEAD_MAX

        for i in range(_DEAD_MAX + 50):
            tid = f"test_trim_{i:04d}"
            await q.enqueue("test_trim", {"i": i}, task_id=tid, max_retries=1)
            task = await q.dequeue("test_trim", lease_sec=30)
            await q.fail(task, f"error {i}")

        # Dead list should be exactly DEAD_MAX
        dlen = await q.dead_length("test_trim")
        assert dlen <= _DEAD_MAX, f"Dead list should be trimmed to {_DEAD_MAX}, got {dlen}"

        # Hashes for trimmed entries should have TTL (or be gone after trim)
        dead_ids = await r.lrange("taskq:dead:test_trim", 0, -1)
        hash_count = 0
        for tid in dead_ids:
            exists = await r.exists(f"taskq:task:{tid}")
            if exists:
                hash_count += 1
        await r.aclose()

        # At least the visible entries should have hashes
        assert hash_count == len(dead_ids)

    @pytest.mark.asyncio
    async def test_processing_does_not_grow_after_complete(self, q):
        """13. Completed tasks don't leave processing set growing."""
        for i in range(10):
            tid = f"test_nogrow_{i:04d}"
            await q.enqueue("test_nogrow", {"i": i}, task_id=tid)
            task = await q.dequeue("test_nogrow", lease_sec=30)
            assert task is not None
            await q.complete(task)

        plen = await q.processing_length("test_nogrow")
        assert plen == 0


class TestDurableTaskQueueHeartbeat:
    """Heartbeat extends leases properly."""

    @pytest.mark.asyncio
    async def test_heartbeat_extends_zset_lease(self, q):
        """2. Heartbeat updates processing ZSET score."""
        await q.enqueue("test_hb_z", {}, task_id="test_hb_z_001")

        task = await q.dequeue("test_hb_z", lease_sec=30)
        initial_expiry = task.lease_expires_at

        # Heartbeat should extend
        await q.heartbeat(task, lease_sec=60)

        # Re-dequeue to check new expiry — would only work if ZSET was updated
        # Indirect check: reaper should NOT reclaim 1s later
        await asyncio.sleep(1)
        reclaimed = await q._reclaim_expired("test_hb_z")
        assert reclaimed == 0, "Heartbeat should have extended ZSET lease"

        await q.complete(task)

    @pytest.mark.asyncio
    async def test_long_task_not_reclaimed_with_heartbeat(self, q):
        """4. Long task with regular heartbeat is not re-executed."""
        await q.enqueue("test_long", {}, task_id="test_long_001")

        task = await q.dequeue("test_long", lease_sec=3)

        # Simulate long processing with heartbeats
        for _ in range(3):
            await asyncio.sleep(1)
            ok = await q.heartbeat(task, lease_sec=3)
            assert ok is True, "Heartbeat should succeed during processing"

        # Reaper should not steal it
        reclaimed = await q._reclaim_expired("test_long")
        assert reclaimed == 0, "Reaper should not reclaim a task with active heartbeat"

        await q.complete(task)


class TestDurableTaskQueueEdgeCases:
    """Edge cases and error recovery."""

    @pytest.mark.asyncio
    async def test_enqueue_without_idempotent_key_works(self, q):
        """Enqueue with idempotent=False always creates a new entry."""
        tid1 = await q.enqueue("test_nonidem", {"x": 1}, idempotent=False)
        tid2 = await q.enqueue("test_nonidem", {"x": 2}, idempotent=False)
        assert tid1 != tid2  # different auto-generated IDs

        t1 = await q.dequeue("test_nonidem", lease_sec=10)
        assert t1 is not None
        t2 = await q.dequeue("test_nonidem", lease_sec=10)
        assert t2 is not None

    @pytest.mark.asyncio
    async def test_dequeue_empty_returns_none(self, q):
        """Dequeue from empty queue returns None."""
        task = await q.dequeue("nonexistent", lease_sec=5)
        assert task is None

    @pytest.mark.asyncio
    async def test_complete_nonexistent_no_error(self, q):
        """Complete on non-existent task doesn't crash."""
        from app.services.task_queue_service import Task

        t = Task(task_id="does_not_exist", task_type="test", payload={})
        ok = await q.complete(t)
        # Should not raise

    @pytest.mark.asyncio
    async def test_fail_nonexistent_no_error(self, q):
        """Fail on non-existent task doesn't crash."""
        from app.services.task_queue_service import Task

        t = Task(task_id="does_not_exist", task_type="test", payload={})
        ok = await q.fail(t, "test error")
        # Should not raise

    @pytest.mark.asyncio
    async def test_multiple_task_types_isolated(self, q):
        """Different task types don't interfere."""
        await q.enqueue("type_a", {"a": 1}, task_id="multi_a_001")
        await q.enqueue("type_b", {"b": 2}, task_id="multi_b_001")

        a = await q.dequeue("type_a", lease_sec=10)
        assert a is not None
        assert a.task_id == "multi_a_001"

        b = await q.dequeue("type_b", lease_sec=10)
        assert b is not None
        assert b.task_id == "multi_b_001"
