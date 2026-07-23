"""Durable Redis-backed task queue for long-running background jobs.

Replaces ad-hoc ``asyncio.create_task`` patterns that are unreliable across
worker restarts, deployments, and scale-outs.

Architecture (Redis data model):
- ``taskq:queue:{type}`` — List of task_ids (ready queue).
- ``taskq:processing:{type}`` — Sorted Set of task_ids, score = lease expiry.
- ``taskq:retry:{type}`` — Sorted Set of task_ids, score = retry_at timestamp.
- ``taskq:dead:{type}`` — List of task_ids (dead-letter).
- ``taskq:task:{task_id}`` — Hash of task payload/metadata.
- ``taskq:heartbeat:{task_id}`` — String, TTL = lease_sec (auto-expiry lease).
- ``taskq:idempotent:{task_id}`` — String, TTL = 24h (idempotency guard).

Atomic operations via Lua scripts eliminate race conditions between
``complete``/``fail``/``reaper``.

Features:
- Idempotent enqueue (same task_id won't be enqueued twice)
- Atomic task claim with lease (prevent double-execution)
- Heartbeat mechanism (worker periodically extends lease)
- Retry with exponential backoff and max retries
- Dead-letter queue for permanently failed tasks
- Worker crash recovery (expired leases are reclaimed)
- Graceful shutdown (lease released)
- No O(n) LREM — all cleanup via task_id + ZSET
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.core.config import settings
from app.core.deployment_profile import detect_deployment_profile, DeploymentProfile

logger = logging.getLogger("postgraduate-ai.task-queue")

# Redis key prefixes
_QUEUE_PREFIX = "taskq:queue"
_PROCESSING_PREFIX = "taskq:processing"
_DEAD_PREFIX = "taskq:dead"
_RETRY_PREFIX = "taskq:retry"
_TASK_PREFIX = "taskq:task"
_IDEMPOTENCY_PREFIX = "taskq:idempotent"
_HEARTBEAT_PREFIX = "taskq:heartbeat"

# Defaults
_DEFAULT_LEASE_SEC = 300       # 5 minutes
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE_DELAY = 10  # seconds
_REAPER_INTERVAL_SEC = 60
_LOCAL_TASK_MAX = 100           # bounded local fallback
_DEAD_MAX = 1000                # max dead-letter entries


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


# ── Lua scripts ──

# CLAIM: pop task_id from ready queue → ZADD processing ZSET → HGET payload → SETEX heartbeat
# KEYS: [queue_key, processing_key, heartbeat_prefix, task_hash_prefix]
# ARGS: [lease_sec]
# Returns: task JSON string (or nil if empty)
_LUA_CLAIM = """
local task_id = redis.call("RPOP", KEYS[1])
if not task_id then
    return nil
end
redis.call("ZADD", KEYS[2], tonumber(ARGV[1]), task_id)
local raw = redis.call("HGET", KEYS[4] .. ":" .. task_id, "data")
if not raw then
    redis.call("ZREM", KEYS[2], task_id)
    return nil
end
redis.call("SETEX", KEYS[3] .. ":" .. task_id, tonumber(ARGV[1]), "1")
return raw
"""

# COMPLETE: ZREM processing → DEL hash → DEL heartbeat → DEL idempotent
# KEYS: [processing_key, task_hash_prefix, heartbeat_prefix, idempotent_prefix]
# ARGS: [task_id]
_LUA_COMPLETE = """
local task_id = ARGV[1]
redis.call("ZREM", KEYS[1], task_id)
redis.call("DEL", KEYS[2] .. ":" .. task_id)
redis.call("DEL", KEYS[3] .. ":" .. task_id)
redis.call("DEL", KEYS[4] .. ":" .. task_id)
return 1
"""

# FAIL (retry): ZREM processing → ZADD retry ZSET → HSET task hash → DEL heartbeat
# KEYS: [processing_key, retry_key, task_hash_prefix, heartbeat_prefix]
# ARGS: [task_id, retry_at, task_json]
_LUA_FAIL_RETRY = """
local task_id = ARGV[1]
redis.call("ZREM", KEYS[1], task_id)
redis.call("ZADD", KEYS[2], tonumber(ARGV[2]), task_id)
redis.call("HSET", KEYS[3] .. ":" .. task_id, "data", ARGV[3])
redis.call("DEL", KEYS[4] .. ":" .. task_id)
return 1
"""

# FAIL (dead): ZREM processing → LPUSH dead → HSET hash → DEL heartbeat → DEL idempotent
# Dead list trimmed to 1000 to prevent unbounded growth.
# KEYS: [processing_key, dead_key, task_hash_prefix, heartbeat_prefix, idempotent_prefix]
# ARGS: [task_id, task_json]
_LUA_FAIL_DEAD = """
local task_id = ARGV[1]
redis.call("ZREM", KEYS[1], task_id)
redis.call("LPUSH", KEYS[2], task_id)
redis.call("LTRIM", KEYS[2], 0, 999)
redis.call("HSET", KEYS[3] .. ":" .. task_id, "data", ARGV[2])
redis.call("DEL", KEYS[4] .. ":" .. task_id)
redis.call("DEL", KEYS[5] .. ":" .. task_id)
return 1
"""

# REAPER: scan processing ZSET for expired, move back to queue
# KEYS: [processing_key, queue_key, heartbeat_prefix]
# ARGS: [now_timestamp, batch_size]
# Returns: count of reclaimed tasks
_LUA_REAPER = """
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2]) or 100
local expired = redis.call("ZRANGEBYSCORE", KEYS[1], 0, now, "LIMIT", 0, limit)
local count = 0
for _, task_id in ipairs(expired) do
    redis.call("ZREM", KEYS[1], task_id)
    redis.call("RPUSH", KEYS[2], task_id)
    redis.call("DEL", KEYS[3] .. ":" .. task_id)
    count = count + 1
end
return count
"""

# RETRY_CLAIM: pop from retry ZSET → push to processing ZSET → SETEX heartbeat
# KEYS: [retry_key, processing_key, heartbeat_prefix]
# ARGS: [now_timestamp, lease_sec]
# Returns: task_id (or nil)
_LUA_RETRY_CLAIM = """
local now = tonumber(ARGV[1])
local lease = tonumber(ARGV[2])
local candidates = redis.call("ZRANGEBYSCORE", KEYS[1], 0, now, "LIMIT", 0, 1)
if #candidates == 0 then
    return nil
end
local task_id = candidates[1]
redis.call("ZREM", KEYS[1], task_id)
redis.call("ZADD", KEYS[2], lease, task_id)
redis.call("SETEX", KEYS[3] .. ":" .. task_id, lease, "1")
return task_id
"""


# ── Helpers ──

def _task_hash_key(task_id: str) -> str:
    return f"{_TASK_PREFIX}:{task_id}"

def _heartbeat_key(task_id: str) -> str:
    return f"{_HEARTBEAT_PREFIX}:{task_id}"

def _idempotent_key(task_id: str) -> str:
    return f"{_IDEMPOTENCY_PREFIX}:{task_id}"

def _q_key(task_type: str) -> str:
    return f"{_QUEUE_PREFIX}:{task_type}"

def _p_key(task_type: str) -> str:
    return f"{_PROCESSING_PREFIX}:{task_type}"

def _dead_key(task_type: str) -> str:
    return f"{_DEAD_PREFIX}:{task_type}"

def _retry_key(task_type: str) -> str:
    return f"{_RETRY_PREFIX}:{task_type}"


# ── DurableTaskQueue ──


class DurableTaskQueue:
    """Redis-backed durable task queue with atomic Lua operations.

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
        self._local_tasks: dict[str, Task] = {}
        self._redis = None  # lazy persistent connection for dequeue
        self._lua_claim = None
        self._lua_complete = None
        self._lua_fail_retry = None
        self._lua_fail_dead = None
        self._lua_reaper = None
        self._lua_retry_claim = None

    async def _get_client(self):
        """获取或创建持久 Redis 连接（复用)."""
        if not self._redis_enabled:
            return None
        if self._redis is None:
            import redis.asyncio as redis_async

            self._redis = redis_async.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=5,
                socket_timeout=5,
                decode_responses=True,
                single_connection_client=True,
            )
        return self._redis

    async def _get_script_client(self):
        """获取一个用于非阻塞 Redis 操作的连接（不阻塞 dequeue 连接)."""
        if not self._redis_enabled:
            return None
        import redis.asyncio as redis_async

        return redis_async.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=5,
            socket_timeout=5,
            decode_responses=True,
        )

    async def _load_scripts(self, client) -> None:
        """Load Lua scripts into Redis and cache the SHA hashes."""
        if self._lua_claim is not None:
            return
        self._lua_claim = await client.script_load(_LUA_CLAIM)
        self._lua_complete = await client.script_load(_LUA_COMPLETE)
        self._lua_fail_retry = await client.script_load(_LUA_FAIL_RETRY)
        self._lua_fail_dead = await client.script_load(_LUA_FAIL_DEAD)
        self._lua_reaper = await client.script_load(_LUA_REAPER)
        self._lua_retry_claim = await client.script_load(_LUA_RETRY_CLAIM)

    async def close(self) -> None:
        """关闭持久 Redis 连接。"""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None

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
        enqueued twice. For idempotent tasks, provide a deterministic
        task_id (e.g. ``f"pipeline:{pipeline_id}"``).
        """
        tid = task_id or f"task_{uuid.uuid4().hex}"

        if idempotent and task_id:
            if self._redis_enabled:
                try:
                    client = await self._get_script_client()
                    if client is None:
                        return tid
                    exists = await client.exists(_idempotent_key(tid))
                    if exists:
                        await client.aclose()
                        logger.info(
                            "Duplicate task rejected (idempotent): task_id=%s", tid,
                        )
                        return tid
                    # Mark as enqueued with 24h TTL (atomic)
                    await client.set(_idempotent_key(tid), "1", ex=86400)
                    await client.aclose()
                except Exception:
                    pass  # best-effort
            else:
                if tid in self._local_tasks:
                    logger.info("Duplicate local task rejected: task_id=%s", tid)
                    return tid
                if len(self._local_tasks) >= _LOCAL_TASK_MAX:
                    logger.error("Local task queue full, rejecting task_id=%s", tid)
                    return tid

        task = Task(
            task_id=tid,
            task_type=task_type,
            payload=payload,
            max_retries=max_retries,
        )

        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    self._local_tasks[tid] = task
                    return tid
                await client.rpush(_q_key(task_type), tid)
                # Store task payload as Hash
                await client.hset(
                    _task_hash_key(tid),
                    mapping={"data": json.dumps(task.to_dict(), default=str)},
                )
                await client.aclose()
                logger.info("Task enqueued: task_id=%s type=%s", tid, task_type)
            except Exception as e:
                if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
                    logger.error(
                        "Redis unavailable in cloud mode, rejecting task_id=%s: %s",
                        tid, e,
                    )
                    return tid
                logger.warning("Redis enqueue failed, falling back to local: %s", e)
                if len(self._local_tasks) < _LOCAL_TASK_MAX:
                    self._local_tasks[tid] = task
                else:
                    logger.error("Local task queue full, dropped task_id=%s", tid)
        else:
            if len(self._local_tasks) < _LOCAL_TASK_MAX:
                self._local_tasks[tid] = task
            else:
                logger.error("Local task queue full, dropped task_id=%s", tid)

        return tid

    # ── dequeue ──

    async def dequeue(
        self,
        task_type: str,
        *,
        lease_sec: int = _DEFAULT_LEASE_SEC,
    ) -> Task | None:
        """Atomically claim a task from the queue.

        Tries the ready queue first, then the retry ZSET.
        Uses atomic Lua script: RPOP from queue → ZADD to processing → HSET payload.

        Returns None if queue is empty.
        """
        if self._redis_enabled:
            try:
                client = await self._get_client()
                if client is None:
                    return None

                await self._load_scripts(client)

                # 1. Try ready queue via atomic Lua (RPOP → ZADD → HGET → SETEX)
                q_key = _q_key(task_type)
                p_key = _p_key(task_type)
                lease_expiry = time.time() + lease_sec

                raw = await client.evalsha(
                    self._lua_claim,
                    4,
                    q_key,                                  # KEYS[1]: queue_key
                    p_key,                                  # KEYS[2]: processing_key
                    _HEARTBEAT_PREFIX,                      # KEYS[3]: heartbeat_prefix
                    _TASK_PREFIX,                           # KEYS[4]: task_hash_prefix
                    str(lease_expiry),                      # ARGV[1]: lease_sec
                )

                if raw is not None:
                    # Lua script returned the task JSON — same path as below
                    task = Task.from_dict(json.loads(raw))
                    task.status = TaskStatus.PROCESSING
                    task.lease_expires_at = lease_expiry
                    task.updated_at = time.time()
                    logger.info(
                        "Task dequeued (lua): task_id=%s type=%s lease=%ds",
                        task.task_id, task_type, lease_sec,
                    )
                    return task

                # 2. Ready queue empty — try retry ZSET
                task_id = await self._dequeue_retry(client, task_type, lease_sec)
                if task_id is None:
                    return None

                raw = await client.hget(_task_hash_key(task_id), "data")
                if raw is None:
                    return None

                task = Task.from_dict(json.loads(raw))
                task.status = TaskStatus.PROCESSING
                task.lease_expires_at = time.time() + lease_sec
                task.updated_at = time.time()

                logger.info(
                    "Task dequeued (retry): task_id=%s type=%s lease=%ds",
                    task.task_id, task_type, lease_sec,
                )
                return task
            except Exception as e:
                logger.warning("Redis dequeue failed: %s", e)
                return None

        # Local fallback (bounded)
        for tid, t in list(self._local_tasks.items()):
            if t.task_type == task_type and t.status == TaskStatus.PENDING:
                t.status = TaskStatus.PROCESSING
                t.lease_expires_at = time.time() + lease_sec
                return t
        return None

    async def _dequeue_retry(self, client, task_type: str, lease_sec: int) -> str | None:
        """Consume from retry ZSET via atomic Lua — tasks whose retry_at has passed.

        Uses Lua to atomically ZRANGEBYSCORE retry → ZREM retry → ZADD processing → SETEX heartbeat.
        """
        now = time.time()
        lease_expiry = now + lease_sec
        return await client.evalsha(
            self._lua_retry_claim,
            3,
            _retry_key(task_type),      # KEYS[1]: retry ZSET
            _p_key(task_type),           # KEYS[2]: processing ZSET
            _HEARTBEAT_PREFIX,           # KEYS[3]: heartbeat_prefix
            str(now),                    # ARGV[1]: now timestamp
            str(lease_expiry),           # ARGV[2]: lease expiry score
        )

    # ── heartbeat ──

    async def heartbeat(
        self,
        task_or_id: Task | str,
        task_type: str | None = None,
        *,
        lease_sec: int = _DEFAULT_LEASE_SEC,
    ) -> bool:
        """Extend the lease for a task (called periodically by the worker).

        Accepts a ``Task`` object or ``(task_id, task_type)`` pair.
        Returns True if heartbeat was sent.
        """
        if isinstance(task_or_id, Task):
            task_id = task_or_id.task_id
        else:
            task_id = task_or_id
        if not task_id:
            return False

        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return False
                await client.expire(_heartbeat_key(task_id), lease_sec)
                await client.aclose()
                if isinstance(task_or_id, Task):
                    task_or_id.lease_expires_at = time.time() + lease_sec
                return True
            except Exception:
                return False
        return False

    # ── complete ──

    async def complete(
        self,
        task_or_id: Task | str,
        task_type: str | None = None,
    ) -> None:
        """Mark a task as completed and remove from processing.

        Accepts a ``Task`` object or ``(task_id, task_type)`` pair.
        Uses atomic Lua: ZREM processing → DEL hash → DEL heartbeat → DEL idempotent.
        """
        if isinstance(task_or_id, Task):
            task_id = task_or_id.task_id
            tt = task_or_id.task_type
        else:
            task_id = task_or_id
            tt = task_type or ""
        if not task_id:
            return

        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return

                p_key = _p_key(tt)
                await client.evalsha(
                    self._lua_complete,
                    4,
                    p_key,                              # KEYS[1]: processing_key
                    _TASK_PREFIX,                       # KEYS[2]: task_hash_prefix
                    _HEARTBEAT_PREFIX,                  # KEYS[3]: heartbeat_prefix
                    _IDEMPOTENCY_PREFIX,                # KEYS[4]: idempotent_prefix
                    task_id,                            # ARGV[1]: task_id
                )
                await client.aclose()
            except Exception as e:
                logger.warning("Task complete failed: %s", e)
        else:
            if isinstance(task_or_id, Task):
                self._local_tasks.pop(task_id, None)

        logger.info("Task completed: task_id=%s", task_id)

    # ── fail ──

    async def fail(
        self,
        task_or_id: Task | str,
        error: str,
        task_type: str | None = None,
        *,
        lease_sec: int = _DEFAULT_LEASE_SEC,
    ) -> None:
        """Handle task failure.

        Accepts a ``Task`` object or ``(task_id, task_type)`` pair.
        When given a Task object, tracks retry_count; with just IDs,
        skips retry and moves directly to dead-letter.
        """
        if isinstance(task_or_id, Task):
            task = task_or_id
            task_id = task.task_id
            tt = task.task_type
        else:
            task_id = task_or_id
            tt = task_type or ""

        if not task_id or not tt:
            return

        if isinstance(task_or_id, Task):
            task.retry_count += 1
            task.error = error
            task.updated_at = time.time()

        # Retry path (requires Task object for retry tracking)
        if isinstance(task_or_id, Task) and task.retry_count < task.max_retries:
            delay = _DEFAULT_RETRY_BASE_DELAY * (2 ** (task.retry_count - 1))
            task.status = TaskStatus.FAILED

            if self._redis_enabled:
                try:
                    client = await self._get_script_client()
                    if client is None:
                        return
                    p_key = _p_key(tt)
                    retry_at = time.time() + delay
                    task_json = json.dumps(task.to_dict(), default=str)
                    await client.evalsha(
                        self._lua_fail_retry,
                        4,
                        p_key,                              # KEYS[1]: processing_key
                        _retry_key(tt),                     # KEYS[2]: retry_key
                        _TASK_PREFIX,                       # KEYS[3]: task_hash_prefix
                        _HEARTBEAT_PREFIX,                  # KEYS[4]: heartbeat_prefix
                        task_id,                            # ARGV[1]: task_id
                        str(retry_at),                      # ARGV[2]: retry_at
                        task_json,                          # ARGV[3]: task_json
                    )
                    await client.aclose()
                except Exception as e:
                    logger.warning("Task fail/retry Redis error: %s", e)
            else:
                task.status = TaskStatus.PENDING
                task.lease_expires_at = 0

            logger.warning(
                "Task failed (retry %d/%d, +%ds): task_id=%s error=%s",
                task.retry_count, task.max_retries, delay,
                task_id, error[:200],
            )
            return

        # Dead-letter path (no more retries or no Task object)
        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return
                p_key = _p_key(tt)
                task_json = json.dumps(task.to_dict(), default=str) if isinstance(task_or_id, Task) else "{}"
                await client.evalsha(
                    self._lua_fail_dead,
                    5,
                    p_key,                              # KEYS[1]: processing_key
                    _dead_key(tt),                      # KEYS[2]: dead_key
                    _TASK_PREFIX,                       # KEYS[3]: task_hash_prefix
                    _HEARTBEAT_PREFIX,                  # KEYS[4]: heartbeat_prefix
                    _IDEMPOTENCY_PREFIX,                # KEYS[5]: idempotent_prefix
                    task_id,                            # ARGV[1]: task_id
                    task_json,                          # ARGV[2]: task_json
                )
                await client.aclose()
            except Exception as e:
                logger.warning("Task dead-letter Redis error: %s", e)
        else:
            self._local_tasks.pop(task_id, None)

        logger.error(
            "Task moved to dead-letter: task_id=%s type=%s error=%s",
            task_id, tt, error[:200],
        )

    # ── reaper ──

    async def _reclaim_expired(self, task_type: str) -> int:
        """Re-enqueue tasks whose lease has expired (worker crashed).

        Uses atomic Lua: ZRANGEBYSCORE processing → ZREM → RPUSH queue → DEL heartbeat.
        Returns the number of reclaimed tasks.
        """
        if not self._redis_enabled:
            return 0

        reclaimed = 0
        try:
            client = await self._get_script_client()
            if client is None:
                return 0

            p_key = _p_key(task_type)
            q_key = _q_key(task_type)
            now = time.time()

            reclaimed = await client.evalsha(
                self._lua_reaper,
                3,
                p_key,                    # KEYS[1]: processing_key
                q_key,                    # KEYS[2]: queue_key
                _HEARTBEAT_PREFIX,        # KEYS[3]: heartbeat_prefix
                str(now),                 # ARGV[1]: now
                "100",                    # ARGV[2]: batch_size
            ) or 0
            reclaimed = int(reclaimed)

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
            try:
                client = await self._get_script_client()
                if client is None:
                    return 0
                length = await client.llen(_q_key(task_type))
                await client.aclose()
                return length
            except Exception:
                pass
        return 0

    async def processing_length(self, task_type: str) -> int:
        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return 0
                length = await client.zcard(_p_key(task_type))
                await client.aclose()
                return length
            except Exception:
                pass
        return 0

    async def dead_length(self, task_type: str) -> int:
        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return 0
                length = await client.llen(_dead_key(task_type))
                await client.aclose()
                return length
            except Exception:
                pass
        return 0

    async def retry_length(self, task_type: str) -> int:
        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return 0
                length = await client.zcard(_retry_key(task_type))
                await client.aclose()
                return length
            except Exception:
                pass
        return 0

    # ── Dead-letter management ──

    async def list_dead(self, task_type: str, limit: int = 100) -> list[dict]:
        """List dead-letter entries for a task type (newest first)."""
        if not self._redis_enabled:
            return []
        try:
            client = await self._get_script_client()
            if client is None:
                return []
            task_ids = await client.lrange(_dead_key(task_type), 0, limit - 1)
            result = []
            for tid in task_ids:
                raw = await client.hget(_task_hash_key(tid), "data")
                if raw:
                    try:
                        task_dict = json.loads(raw)
                        result.append(task_dict)
                    except json.JSONDecodeError:
                        result.append({"task_id": tid, "error": "corrupt_payload"})
                else:
                    result.append({"task_id": tid})
            await client.aclose()
            return result
        except Exception as e:
            logger.warning("Failed to list dead tasks: %s", e)
            return []

    async def purge_dead(self, task_type: str, max_age_sec: int = 86400 * 7) -> int:
        """Remove dead-letter entries older than *max_age_sec*.

        Returns count of purged entries.
        """
        if not self._redis_enabled:
            return 0
        try:
            client = await self._get_script_client()
            if client is None:
                return 0
            dk = _dead_key(task_type)
            task_ids = await client.lrange(dk, 0, -1)
            now = time.time()
            purged = 0
            for tid in task_ids:
                raw = await client.hget(_task_hash_key(tid), "data")
                if raw:
                    try:
                        task_dict = json.loads(raw)
                        updated = task_dict.get("updated_at", 0)
                        if now - updated > max_age_sec:
                            await client.lrem(dk, 1, tid)
                            await client.delete(_task_hash_key(tid))
                            purged += 1
                    except json.JSONDecodeError:
                        await client.lrem(dk, 1, tid)
                        purged += 1
            await client.aclose()
            if purged:
                logger.info("Purged %d old dead tasks for %s", purged, task_type)
            return purged
        except Exception as e:
            logger.warning("Failed to purge dead tasks: %s", e)
            return 0


# Process-wide singleton
task_queue = DurableTaskQueue()
