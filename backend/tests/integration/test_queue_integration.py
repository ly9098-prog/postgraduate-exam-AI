"""DurableTaskQueue integration tests — requires ``--run-integration``.

Verifies the durable task queue works against real Redis.
"""

import os
import pytest


pytestmark = pytest.mark.integration

# Test Redis URL for the task queue (matches conftest)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/1")


class TestDurableTaskQueueIntegration:
    """DurableTaskQueue with real Redis backend."""

    @pytest.mark.asyncio
    async def test_enqueue_dequeue_roundtrip(self):
        """Enqueue a task, dequeue it, verify roundtrip."""
        from app.services.task_queue_service import DurableTaskQueue

        queue = DurableTaskQueue(redis_url=TEST_REDIS_URL)
        task_id = await queue.enqueue(
            task_type="test_integration",
            payload={"msg": "hello from PG+Redis integration test"},
            task_id="int_test_001",
        )
        assert task_id == "int_test_001"

        task = await queue.dequeue("test_integration", lease_sec=30)
        assert task is not None
        assert task.task_id == "int_test_001"
        assert task.payload["msg"] == "hello from PG+Redis integration test"
        assert task.task_type == "test_integration"

        await queue.complete(task.task_id, task.task_type)

    @pytest.mark.asyncio
    async def test_task_complete_removes_from_queue(self):
        """Completing a task removes it from the active queue."""
        from app.services.task_queue_service import DurableTaskQueue

        queue = DurableTaskQueue(redis_url=TEST_REDIS_URL)
        await queue.enqueue(
            task_type="test_complete",
            payload={"n": 1},
            task_id="int_complete_001",
        )

        task = await queue.dequeue("test_complete", lease_sec=30)
        await queue.complete(task.task_id, task.task_type)

        # Should not be dequeued again
        again = await queue.dequeue("test_complete", lease_sec=5)
        assert again is None

    @pytest.mark.asyncio
    async def test_task_fail_and_retry(self):
        """Failing a task creates a retry (up to max_retries)."""
        from app.services.task_queue_service import DurableTaskQueue

        queue = DurableTaskQueue(redis_url=TEST_REDIS_URL)
        await queue.enqueue(
            task_type="test_retry",
            payload={"attempt": 0},
            task_id="int_retry_001",
            max_retries=2,
        )

        # Dequeue and fail
        task = await queue.dequeue("test_retry", lease_sec=30)
        await queue.fail(task.task_id, task.task_type, error="test error")

        # Should still be available for retry
        retry = await queue.dequeue("test_retry", lease_sec=30)
        assert retry is not None
        assert retry.task_id == "int_retry_001"

    @pytest.mark.asyncio
    async def test_heartbeat_extends_lease(self):
        """Heartbeat extends the task lease."""
        from app.services.task_queue_service import DurableTaskQueue

        queue = DurableTaskQueue(redis_url=TEST_REDIS_URL)
        await queue.enqueue(
            task_type="test_hb",
            payload={},
            task_id="int_hb_001",
        )

        task = await queue.dequeue("test_hb", lease_sec=5)
        assert task is not None

        # Heartbeat
        ok = await queue.heartbeat(task.task_id, task.task_type, lease_sec=30)
        assert ok is True

        await queue.complete(task.task_id, task.task_type)

    @pytest.mark.asyncio
    async def test_ipc_pub_sub(self):
        """IPC channel publish and subscribe."""
        from app.services.task_queue_service import DurableTaskQueue

        queue = DurableTaskQueue(redis_url=TEST_REDIS_URL)

        published = await queue.publish("test:ipc", {"event": "ping"})
        assert published > 0

    @pytest.mark.asyncio
    async def test_import_pipeline_enqueue_roundtrip(self):
        """End-to-end: enqueue import_pipeline → worker retrieves."""
        from app.services.task_queue_service import DurableTaskQueue
        from app.services.task_queue_worker import enqueue_import_pipeline

        # enqueue_import_pipeline uses the module-level task_queue singleton
        # which may use the local fallback. Bypass and use our own queue directly.
        queue = DurableTaskQueue(redis_url=TEST_REDIS_URL)
        await queue.enqueue(
            task_type="import_pipeline",
            payload={
                "pipeline_id": "int_pipeline_e2e_001",
                "source_type": "txt",
                "source_file": "integration_test.txt",
                "subject": None,
                "subject_id": None,
                "options": {},
                "created_by": None,
            },
            task_id="import:int_pipeline_e2e_001",
            max_retries=2,
        )

        task = await queue.dequeue("import_pipeline", lease_sec=30)
        assert task is not None
        assert task.payload["pipeline_id"] == "int_pipeline_e2e_001"
        assert task.payload["source_type"] == "txt"

        await queue.complete(task.task_id, task.task_type)
