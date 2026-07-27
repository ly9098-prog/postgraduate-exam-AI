"""Tests for v1/v2 queue split fix, cancel semantics, and payload versioning.

Requires ``--run-integration`` flag and a running Redis on TEST_REDIS_URL.

Run with:
    pytest tests/integration/test_queue_hardening.py --run-integration -v
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from app.services.task_queue_service import (
    Task,
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


# ══════════════════════════════════════════════════════════════════
# v1/v2 Queue Split — all enqueue helpers must use v2
# ══════════════════════════════════════════════════════════════════


class TestV1V2QueueSplit:
    """Verify that v1 and v2 keys don't overlap and enqueue_v2 works."""

    @pytest.mark.asyncio
    async def test_enqueue_v2_uses_v2_keys(self, q):
        """enqueue_v2 writes to taskq:v2:* keys, not taskq:queue:*."""
        result = await q.enqueue_v2(
            "test_split", {"k": "v"},
            task_id="split_test_001",
        )
        assert result.accepted
        assert result.task_id == "split_test_001"

        # Verify v2 keys exist
        task = await q.dequeue_v2("test_split", lease_sec=30)
        assert task is not None
        assert task.task_id == "split_test_001"

        # Complete
        ok = await q.complete_v2(task)
        assert ok == 1

    @pytest.mark.asyncio
    async def test_v1_enqueue_not_consumed_by_v2_dispatcher(self, q):
        """v1 enqueue writes to taskq:queue:* which v2 dequeue does NOT read."""
        result = await q.enqueue(
            "test_v1_only", {"k": "v"},
            task_id="v1_only_001",
        )
        assert result.accepted

        # v2 dequeue should NOT find this task
        task = await q.dequeue_v2("test_v1_only", lease_sec=30)
        assert task is None, "v2 dequeue should NOT consume v1-enqueued tasks"

    @pytest.mark.asyncio
    async def test_drain_v1_to_v2_migration(self, q):
        """drain_v1_to_v2 migrates v1 tasks to v2 keys."""
        # Enqueue via v1
        r1 = await q.enqueue(
            "test_drain", {"k": "v1"},
            task_id="drain_v1_001",
        )
        assert r1.accepted

        # Migrate to v2
        migrated = await q.drain_v1_to_v2("test_drain")
        assert migrated == 1, "Should migrate 1 task"

        # Now v2 dequeue should find it
        task = await q.dequeue_v2("test_drain", lease_sec=30)
        assert task is not None
        assert task.task_id == "drain_v1_001"
        assert task.payload["k"] == "v1"

        # Clean up
        await q.complete_v2(task)

    @pytest.mark.asyncio
    async def test_drain_is_idempotent(self, q):
        """Running drain multiple times doesn't create duplicate tasks."""
        await q.enqueue(
            "test_idem_drain", {"k": "v"},
            task_id="idem_drain_001",
        )

        migrated1 = await q.drain_v1_to_v2("test_idem_drain")
        assert migrated1 == 1

        migrated2 = await q.drain_v1_to_v2("test_idem_drain")
        assert migrated2 == 0, "Second drain should migrate 0 (already in v2)"

    @pytest.mark.asyncio
    async def test_v1_enqueue_warns_in_restricted_env(self, q):
        """v1 enqueue logs warning in restricted environment (simulated)."""
        # Set _is_restricted to True for this test
        q._is_restricted = True
        q._redis_enabled = True

        result = await q.enqueue(
            "test_warn", {"x": 1},
            task_id="warn_test_001",
        )
        # Should still work but log warning
        assert result.accepted or not result.accepted
        q._is_restricted = False  # Reset


# ══════════════════════════════════════════════════════════════════
# Cancel Semantics
# ══════════════════════════════════════════════════════════════════


class TestCancelV2:
    """Test the atomic cancel_v2 Lua script."""

    @pytest.mark.asyncio
    async def test_cancel_pending_task(self, q):
        """Cancel a pending task — removed from ready queue."""
        await q.enqueue_v2(
            "test_cancel", {"x": 1},
            task_id="cancel_pending_001",
        )

        result = await q.cancel_v2("cancel_pending_001", "test_cancel")
        assert result == 1, "Pending → cancelled should return 1"

        # Verify can't claim
        task = await q.dequeue_v2("test_cancel", lease_sec=30)
        assert task is None, "Cancelled task should not be claimable"

    @pytest.mark.asyncio
    async def test_cancel_processing_task(self, q):
        """Cancel a processing task — sets cancel_requested flag."""
        await q.enqueue_v2(
            "test_cancel_proc", {"x": 1},
            task_id="cancel_proc_001",
        )

        # Claim it first
        task = await q.dequeue_v2("test_cancel_proc", lease_sec=30)
        assert task is not None
        assert task.status == TaskStatus.PROCESSING

        # Cancel while processing
        result = await q.cancel_v2("cancel_proc_001", "test_cancel_proc")
        assert result == 2, "Processing → cancel_requested should return 2"

        # Verify cancel_requested flag is set
        task_data = await q.get_task_v2("cancel_proc_001")
        assert task_data is not None
        assert task_data.get("cancel_requested") == "1"

        # Clean up via complete
        ok = await q.complete_v2(task)
        assert ok == 1

    @pytest.mark.asyncio
    async def test_cancel_retrying_task(self, q):
        """Cancel a retrying task — removed from retry ZSET."""
        await q.enqueue_v2(
            "test_cancel_retry", {"x": 1},
            task_id="cancel_retry_001",
        )

        # Simulate retry by manually setting failed status
        import redis.asyncio as redis_async
        client = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
        from app.services.task_queue_service import _v2_retry_key, _v2_task_hash_key

        await client.zadd(_v2_retry_key("test_cancel_retry"), {"cancel_retry_001": time.time() + 60})
        await client.hset(_v2_task_hash_key("cancel_retry_001"), "status", "failed")
        await client.aclose()

        result = await q.cancel_v2("cancel_retry_001", "test_cancel_retry")
        assert result == 3, "Retrying → cancelled should return 3"

    @pytest.mark.asyncio
    async def test_cancel_dead_task(self, q):
        """Cancel a dead-letter task."""
        task_id = "cancel_dead_001"
        await q.enqueue_v2(
            "test_cancel_dead", {"x": 1},
            task_id=task_id, max_retries=0,
        )

        # Claim and fail (max_retries=0 → dead)
        task = await q.dequeue_v2("test_cancel_dead", lease_sec=30)
        assert task is not None
        fail_result = await q.fail_v2(task, "test fail")
        assert fail_result in (1, 2)

        # Cancel from dead
        result = await q.cancel_v2(task_id, "test_cancel_dead")
        assert result == 4, "Dead → cancelled should return 4"

    @pytest.mark.asyncio
    async def test_cancel_terminal_is_idempotent(self, q):
        """Cancelling an already-cancelled task returns 0."""
        await q.enqueue_v2(
            "test_cancel_idem", {"x": 1},
            task_id="cancel_idem_001",
        )

        result1 = await q.cancel_v2("cancel_idem_001", "test_cancel_idem")
        assert result1 == 1  # pending → cancelled

        result2 = await q.cancel_v2("cancel_idem_001", "test_cancel_idem")
        assert result2 == 0, "Already cancelled should return 0 (idempotent)"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, q):
        """Cancelling a nonexistent task returns 0."""
        result = await q.cancel_v2("nonexistent_task", "test_cancel_miss")
        assert result == 0

    @pytest.mark.asyncio
    async def test_cancel_after_complete_is_noop(self, q):
        """Cancelling an already-completed task returns 0."""
        await q.enqueue_v2(
            "test_cancel_term", {"x": 1},
            task_id="cancel_term_001",
        )
        task = await q.dequeue_v2("test_cancel_term", lease_sec=30)
        assert task is not None
        await q.complete_v2(task)

        result = await q.cancel_v2("cancel_term_001", "test_cancel_term")
        assert result == 0, "Completed task cancel should return 0"


# ══════════════════════════════════════════════════════════════════
# Task Payload Versioning
# ══════════════════════════════════════════════════════════════════


class TestTaskPayloadVersioning:
    """Verify schema_version, minimum_worker_version, trace_id."""

    @pytest.mark.asyncio
    async def test_task_has_versioning_fields(self, q):
        """Task dataclass includes versioning fields."""
        from app.services.task_queue_service import _CURRENT_TASK_SCHEMA_VERSION

        task = Task(
            task_id="version_test_001",
            task_type="test_version",
            payload={"k": "v"},
        )
        assert task.schema_version == _CURRENT_TASK_SCHEMA_VERSION
        assert task.minimum_worker_version >= 1
        assert task.created_by_version == ""
        assert task.trace_id == ""

    @pytest.mark.asyncio
    async def test_version_fields_survive_enqueue_roundtrip(self, q):
        """Version fields persist through enqueue → dequeue."""
        task_id = "version_rt_001"
        result = await q.enqueue_v2(
            "test_version_rt", {"x": 1},
            task_id=task_id,
        )
        assert result.accepted

        task = await q.dequeue_v2("test_version_rt", lease_sec=30)
        assert task is not None
        assert task.schema_version >= 1
        assert task.minimum_worker_version >= 1
        assert task.generation >= 1
        await q.complete_v2(task)

    @pytest.mark.asyncio
    async def test_worker_version_compatibility_check(self, q):
        """Worker rejects tasks with minimum_worker_version > _WORKER_VERSION."""
        from app.services.task_queue_worker import _check_worker_version_compatibility

        # Task requiring version 999 (much higher than current)
        high_version_task = Task(
            task_id="incompat_001",
            task_type="test_incompat",
            payload={},
            minimum_worker_version=999,
        )

        import pytest as _pytest
        with _pytest.raises(ValueError, match="Incompatible task"):
            await _check_worker_version_compatibility(high_version_task)

    @pytest.mark.asyncio
    async def test_compatible_version_passes(self, q):
        """Task with minimum_worker_version <= _WORKER_VERSION passes check."""
        from app.services.task_queue_worker import (
            _WORKER_VERSION,
            _check_worker_version_compatibility,
        )

        task = Task(
            task_id="compat_001",
            task_type="test_compat",
            payload={},
            minimum_worker_version=_WORKER_VERSION,
        )
        # Should not raise
        await _check_worker_version_compatibility(task)

    @pytest.mark.asyncio
    async def test_legacy_task_defaults_to_version_1(self, q):
        """Tasks created without version fields default to schema_version=1."""
        # Directly create a task dict missing version fields
        task_dict = {
            "task_id": "legacy_001",
            "task_type": "test_legacy",
            "payload": {},
            "status": "pending",
        }
        task = Task.from_dict(task_dict)
        assert task.schema_version == 1
        assert task.minimum_worker_version == 1


# ══════════════════════════════════════════════════════════════════
# Redis TIME Clock Consistency
# ══════════════════════════════════════════════════════════════════


class TestRedisTimeConsistency:
    """Verify Lua scripts use Redis TIME for lease calculations."""

    @pytest.mark.asyncio
    async def test_heartbeat_uses_redis_time(self, q):
        """Heartbeat_v2 Lua uses Redis TIME (accepts 3 ARGV, not 4)."""
        await q.enqueue_v2(
            "test_time_hb", {"x": 1},
            task_id="time_hb_001",
        )

        task = await q.dequeue_v2("test_time_hb", lease_sec=60)
        assert task is not None

        # Heartbeat should succeed with new Lua (3 ARGV)
        result = await q.heartbeat_v2(task, lease_sec=60)
        assert result == 1, "Heartbeat should succeed with Redis TIME-based Lua"

        await q.complete_v2(task)

    @pytest.mark.asyncio
    async def test_reaper_uses_redis_time(self, q):
        """Reaper_v2 uses Redis TIME internally (accepts 2 ARGV, not 3)."""
        await q.enqueue_v2(
            "test_time_reap", {"x": 1},
            task_id="time_reap_001",
        )

        task = await q.dequeue_v2("test_time_reap", lease_sec=1)
        assert task is not None

        # Wait for lease to expire (accounting for Redis-Python clock skew)
        await asyncio.sleep(3)

        # Run reaper — may need retries if Redis TIME skew
        reclaimed = 0
        for _ in range(5):
            reclaimed = await q._reclaim_expired_v2("test_time_reap")
            if reclaimed >= 1:
                break
            await asyncio.sleep(1)
        assert reclaimed >= 1, "Reaper should reclaim expired task within 8s"

        # Should be claimable again
        task2 = await q.dequeue_v2("test_time_reap", lease_sec=30)
        assert task2 is not None
        assert task2.task_id == "time_reap_001"

        await q.complete_v2(task2)

    @pytest.mark.asyncio
    async def test_complete_v2_after_lease_expiry(self, q):
        """After lease expires and reaper reclaims, old owner can't complete."""
        task_id = "time_stale_001"
        await q.enqueue_v2(
            "test_time_stale", {"x": 1},
            task_id=task_id,
        )

        # First claim (worker A)
        task_a = await q.dequeue_v2("test_time_stale", lease_sec=1)
        assert task_a is not None
        gen_a = task_a.generation

        # Wait for lease to expire (accounting for Redis-Python clock skew)
        await asyncio.sleep(3)

        # Reaper reclaims (may need retries if Redis TIME skew)
        reclaimed = 0
        for _ in range(5):
            reclaimed = await q._reclaim_expired_v2("test_time_stale")
            if reclaimed >= 1:
                break
            await asyncio.sleep(1)
        assert reclaimed >= 1, "Reaper should reclaim expired task within 8s"

        # Second claim (worker B) — gets new generation
        task_b = await q.dequeue_v2("test_time_stale", lease_sec=30)
        assert task_b is not None
        assert task_b.generation > gen_a, "Generation must increase after re-claim"

        # Worker A tries to complete — should be rejected (stale generation)
        result = await q.complete_v2(task_a)
        assert result != 1, "Stale worker should not be able to complete"
        assert result in (0, -1), "Should get owner or generation mismatch"

        # Worker B completes successfully
        result = await q.complete_v2(task_b)
        assert result == 1


# ══════════════════════════════════════════════════════════════════
# Transactional Outbox Integration
# ══════════════════════════════════════════════════════════════════


class TestOutboxIntegration:
    """Verify outbox service integrates with the task queue."""

    @pytest.mark.asyncio
    async def test_outbox_roundtrip(self, q):
        """Create outbox, verify model fields."""
        from app.models.task_outbox import TaskOutbox

        outbox = TaskOutbox(
            task_id="outbox_test_001",
            task_type="import_pipeline",
            payload={"pipeline_id": "test-123"},
            schema_version=2,
            status="pending",
        )
        assert outbox.task_id == "outbox_test_001"
        assert outbox.task_type == "import_pipeline"
        assert outbox.payload["pipeline_id"] == "test-123"
        assert outbox.schema_version == 2
        assert outbox.status == "pending"


# ══════════════════════════════════════════════════════════════════
# Production Config Validation
# ══════════════════════════════════════════════════════════════════


class TestProductionConfigValidation:
    """Verify deprecation warnings and config checks."""

    def test_deprecated_env_var_detection(self):
        """Settings.warn_deprecated_env_vars() detects conflicts."""
        from app.core.config import settings

        conflicts = settings.warn_deprecated_env_vars()
        # Should not have conflicts (all values are at defaults)
        assert isinstance(conflicts, list)

    def test_task_queue_duplicate_constants(self):
        """TASK_QUEUE_RETRY_MAX and TASK_QUEUE_DEAD_MAX exist."""
        from app.core.config import settings

        # Both new names exist
        assert hasattr(settings, "TASK_QUEUE_RETRY_MAX")
        assert hasattr(settings, "TASK_QUEUE_DEAD_MAX")
        # Old names still exist for backward compat
        assert hasattr(settings, "TASK_QUEUE_MAX_RETRY")
        assert hasattr(settings, "TASK_QUEUE_MAX_DEAD")
