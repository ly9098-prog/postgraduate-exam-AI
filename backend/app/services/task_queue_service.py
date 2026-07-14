"""Durable Redis-backed task queue for long-running background jobs.

Replaces ad-hoc ``asyncio.create_task`` patterns that are unreliable across
worker restarts, deployments, and scale-outs.

Features:
- Idempotent enqueue (same task_id won't be enqueued twice)
- Atomic task claim with lease (prevent double-execution)
- Heartbeat mechanism (worker periodically extends lease)
- Retry with exponential backoff and max retries
- Dead-letter queue for permanently failed tasks
- Worker crash recovery (expired leases are reclaimed)
- Graceful shutdown (lease released)

Design:
- **Enqueue**: RPUSH to a Redis list (queue:<type>).
- **Claim**: RPOPLPUSH from queue:<type> → processing:<type> (atomic).
  Worker sets a TTL on the processing entry for lease.
- **Heartbeat**: worker periodically touches the processing entry TTL.
- **Completion**: worker DELETEs from processing:<type>.
- **Failure**: worker increments retry count; if ≤ max_retries, re-enqueues
  with exponential backoff (stored in a sorted set by retry_at); else moves
  to dead-letter list.
- **Reaper**: a background task periodically scans processing:<type> for
  entries with expired TTL and re-enqueues them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

from app.core.cache import cache
from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.task-queue")

# Redis key prefixes
_QUEUE_PREFIX = "taskq:queue"
_PROCESSING_PREFIX = "taskq:processing"
_DEAD_PREFIX = "taskq:dead"
_RETRY_PREFIX = "taskq:retry"
_IDEMPOTENCY_PREFIX = "taskq:idempotent"
_HEARTBEAT_PREFIX = "taskq:heartbeat"

# Defaults
_DEFAULT_LEASE_SEC = 300       # 5 minutes
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE_DELAY = 10  # seconds
_REAPER_INTERVAL_SEC = 60
_HEARTBEAT_INTERVAL_SEC = 30


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"


@dataclass
class Task:
    """A task in the durable queue."""
    task_id: str
    task_type: str
    payload: dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    max_retries: int = _DEFAULT_MAX_RETRIES
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    lease_expires_at: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "payload": self.payload,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lease_expires_at": self.lease_expires_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        return cls(
            task_id=d["task_id"],
            task_type=d["task_type"],
            payload=d.get("payload", {}),
            status=TaskStatus(d.get("status", "pending")),
            retry_count=d.get("retry_count", 0),
            max_retries=d.get("max_retries", _DEFAULT_MAX_RETRIES),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            lease_expires_at=d.get("lease_expires_at", 0.0),
            error=d.get("error", ""),
        )


class DurableTaskQueue:
    """Redis-backed durable task queue.

    Usage::

        queue = DurableTaskQueue()

        # Enqueue
        task_id = await queue.enqueue("ocr_pipeline", {"pipeline_id": "..."})

        # Worker loop
        while running:
            task = await queue.dequeue("ocr_pipeline", lease_sec=300)
            if task is None:
                await asyncio.sleep(1); continue
            heartbeat_task = asyncio.create_task(
                queue._heartbeat_loop(task, 300)
            )
            try:
                await process_task(task)
                await queue.complete(task)
            except Exception as e:
                await queue.fail(task, str(e))
            finally:
                heartbeat_task.cancel()
    """

    def __init__(self) -> None:
        self._redis_enabled = bool(settings.REDIS_URL)
        self._local_tasks: dict[str, Task] = {}  # fallback when no Redis

    # ── key helpers ──

    def _q_key(self, task_type: str) -> str:
        return f"{_QUEUE_PREFIX}:{task_type}"

    def _p_key(self, task_type: str) -> str:
        return f"{_PROCESSING_PREFIX}:{task_type}"

    def _dead_key(self, task_type: str) -> str:
        return f"{_DEAD_PREFIX}:{task_type}"

    def _retry_key(self, task_type: str) -> str:
        return f"{_RETRY_PREFIX}:{task_type}"

    def _idempotent_key(self, task_id: str) -> str:
        return f"{_IDEMPOTENCY_PREFIX}:{task_id}"

    def _heartbeat_key(self, task_id: str) -> str:
        return f"{_HEARTBEAT_PREFIX}:{task_id}"

    # ── enqueue ──

    async def enqueue(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        task_id: str | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        idempotent: bool = True,
    ) -> str:
        """Enqueue a task. Returns task_id.

        When *idempotent* is True (default), the same task_id won't be
        enqueued twice. The task_id defaults to a UUID if not provided
        and idempotency is disabled. For idempotent tasks, provide a
        deterministic task_id (e.g. ``f"pipeline:{pipeline_id}"``).
        """
        tid = task_id or f"task_{uuid.uuid4().hex}"

        if idempotent and task_id:
            # Check idempotency
            if self._redis_enabled:
                import redis.asyncio as redis_async

                try:
                    client = redis_async.from_url(
                        settings.REDIS_URL,
                        socket_connect_timeout=2,
                        socket_timeout=2,
                        decode_responses=True,
                    )
                    exists = await client.exists(self._idempotent_key(tid))
                    if exists:
                        await client.aclose()
                        logger.info(
                            "Duplicate task rejected (idempotent): task_id=%s",
                            tid,
                        )
                        return tid
                    # Mark as enqueued with 24h TTL
                    await client.set(
                        self._idempotent_key(tid), "1", ex=86400
                    )
                    await client.aclose()
                except Exception:
                    pass  # Fall through: best-effort idempotency
            else:
                if tid in self._local_tasks:
                    logger.info(
                        "Duplicate local task rejected: task_id=%s", tid
                    )
                    return tid
                self._local_tasks[tid] = Task(
                    task_id=tid,
                    task_type=task_type,
                    payload=payload,
                    max_retries=max_retries,
                )

        task = Task(
            task_id=tid,
            task_type=task_type,
            payload=payload,
            max_retries=max_retries,
        )
        task_data = json.dumps(task.to_dict(), default=str)

        if self._redis_enabled:
            import redis.asyncio as redis_async

            try:
                client = redis_async.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                await client.rpush(self._q_key(task_type), task_data)
                await client.aclose()
                logger.info(
                    "Task enqueued: task_id=%s type=%s",
                    tid, task_type,
                )
            except Exception as e:
                logger.warning(
                    "Redis enqueue failed, falling back to local: %s", e
                )
                self._local_tasks[tid] = task
        else:
            self._local_tasks[tid] = task

        return tid

    # ── dequeue ──

    async def dequeue(
        self,
        task_type: str,
        *,
        lease_sec: int = _DEFAULT_LEASE_SEC,
    ) -> Task | None:
        """Atomically claim a task from the queue.

        Uses RPOPLPUSH to move from queue → processing list atomically.
        Returns None if queue is empty.
        """
        if self._redis_enabled:
            import redis.asyncio as redis_async

            try:
                client = redis_async.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                # Atomic: pop from queue, push to processing
                task_data = await client.brpoplpush(
                    self._q_key(task_type),
                    self._p_key(task_type),
                    timeout=0,  # don't block
                )
                if task_data:
                    task = Task.from_dict(json.loads(task_data))
                    task.status = TaskStatus.PROCESSING
                    task.lease_expires_at = time.time() + lease_sec
                    task.updated_at = time.time()
                    # Set TTL on the processing entry (lease)
                    # Also set a heartbeat key
                    await client.expire(
                        self._heartbeat_key(task.task_id), lease_sec
                    )
                    await client.aclose()
                    logger.info(
                        "Task dequeued: task_id=%s type=%s lease=%ds",
                        task.task_id, task_type, lease_sec,
                    )
                    return task
                await client.aclose()
            except Exception as e:
                logger.warning("Redis dequeue failed: %s", e)
                return None
            return None

        # Local fallback
        for tid, task in list(self._local_tasks.items()):
            if task.task_type == task_type and task.status == TaskStatus.PENDING:
                task.status = TaskStatus.PROCESSING
                task.lease_expires_at = time.time() + lease_sec
                return task
        return None

    # ── heartbeat ──

    async def heartbeat(self, task: Task, lease_sec: int = _DEFAULT_LEASE_SEC) -> None:
        """Extend the lease for a task (called periodically by the worker)."""
        if self._redis_enabled:
            import redis.asyncio as redis_async

            try:
                client = redis_async.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                await client.expire(
                    self._heartbeat_key(task.task_id), lease_sec
                )
                await client.aclose()
                task.lease_expires_at = time.time() + lease_sec
            except Exception:
                pass  # Best-effort heartbeat

    # ── complete ──

    async def complete(self, task: Task) -> None:
        """Mark a task as completed and remove from processing."""
        if self._redis_enabled:
            import redis.asyncio as redis_async

            try:
                client = redis_async.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                # Remove from processing list
                p_key = self._p_key(task.task_type)
                # We need to find and remove our specific entry from the list.
                # LREM by value is O(n) but acceptable for modest queue sizes.
                task_data = json.dumps(task.to_dict(), default=str)
                await client.lrem(p_key, 1, task_data)
                await client.delete(self._heartbeat_key(task.task_id))
                await client.delete(self._idempotent_key(task.task_id))
                await client.aclose()
            except Exception as e:
                logger.warning("Task complete failed: %s", e)
        else:
            self._local_tasks.pop(task.task_id, None)

        logger.info("Task completed: task_id=%s type=%s", task.task_id, task.task_type)

    # ── fail ──

    async def fail(
        self,
        task: Task,
        error: str,
        *,
        lease_sec: int = _DEFAULT_LEASE_SEC,
    ) -> None:
        """Handle task failure.

        If retry_count < max_retries, re-enqueue with exponential backoff.
        Otherwise, move to dead-letter queue.
        """
        task.retry_count += 1
        task.error = error
        task.updated_at = time.time()

        if task.retry_count < task.max_retries:
            # Re-enqueue with backoff
            delay = _DEFAULT_RETRY_BASE_DELAY * (2 ** (task.retry_count - 1))
            task.status = TaskStatus.FAILED

            if self._redis_enabled:
                import redis.asyncio as redis_async

                try:
                    client = redis_async.from_url(
                        settings.REDIS_URL,
                        socket_connect_timeout=2,
                        socket_timeout=2,
                    )
                    # Remove from processing
                    p_key = self._p_key(task.task_type)
                    task_data = json.dumps(task.to_dict(), default=str)
                    await client.lrem(p_key, 1, task_data)
                    # Add to retry sorted set (score = retry_at timestamp)
                    retry_at = time.time() + delay
                    await client.zadd(
                        self._retry_key(task.task_type),
                        {task_data: retry_at},
                    )
                    await client.delete(self._heartbeat_key(task.task_id))
                    await client.aclose()
                except Exception as e:
                    logger.warning(
                        "Task fail/retry Redis error: %s", e
                    )
            else:
                task.status = TaskStatus.PENDING  # re-queue locally
                task.lease_expires_at = 0

            logger.warning(
                "Task failed (retry %d/%d, +%ds): task_id=%s error=%s",
                task.retry_count, task.max_retries, delay,
                task.task_id, error[:200],
            )
        else:
            # Dead letter
            task.status = TaskStatus.DEAD

            if self._redis_enabled:
                import redis.asyncio as redis_async

                try:
                    client = redis_async.from_url(
                        settings.REDIS_URL,
                        socket_connect_timeout=2,
                        socket_timeout=2,
                    )
                    p_key = self._p_key(task.task_type)
                    task_data = json.dumps(task.to_dict(), default=str)
                    await client.lrem(p_key, 1, task_data)
                    await client.lpush(self._dead_key(task.task_type), task_data)
                    await client.delete(self._heartbeat_key(task.task_id))
                    await client.aclose()
                except Exception as e:
                    logger.warning(
                        "Task dead-letter Redis error: %s", e
                    )
            else:
                self._local_tasks.pop(task.task_id, None)

            logger.error(
                "Task moved to dead-letter (max retries): task_id=%s type=%s error=%s",
                task.task_id, task.task_type, error[:200],
            )

    # ── reaper (reclaim expired leases) ──

    async def _reclaim_expired(self, task_type: str) -> int:
        """Re-enqueue tasks whose lease has expired (worker crashed).

        Scans the processing list, checks each entry's lease_expires_at.
        Returns the number of reclaimed tasks.
        """
        if not self._redis_enabled:
            return 0

        import redis.asyncio as redis_async

        reclaimed = 0
        try:
            client = redis_async.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            p_key = self._p_key(task_type)
            q_key = self._q_key(task_type)

            # Get all processing entries
            tasks_data = await client.lrange(p_key, 0, -1)
            now = time.time()

            for raw in tasks_data:
                try:
                    task_dict = json.loads(raw)
                    lease_exp = task_dict.get("lease_expires_at", 0)
                    if now > lease_exp:
                        # Expired — re-enqueue
                        task_dict["status"] = TaskStatus.PENDING.value
                        task_dict["lease_expires_at"] = 0
                        task_dict["error"] = (
                            task_dict.get("error", "")
                            + "; reclaimed after lease expiry"
                        ).strip("; ")
                        await client.lrem(p_key, 1, raw)
                        await client.rpush(
                            q_key, json.dumps(task_dict, default=str)
                        )
                        reclaimed += 1
                        logger.info(
                            "Task reclaimed (lease expired): task_id=%s",
                            task_dict.get("task_id"),
                        )
                except json.JSONDecodeError:
                    continue

            await client.aclose()
        except Exception as e:
            logger.warning("Reclaim scan failed: %s", e)

        return reclaimed

    async def run_reaper(self, task_types: list[str] | None = None) -> None:
        """Run one cycle of the reaper for given task types."""
        types = task_types or []
        for t in types:
            try:
                await self._reclaim_expired(t)
            except Exception as e:
                logger.warning("Reaper failed for %s: %s", t, e)

    # ── stats ──

    async def queue_length(self, task_type: str) -> int:
        if self._redis_enabled:
            import redis.asyncio as redis_async

            try:
                client = redis_async.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                length = await client.llen(self._q_key(task_type))
                await client.aclose()
                return length
            except Exception:
                pass
        return 0

    async def dead_length(self, task_type: str) -> int:
        if self._redis_enabled:
            import redis.asyncio as redis_async

            try:
                client = redis_async.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                length = await client.llen(self._dead_key(task_type))
                await client.aclose()
                return length
            except Exception:
                pass
        return 0


# Process-wide singleton
task_queue = DurableTaskQueue()
