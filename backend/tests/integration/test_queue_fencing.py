"""Queue v2 fencing integration tests — requires ``--run-integration``.

Tests the v2 key namespace with HINCRBY-based generation fencing,
retry-full atomic dead-letter, corrupt collection, and queue health.
Generation is monotonic and NEVER reset.

Run with:
    pytest tests/integration/test_queue_fencing.py --run-integration -v
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from app.services.task_queue_service import (
    QueueHealthError,
    TaskStatus,
)

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/1")


@pytest.fixture
def q():
    """Create a fresh DurableTaskQueue for each test, with clean v2 keys."""
    import redis

    r = redis.from_url(TEST_REDIS_URL, decode_responses=True)
    keys = r.keys("taskq:v2:*")
    if keys:
        r.delete(*keys)
    r.close()

    from app.services.task_queue_service import DurableTaskQueue
    queue = DurableTaskQueue(redis_url=TEST_REDIS_URL)
    return queue


class TestQueueV2Basic:
    """Basic v2 enqueue/dequeue/complete roundtrip."""

    @pytest.mark.asyncio
    async def test_enqueue_dequeue_roundtrip(self, q):
        """v2: Enqueue → dequeue → verify payload and generation."""
        result = await q.enqueue_v2(
            task_type="v2_basic",
            payload={"msg": "hello v2"},
            task_id="v2_basic_001",
        )
        assert result.accepted
        assert result.task_id == "v2_basic_001"

        task = await q.dequeue_v2("v2_basic", lease_sec=30)
        assert task is not None
        assert task.task_id == "v2_basic_001"
        assert task.payload["msg"] == "hello v2"
        assert task.task_type == "v2_basic"
        assert task.status == TaskStatus.PROCESSING
        assert task.owner_token != ""
        assert task.generation >= 1, "Generation must be >= 1 (HINCRBY started)"

        # Complete should succeed
        ok = await q.complete_v2(task)
        assert ok == 1

    @pytest.mark.asyncio
    async def test_enqueue_v2_idempotent(self, q):
        """v2 duplicate enqueue returns same task_id."""
        r1 = await q.enqueue_v2(
            "v2_idem", {"x": 1},
            task_id="v2_idem_001", idempotent=True,
        )
        r2 = await q.enqueue_v2(
            "v2_idem", {"x": 2},
            task_id="v2_idem_001", idempotent=True,
        )
        assert r1.task_id == r2.task_id == "v2_idem_001"

        # Dequeue once
        task = await q.dequeue_v2("v2_idem", lease_sec=10)
        assert task is not None
        await q.complete_v2(task)

        # Second dequeue should be None
        task2 = await q.dequeue_v2("v2_idem", lease_sec=5)
        assert task2 is None

    @pytest.mark.asyncio
    async def test_v2_keys_namespace(self, q):
        """v2 operations use taskq:v2:* keys, not v1."""
        import redis.asyncio as redis_async

        await q.enqueue_v2("v2_ns", {"n": 1}, task_id="v2_ns_001")
        task = await q.dequeue_v2("v2_ns", lease_sec=30)
        assert task is not None
        await q.complete_v2(task)

        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)

        # v2 keys should exist
        cursor = 0
        v2_keys = []
        while True:
            cursor, batch = await r.scan(cursor=cursor, match="taskq:v2:*", count=1000)
            v2_keys.extend(batch)
            if cursor == 0:
                break
        assert len(v2_keys) > 0, "v2 keys should be present"

        # v1 keys for this type should NOT exist
        v1_ready = await r.exists("taskq:queue:v2_ns")
        v1_processing = await r.exists("taskq:processing:v2_ns")
        assert not v1_ready, "v1 ready key should not exist"
        assert not v1_processing, "v1 processing key should not exist"

        await r.aclose()


class TestQueueV2FencingGeneration:
    """Generation fencing via HINCRBY — monotonic, never reset."""

    @pytest.mark.asyncio
    async def test_generation_monotonic(self, q):
        """Generation increases with each claim (monotonic, never reset)."""
        import redis.asyncio as redis_async

        await q.enqueue_v2("v2_gen", {}, task_id="v2_gen_001")

        # Claim 1
        t1 = await q.dequeue_v2("v2_gen", lease_sec=1)
        assert t1 is not None
        gen1 = t1.generation

        # Force reaper to reclaim (delete heartbeat, expire lease)
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        await r.delete("taskq:v2:heartbeat:v2_gen_001")
        await r.zadd("taskq:v2:processing:v2_gen", {"v2_gen_001": time.time() - 60})
        await r.aclose()

        await q._reclaim_expired_v2("v2_gen")

        # Claim 2 — generation must be higher
        t2 = await q.dequeue_v2("v2_gen", lease_sec=30)
        assert t2 is not None
        gen2 = t2.generation

        assert gen2 > gen1, f"Generation must increase: {gen2} <= {gen1}"

    @pytest.mark.asyncio
    async def test_generation_never_reset_on_complete(self, q):
        """Complete does not reset the fencing key."""
        import redis.asyncio as redis_async

        await q.enqueue_v2("v2_gen2", {}, task_id="v2_gen2_001")
        t = await q.dequeue_v2("v2_gen2", lease_sec=30)
        assert t is not None
        gen = t.generation

        assert gen >= 1

        # Complete should not reset fencing key
        ok = await q.complete_v2(t)
        assert ok == 1

        # Verify fencing key still exists with same generation
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        fencing_val = await r.hget("taskq:v2:fencing:v2_gen2_001", "gen")
        await r.aclose()
        assert fencing_val is not None, "Fencing key must NOT be deleted on complete"
        assert int(fencing_val) >= gen, "Fencing gen must not decrease"

    @pytest.mark.asyncio
    async def test_generation_never_reset_on_fail_dead(self, q):
        """Fail→dead does not reset the fencing key."""
        import redis.asyncio as redis_async

        await q.enqueue_v2("v2_gen3", {}, task_id="v2_gen3_001", max_retries=0)
        t = await q.dequeue_v2("v2_gen3", lease_sec=30)
        gen = t.generation
        ok = await q.fail_v2(t, "dead")
        assert ok == 1

        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        fencing_val = await r.hget("taskq:v2:fencing:v2_gen3_001", "gen")
        await r.aclose()
        assert fencing_val is not None, "Fencing key must NOT be deleted on fail->dead"
        assert int(fencing_val) >= gen


class TestQueueV2StaleWorker:
    """Stale workers (bad owner_token or generation) are rejected."""

    @pytest.mark.asyncio
    async def test_stale_owner_heartbeat_rejected(self, q):
        """Old owner_token's heartbeat is rejected (returns 0)."""
        await q.enqueue_v2("v2_fence", {}, task_id="v2_fence_001")

        t1 = await q.dequeue_v2("v2_fence", lease_sec=30)
        assert t1 is not None
        token_a = t1.owner_token

        # Force reclaim
        import redis.asyncio as redis_async
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        await r.delete("taskq:v2:heartbeat:v2_fence_001")
        await r.zadd("taskq:v2:processing:v2_fence", {"v2_fence_001": time.time() - 60})
        await r.aclose()
        await q._reclaim_expired_v2("v2_fence")

        # Claim 2
        t2 = await q.dequeue_v2("v2_fence", lease_sec=30)
        assert t2 is not None

        # Stale owner heartbeats
        t1.owner_token = token_a
        ok = await q.heartbeat_v2(t1)
        assert ok == 0  # owner mismatch

    @pytest.mark.asyncio
    async def test_stale_generation_heartbeat_rejected(self, q):
        """Stale generation heartbeat returns -1."""
        await q.enqueue_v2("v2_genf", {}, task_id="v2_genf_001")

        t1 = await q.dequeue_v2("v2_genf", lease_sec=30)
        assert t1 is not None
        token_a = t1.owner_token
        gen_a = t1.generation

        # Force reclaim (heartbeat + ZSET expiry)
        import redis.asyncio as redis_async
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        await r.delete("taskq:v2:heartbeat:v2_genf_001")
        await r.zadd("taskq:v2:processing:v2_genf", {"v2_genf_001": time.time() - 60})
        await r.aclose()
        await q._reclaim_expired_v2("v2_genf")

        # Claim 2 — new generation
        t2 = await q.dequeue_v2("v2_genf", lease_sec=30)
        assert t2 is not None

        # Now simulate stale generation: restore t1's generation on the task hash
        # AND restore its heartbeat token (which was deleted by reaper)
        r2 = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        await r2.setex("taskq:v2:heartbeat:v2_genf_001", 30, token_a)
        # Set task hash generation back to gen_a (stale)
        await r2.hset("taskq:v2:task:v2_genf_001", "generation", gen_a)
        await r2.aclose()

        # Stale generation heartbeat — should fail
        ok = await q.heartbeat_v2(t1)
        assert ok == -1, f"Expected generation mismatch (-1), got {ok}"

    @pytest.mark.asyncio
    async def test_stale_owner_complete_rejected(self, q):
        """Stale owner's complete is rejected (returns 0)."""
        await q.enqueue_v2("v2_comp", {}, task_id="v2_comp_001")
        t1 = await q.dequeue_v2("v2_comp", lease_sec=30)
        token_a = t1.owner_token

        # Force reclaim
        import redis.asyncio as redis_async
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        await r.delete("taskq:v2:heartbeat:v2_comp_001")
        await r.zadd("taskq:v2:processing:v2_comp", {"v2_comp_001": time.time() - 60})
        await r.aclose()
        await q._reclaim_expired_v2("v2_comp")

        t2 = await q.dequeue_v2("v2_comp", lease_sec=30)
        assert t2 is not None

        t1.owner_token = token_a
        ok = await q.complete_v2(t1)
        assert ok == 0  # owner mismatch

    @pytest.mark.asyncio
    async def test_stale_owner_fail_rejected(self, q):
        """Stale owner's fail is rejected (returns 0)."""
        await q.enqueue_v2("v2_fail", {}, task_id="v2_fail_001", max_retries=1)
        t1 = await q.dequeue_v2("v2_fail", lease_sec=30)
        token_a = t1.owner_token

        # Force reclaim
        import redis.asyncio as redis_async
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        await r.delete("taskq:v2:heartbeat:v2_fail_001")
        await r.zadd("taskq:v2:processing:v2_fail", {"v2_fail_001": time.time() - 60})
        await r.aclose()
        await q._reclaim_expired_v2("v2_fail")

        t2 = await q.dequeue_v2("v2_fail", lease_sec=30)
        assert t2 is not None

        t1.owner_token = token_a
        ok = await q.fail_v2(t1, "stale")
        assert ok == 0  # owner mismatch

    @pytest.mark.asyncio
    async def test_two_workers_only_one_owner(self, q):
        """Two concurrent claims → only one gets the task."""
        await q.enqueue_v2("v2_race", {}, task_id="v2_race_001")
        t1 = await q.dequeue_v2("v2_race", lease_sec=30)
        t2 = await q.dequeue_v2("v2_race", lease_sec=5)
        assert t1 is not None
        assert t2 is None


class TestQueueV2RetryDead:
    """Retry and dead-letter behavior."""

    @pytest.mark.asyncio
    async def test_fail_retry_then_succeed(self, q):
        """Task fails, retries, then completes."""
        await q.enqueue_v2("v2_rt", {}, task_id="v2_rt_001", max_retries=2)

        task = await q.dequeue_v2("v2_rt", lease_sec=30)
        assert task is not None
        ok = await q.fail_v2(task, "retry error")
        assert ok == 1  # retry

        # Should be in retry ZSET
        rlen = await q.retry_length_v2("v2_rt")
        assert rlen >= 1

        # Wait for retry delay (base 10s)
        await asyncio.sleep(12)

        # Claim retried task
        task2 = await q.dequeue_v2("v2_rt", lease_sec=30)
        assert task2 is not None
        assert task2.retry_count == 1

        # Verify generation increased on retry claim
        assert task2.generation > task.generation, \
            "Retry claim must have higher generation"

        await q.complete_v2(task2)

    @pytest.mark.asyncio
    async def test_fail_exhausts_retries_goes_to_dead(self, q):
        """Max retries exhausted → dead-letter."""
        await q.enqueue_v2("v2_dl", {}, task_id="v2_dl_001", max_retries=1)

        task = await q.dequeue_v2("v2_dl", lease_sec=30)
        ok = await q.fail_v2(task, "err1")
        assert ok == 1

        await asyncio.sleep(12)

        task2 = await q.dequeue_v2("v2_dl", lease_sec=30)
        assert task2 is not None
        ok = await q.fail_v2(task2, "err2")
        assert ok == 1  # dead-letter

        dlen = await q.dead_length_v2("v2_dl")
        assert dlen >= 1

    @pytest.mark.asyncio
    async def test_retry_full_atomic_dead(self, q):
        """Retry ZSET full → atomically dead-letter, not stuck in processing."""
        import redis.asyncio as redis_async

        from app.core.config import settings

        # Lower retry max for test
        original_retry_max = settings.TASK_QUEUE_RETRY_MAX
        settings.TASK_QUEUE_RETRY_MAX = 3

        try:
            # Manually fill the retry ZSET
            r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
            for i in range(3):
                await r.zadd("taskq:v2:retry:v2_full", {f"filler_{i}": time.time()})
            await r.aclose()

            await q.enqueue_v2("v2_full", {}, task_id="v2_full_001", max_retries=2)

            task = await q.dequeue_v2("v2_full", lease_sec=30)
            assert task is not None

            ok = await q.fail_v2(task, "retry full")
            # Should return 2 = dead-letter due to retry ZSET full
            assert ok == 2, f"Expected 2 (dead), got {ok}"

            # Verify not in processing
            plen = await q.processing_length_v2("v2_full")
            assert plen == 0, "Task must not remain in processing"
        finally:
            settings.TASK_QUEUE_RETRY_MAX = original_retry_max


class TestQueueV2Corrupt:
    """Corrupt collection management."""

    @pytest.mark.asyncio
    async def test_mark_corrupt(self, q):
        """Mark corrupt removes from processing and adds to corrupt ZSET."""
        await q.enqueue_v2("v2_cor", {}, task_id="v2_cor_001")
        task = await q.dequeue_v2("v2_cor", lease_sec=30)
        assert task is not None

        ok = await q.mark_corrupt_v2("v2_cor_001", "v2_cor", "test corruption")
        assert ok

        # Should be in corrupt ZSET
        clen = await q.corrupt_length_v2("v2_cor")
        assert clen >= 1

        # Should not be in processing
        plen = await q.processing_length_v2("v2_cor")
        assert plen == 0

        # List corrupt should include it
        entries = await q.list_corrupt_v2("v2_cor")
        assert len(entries) >= 1
        ids = [e.get("task_id") for e in entries]
        assert "v2_cor_001" in ids

    @pytest.mark.asyncio
    async def test_delete_from_corrupt(self, q):
        """Delete from corrupt ZSET works."""
        await q.enqueue_v2("v2_cd", {}, task_id="v2_cd_001")
        _ = await q.dequeue_v2("v2_cd", lease_sec=30)
        await q.mark_corrupt_v2("v2_cd_001", "v2_cd", "del test")

        ok = await q.delete_from_corrupt_v2("v2_cd", "v2_cd_001")
        assert ok

        clen = await q.corrupt_length_v2("v2_cd")
        assert clen == 0


class TestQueueV2Health:
    """Queue health methods raise QueueHealthError on Redis error."""

    @pytest.mark.asyncio
    async def test_queue_length_v2_without_redis(self, q):
        """Without Redis, queue_length_v2 raises QueueHealthError."""
        q._redis_enabled = False
        with pytest.raises(QueueHealthError):
            await q.queue_length_v2("test")

    @pytest.mark.asyncio
    async def test_queue_length_v2_with_redis(self, q):
        """With Redis, queue_length_v2 returns queue size."""
        await q.enqueue_v2("v2_hlth", {"x": 1}, task_id="v2_hlth_001")
        await q.enqueue_v2("v2_hlth", {"x": 2}, task_id="v2_hlth_002")

        length = await q.queue_length_v2("v2_hlth")
        assert length == 2

    @pytest.mark.asyncio
    async def test_processing_length_v2(self, q):
        """processing_length_v2 returns correct count."""
        await q.enqueue_v2("v2_proc", {"x": 1}, task_id="v2_proc_001")
        task = await q.dequeue_v2("v2_proc", lease_sec=30)
        assert task is not None

        plen = await q.processing_length_v2("v2_proc")
        assert plen == 1

        await q.complete_v2(task)
        plen = await q.processing_length_v2("v2_proc")
        assert plen == 0


class TestQueueV2DeadManagement:
    """Dead-letter management API."""

    @pytest.mark.asyncio
    async def test_list_dead_v2(self, q):
        """List dead entries returns correct data."""
        await q.enqueue_v2("v2_dm", {}, task_id="v2_dm_001", max_retries=0)
        task = await q.dequeue_v2("v2_dm", lease_sec=30)
        await q.fail_v2(task, "dead for list")

        entries = await q.list_dead_v2("v2_dm")
        assert len(entries) >= 1

    @pytest.mark.asyncio
    async def test_delete_from_dead_v2(self, q):
        """Delete a specific task from dead-letter."""
        await q.enqueue_v2("v2_dd", {}, task_id="v2_dd_001", max_retries=0)
        task = await q.dequeue_v2("v2_dd", lease_sec=30)
        await q.fail_v2(task, "dead for delete")

        ok = await q.delete_from_dead_v2("v2_dd", "v2_dd_001")
        assert ok

        dlen = await q.dead_length_v2("v2_dd")
        assert dlen == 0

    @pytest.mark.asyncio
    async def test_retry_from_dead_v2(self, q):
        """Retry from dead re-enqueues the task to ready queue."""
        await q.enqueue_v2("v2_dr", {}, task_id="v2_dr_001", max_retries=0)
        task = await q.dequeue_v2("v2_dr", lease_sec=30)
        await q.fail_v2(task, "dead for retry")

        ok = await q.retry_from_dead_v2("v2_dr", "v2_dr_001")
        assert ok

        # Should be in ready queue
        length = await q.queue_length_v2("v2_dr")
        assert length >= 1

        # Can claim it again
        task2 = await q.dequeue_v2("v2_dr", lease_sec=30)
        assert task2 is not None
        assert task2.task_id == "v2_dr_001"

        # Generation increments again (not reset)
        assert task2.generation > task.generation, \
            "Generation must be higher after retry from dead"


class TestQueueV2Reaper:
    """v2 reaper reclaims expired tasks."""

    @pytest.mark.asyncio
    async def test_reaper_recovers_expired_lease(self, q):
        """v2 reaper reclaims tasks with expired lease and no heartbeat."""
        import redis.asyncio as redis_async

        await q.enqueue_v2("v2_reap", {}, task_id="v2_reap_001")
        task = await q.dequeue_v2("v2_reap", lease_sec=1)
        assert task is not None

        # Force heartbeat deletion + ZSET expiry
        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        await r.delete("taskq:v2:heartbeat:v2_reap_001")
        await r.zadd("taskq:v2:processing:v2_reap", {"v2_reap_001": time.time() - 60})
        await r.aclose()

        # Reaper should reclaim
        reclaimed = await q._reclaim_expired_v2("v2_reap")
        assert reclaimed >= 1

        # Can claim again with higher generation
        task2 = await q.dequeue_v2("v2_reap", lease_sec=30)
        assert task2 is not None
        assert task2.task_id == "v2_reap_001"
        assert task2.generation > task.generation, \
            "Reclaimed task must have higher generation"

    @pytest.mark.asyncio
    async def test_reaper_skips_active_heartbeat(self, q):
        """v2 reaper skips tasks with active heartbeat."""
        import redis.asyncio as redis_async

        await q.enqueue_v2("v2_reap_hb", {}, task_id="v2_reap_hb_001")
        task = await q.dequeue_v2("v2_reap_hb", lease_sec=30)
        assert task is not None

        # Heartbeat is alive, but processing ZSET score is past
        await q.heartbeat_v2(task, lease_sec=30)

        r = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        await r.zadd("taskq:v2:processing:v2_reap_hb", {"v2_reap_hb_001": time.time() - 60})
        await r.aclose()

        reclaimed = await q._reclaim_expired_v2("v2_reap_hb")
        assert reclaimed == 0

        await q.complete_v2(task)


class TestQueueV2GetMetrics:
    """v2 metrics aggregation."""

    @pytest.mark.asyncio
    async def test_get_metrics_v2(self, q):
        """get_metrics_v2 returns all expected keys."""
        await q.enqueue_v2("v2_met", {"x": 1}, task_id="v2_met_001")

        metrics = await q.get_metrics_v2(task_types=["v2_met"])
        assert "ready" in metrics
        assert "processing" in metrics
        assert "retry" in metrics
        assert "dead" in metrics
        assert metrics["ready"] >= 1

    @pytest.mark.asyncio
    async def test_get_metrics_v2_multiple_types(self, q):
        """get_metrics_v2 handles multiple task types."""
        await q.enqueue_v2("type_a", {"a": 1}, task_id="a_001")
        await q.enqueue_v2("type_b", {"b": 1}, task_id="b_001")

        metrics = await q.get_metrics_v2(task_types=["type_a", "type_b"])
        assert metrics["ready"] >= 2
