"""Durable Redis-backed task queue with atomic Lua operations and owner fencing.

Architecture (Redis data model):
- ``taskq:queue:{type}`` — List of task_ids (ready queue).
- ``taskq:processing:{type}`` — Sorted Set of task_ids, score = lease expiry.
- ``taskq:retry:{type}`` — Sorted Set of task_ids, score = retry_at timestamp.
- ``taskq:dead:{type}`` — List of task_ids (dead-letter, LRIM to 1000).
- ``taskq:task:{task_id}`` — Hash of task payload/metadata (TTL 7d in dead, 24h after complete).
- ``taskq:heartbeat:{task_id}`` — String = owner_token, TTL = lease_sec.
- ``taskq:idempotent:{task_id}`` — String, TTL = 24h (idempotency guard).

Atomic operations via Lua scripts. All operations carry an owner_token
that prevents stale workers from modifying tasks claimed by another owner.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import redis.asyncio as redis_async
import redis.exceptions as redis_exc

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

logger = logging.getLogger("postgraduate-ai.task-queue")

# Redis key prefixes
_QUEUE_PREFIX = "taskq:queue"
_PROCESSING_PREFIX = "taskq:processing"
_DEAD_PREFIX = "taskq:dead"
_RETRY_PREFIX = "taskq:retry"
_CORRUPT_PREFIX = "taskq:corrupt"
_TASK_PREFIX = "taskq:task"
_IDEMPOTENCY_PREFIX = "taskq:idempotent"
_HEARTBEAT_PREFIX = "taskq:heartbeat"

# Defaults
_DEFAULT_LEASE_SEC = 300       # 5 minutes
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE_DELAY = 10  # seconds
_REAPER_INTERVAL_SEC = 60
_LOCAL_TASK_MAX = 100           # bounded local fallback (dev only)
_DEAD_MAX = 1000                # max dead-letter entries
_CORRUPT_MAX = 100              # max corrupt entries
_IDEMPOTENT_TTL = 86400 * 7      # 7d — matches dead hash TTL, ensures idempotency outlives all terminal states
_COMPLETED_TTL = 86400            # 24h retention for completed task hashes
_DEAD_HASH_TTL = 86400 * 7        # 7d retention for dead task hashes


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"
    CORRUPT = "corrupt"


@dataclass
class EnqueueResult:
    """Result of an enqueue attempt.

    Attributes:
        accepted: True if the task was accepted into the queue.
        task_id: The task ID (None if not accepted and no task was created).
        reason: Machine-readable reason code for rejection.
        retry_after: Recommended seconds before the caller should retry.
    """
    accepted: bool = True
    task_id: str | None = None
    reason: str = ""
    retry_after: int = 0

    def __bool__(self) -> bool:
        return self.accepted


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
    owner_token: str = ""
    error: str = ""
    generation: int = 0

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
            "owner_token": self.owner_token,
            "error": self.error,
            "generation": self.generation,
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
            owner_token=d.get("owner_token", ""),
            error=d.get("error", ""),
            generation=d.get("generation", 0),
        )


def _get_max_ready(task_type: str) -> int:
    """Get max ready queue length for a task type from settings."""
    mapping = {
        "import_pipeline": settings.TASK_QUEUE_MAX_READY_IMPORT,
        "image_pipeline": settings.TASK_QUEUE_MAX_READY_IMPORT,
        "excel_pipeline": settings.TASK_QUEUE_MAX_READY_IMPORT,
        "resume_pipeline": settings.TASK_QUEUE_MAX_READY_IMPORT,
        "admin_resume": settings.TASK_QUEUE_MAX_READY_IMPORT,
        "ocr_pipeline": settings.TASK_QUEUE_MAX_READY_OCR,
        "prewarm_analysis": settings.TASK_QUEUE_MAX_READY_AI,
        "formula_batch": settings.TASK_QUEUE_MAX_READY_FORMULA,
        "batch_image": settings.TASK_QUEUE_MAX_READY_BATCH_IMAGE,
    }
    return mapping.get(task_type, settings.TASK_QUEUE_MAX_READY_DEFAULT)


# ── Lua scripts ──

# ENQUEUE with idempotency check AND ready queue capacity limit.
# KEYS: [queue_key, task_hash_prefix, idempotent_prefix]
# ARGS: [task_id, task_json, idempotent_ttl_sec, max_ready]
# Returns: task_id on success, "__duplicate__" if idempotent exists,
#          "__queue_full__" if at capacity, nil on error
_LUA_ENQUEUE = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local idem_ttl = tonumber(ARGV[3])
local max_ready = tonumber(ARGV[4])

-- 1. Check idempotent key
local exists = redis.call("EXISTS", KEYS[3] .. ":" .. task_id)
if exists == 1 then
    return "__duplicate__"
end

-- 2. Check ready queue capacity
local ready_len = redis.call("LLEN", KEYS[1])
if max_ready > 0 and ready_len >= max_ready then
    return "__queue_full__"
end

-- 3. Set idempotent guard first (prevents races on concurrent enqueue)
redis.call("SETEX", KEYS[3] .. ":" .. task_id, idem_ttl, "1")

-- 4. Write task payload + authoritative fields
redis.call("HSET", KEYS[2] .. ":" .. task_id, "data", task_json,
    "status", "pending",
    "owner_token", "",
    "generation", 0,
    "retry_count", 0)

-- 5. Push to ready queue
redis.call("RPUSH", KEYS[1], task_id)

return task_id
"""

# ENQUEUE_NON_IDEMPOTENT: HSET payload → RPUSH ready (no idempotency check)
# KEYS: [queue_key, task_hash_prefix]
# ARGS: [task_id, task_json]
_LUA_ENQUEUE_NON_IDEMPOTENT = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local max_ready = tonumber(ARGV[3])

-- Check ready queue capacity
local ready_len = redis.call("LLEN", KEYS[1])
if max_ready > 0 and ready_len >= max_ready then
    return "__queue_full__"
end

redis.call("HSET", KEYS[2] .. ":" .. task_id, "data", task_json,
    "status", "pending")
redis.call("RPUSH", KEYS[1], task_id)

return task_id
"""

# CLAIM: RPOP ready → ZADD processing → HGET payload → SETEX heartbeat + update hash
# Returns payload, owner_token, and generation.
# KEYS: [queue_key, processing_key, heartbeat_prefix, task_hash_prefix]
# ARGS: [lease_expiry_abs, lease_ttl_rel, owner_token, execution_generation]
# Returns: {raw_payload, owner_token, generation} or nil
_LUA_CLAIM = """
local task_id = redis.call("RPOP", KEYS[1])
if not task_id then
    return nil
end

local owner_token = ARGV[3]
local generation = tonumber(ARGV[4]) or 1
local lease_expiry = tonumber(ARGV[1])
local lease_ttl = tonumber(ARGV[2])

-- Read payload
local raw = redis.call("HGET", KEYS[4] .. ":" .. task_id, "data")
if not raw then
    -- Payload missing — don't requeue, mark as corrupt
    redis.call("HSET", KEYS[4] .. ":" .. task_id, "status", "corrupt")
    return nil
end

-- Add to processing ZSET with absolute lease expiry
redis.call("ZADD", KEYS[2], lease_expiry, task_id)

-- Set heartbeat key with relative TTL and owner_token as value
redis.call("SETEX", KEYS[3] .. ":" .. task_id, lease_ttl, owner_token)

-- Update authoritative state fields in task hash
redis.call("HSET", KEYS[4] .. ":" .. task_id,
    "owner_token", owner_token,
    "generation", generation,
    "status", "processing",
    "lease_expires_at", lease_expiry)

return {raw, owner_token, tostring(generation)}
"""

# HEARTBEAT: verify owner_token → update processing ZSET score → extend heartbeat TTL
# KEYS: [processing_key, heartbeat_prefix]
# ARGS: [task_id, new_lease_expiry, lease_ttl, owner_token]
# Returns: 1 on success, 0 on owner mismatch
_LUA_HEARTBEAT = """
local task_id = ARGV[1]
local new_expiry = tonumber(ARGV[2])
local lease_ttl = tonumber(ARGV[3])
local owner_token = ARGV[4]

-- Verify owner
local stored = redis.call("GET", KEYS[2] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end

-- Update processing ZSET lease score
redis.call("ZADD", KEYS[1], new_expiry, task_id)

-- Extend heartbeat key TTL
redis.call("EXPIRE", KEYS[2] .. ":" .. task_id, lease_ttl)

return 1
"""

# COMPLETE: verify owner_token → ZREM processing → ZREM retry → HSET completed → DEL heartbeat
# KEYS: [processing_key, retry_key, task_hash_prefix, heartbeat_prefix]
# ARGS: [task_id, owner_token, completed_ttl]
_LUA_COMPLETE = """
local task_id = ARGV[1]
local owner_token = ARGV[2]
local ttl = tonumber(ARGV[3])

-- Verify owner via heartbeat key
local stored = redis.call("GET", KEYS[4] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end

-- Remove from processing
redis.call("ZREM", KEYS[1], task_id)

-- Clean up retry ZSET (in case it was re-enqueued)
redis.call("ZREM", KEYS[2], task_id)

-- Set authoritative status to completed
redis.call("HSET", KEYS[3] .. ":" .. task_id, "status", "completed")
redis.call("EXPIRE", KEYS[3] .. ":" .. task_id, ttl)

-- Delete heartbeat only (idempotent key preserved for dedup)
redis.call("DEL", KEYS[4] .. ":" .. task_id)

return 1
"""

# FAIL_RETRY: verify owner_token → ZREM processing → ZADD retry → update status fields → DEL heartbeat
# KEYS: [processing_key, retry_key, task_hash_prefix, heartbeat_prefix]
# ARGS: [task_id, retry_at, task_json, owner_token, retry_count, error]
_LUA_FAIL_RETRY = """
local task_id = ARGV[1]
local retry_at = tonumber(ARGV[2])
local task_json = ARGV[3]
local owner_token = ARGV[4]
local retry_count = tonumber(ARGV[5]) or 1
local error_msg = ARGV[6] or ""

-- Verify owner
local stored = redis.call("GET", KEYS[4] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end

-- Remove from processing
redis.call("ZREM", KEYS[1], task_id)

-- Add to retry ZSET
redis.call("ZADD", KEYS[2], retry_at, task_id)

-- Update task hash (JSON data for backward compat + authoritative fields)
redis.call("HSET", KEYS[3] .. ":" .. task_id, "data", task_json,
    "status", "failed",
    "retry_count", retry_count,
    "error", error_msg)

-- Delete heartbeat (idempotent stays for dedup)
redis.call("DEL", KEYS[4] .. ":" .. task_id)

return 1
"""

# FAIL_DEAD: verify owner → ZREM processing → LPUSH dead → LTRIM → HSET status=dead + TTL → DEL heartbeat
# KEYS: [processing_key, dead_key, task_hash_prefix, heartbeat_prefix]
# ARGS: [task_id, task_json, owner_token, dead_max]
_LUA_FAIL_DEAD = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local owner_token = ARGV[3]
local dead_max = tonumber(ARGV[4]) or 1000

-- Verify owner
local stored = redis.call("GET", KEYS[4] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end

-- Remove from processing
redis.call("ZREM", KEYS[1], task_id)

-- Add to dead list (trim prevents unbounded growth)
redis.call("LPUSH", KEYS[2], task_id)
redis.call("LTRIM", KEYS[2], 0, dead_max - 1)

-- Update task hash (data + authoritative status = dead)
redis.call("HSET", KEYS[3] .. ":" .. task_id, "data", task_json)
redis.call("HSET", KEYS[3] .. ":" .. task_id, "status", "dead")
redis.call("EXPIRE", KEYS[3] .. ":" .. task_id, 604800)

-- Delete heartbeat only (idempotent key preserved for dedup)
redis.call("DEL", KEYS[4] .. ":" .. task_id)

return 1
"""

# REAPER: scan processing ZSET → heartbeat alive? → check status/payload → reclaim or mark corrupt
# KEYS: [processing_key, queue_key, heartbeat_prefix, task_hash_prefix]
# ARGS: [now_timestamp, batch_size]
# Returns: count of reclaimed tasks
_LUA_REAPER = """
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2]) or 100
local expired = redis.call("ZRANGEBYSCORE", KEYS[1], 0, now, "LIMIT", 0, limit)
local count = 0
for _, task_id in ipairs(expired) do
    -- Check if worker is still alive via heartbeat key
    local hb_exists = redis.call("EXISTS", KEYS[3] .. ":" .. task_id)
    if hb_exists == 0 then
        -- Check task hash status — skip if terminal (stale ZSET entry)
        local status = redis.call("HGET", KEYS[4] .. ":" .. task_id, "status")
        if status and (status == "completed" or status == "dead" or status == "corrupt") then
            redis.call("ZREM", KEYS[1], task_id)
        else
            -- Check payload exists before reclaiming
            local payload_exists = redis.call("HEXISTS", KEYS[4] .. ":" .. task_id, "data")
            if payload_exists == 1 then
                redis.call("ZREM", KEYS[1], task_id)
                redis.call("RPUSH", KEYS[2], task_id)
                count = count + 1
            else
                redis.call("ZREM", KEYS[1], task_id)
                redis.call("HSET", KEYS[4] .. ":" .. task_id, "status", "corrupt")
            end
        end
    end
end
return count
"""

# RETRY_CLAIM: ZRANGEBYSCORE retry → validate payload/status → ZADD processing + heartbeat
# Returns payload inline — no separate HGET needed.
# KEYS: [retry_key, processing_key, heartbeat_prefix, task_hash_prefix]
# ARGS: [now_timestamp, lease_expiry_abs, lease_ttl_rel, owner_token, execution_generation]
# Returns: {task_id, owner_token, generation, raw_payload} or nil
_LUA_RETRY_CLAIM = """
local now = tonumber(ARGV[1])
local lease_expiry = tonumber(ARGV[2])
local lease_ttl = tonumber(ARGV[3])
local owner_token = ARGV[4]
local generation = tonumber(ARGV[5]) or 1

local candidates = redis.call("ZRANGEBYSCORE", KEYS[1], 0, now, "LIMIT", 0, 1)
if #candidates == 0 then
    return nil
end

local task_id = candidates[1]

-- Validate payload exists before moving
local raw = redis.call("HGET", KEYS[4] .. ":" .. task_id, "data")
if not raw then
    redis.call("ZREM", KEYS[1], task_id)
    redis.call("HSET", KEYS[4] .. ":" .. task_id, "status", "corrupt")
    return nil
end

-- Check if task is in terminal state (stale retry entry)
local status = redis.call("HGET", KEYS[4] .. ":" .. task_id, "status")
if status and (status == "completed" or status == "dead") then
    redis.call("ZREM", KEYS[1], task_id)
    return nil
end

redis.call("ZREM", KEYS[1], task_id)
redis.call("ZADD", KEYS[2], lease_expiry, task_id)
redis.call("SETEX", KEYS[3] .. ":" .. task_id, lease_ttl, owner_token)

-- Update authoritative state fields
redis.call("HSET", KEYS[4] .. ":" .. task_id,
    "owner_token", owner_token,
    "generation", generation,
    "status", "processing",
    "lease_expires_at", lease_expiry)

return {task_id, owner_token, tostring(generation), raw}
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

def _corrupt_key(task_type: str) -> str:
    return f"{_CORRUPT_PREFIX}:{task_type}"


# ── Queue metrics ──

queue_metrics: dict[str, int] = {
    "ready": 0,
    "processing": 0,
    "retry": 0,
    "dead": 0,
    "corrupt": 0,
    "execution_duration": 0,
    "lease_renewal_failure": 0,
    "duplicate_enqueue_prevented": 0,
    "reaper_reclaimed": 0,
    "owner_fencing_rejected": 0,
    "enqueue_rejected": 0,
    "dead_purge_count": 0,
    "corrupt_cleaned": 0,
}


# ── DurableTaskQueue ──


class DurableTaskQueue:
    """Redis-backed durable task queue with atomic Lua operations and owner fencing.

    All state-modifying operations (enqueue, claim, complete, fail, heartbeat)
    are atomic via Lua scripts. Each claim generates a unique owner_token;
    subsequent operations verify the token to prevent stale worker interference.

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

    Production/cloud_api mode requires Redis. When Redis is unavailable,
    enqueue returns None (the caller should return 503).
    """

    def __init__(self, redis_url: str | None = None) -> None:
        """Initialize the task queue.

        Args:
            redis_url: Override Redis URL. If None, uses settings.REDIS_URL.
                       Useful for tests that need a different Redis instance.
        """
        self._redis_url = redis_url or settings.REDIS_URL
        self._redis_enabled = bool(self._redis_url)
        self._is_restricted = (
            detect_deployment_profile() == DeploymentProfile.CLOUD_API
            or settings.APP_ENV == "production"
        )
        self._local_tasks: dict[str, Task] = {}
        self._redis = None  # lazy persistent connection for dequeue
        self._lua_enqueue = None
        self._lua_enqueue_non_idempotent = None
        self._lua_claim = None
        self._lua_heartbeat = None
        self._lua_complete = None
        self._lua_fail_retry = None
        self._lua_fail_dead = None
        self._lua_reaper = None
        self._lua_retry_claim = None

    @property
    def _allow_local_fallback(self) -> bool:
        """Local in-memory fallback allowed only when:
        - NOT production/cloud_api environment, AND
        - ALLOW_IN_MEMORY_TASK_QUEUE=true is explicitly set.
        """
        if self._is_restricted:
            return False
        return settings.ALLOW_IN_MEMORY_TASK_QUEUE if hasattr(settings, "ALLOW_IN_MEMORY_TASK_QUEUE") else False

    async def _get_client(self):
        """Get persistent Redis connection (reused for blocking dequeue)."""
        if not self._redis_enabled:
            return None
        if self._redis is None:
            self._redis = redis_async.from_url(
                self._redis_url,
                socket_connect_timeout=5,
                socket_timeout=5,
                decode_responses=True,
                single_connection_client=True,
            )
        return self._redis

    async def _get_script_client(self):
        """Get a short-lived Redis connection for non-blocking operations."""
        if not self._redis_enabled:
            return None
        return redis_async.from_url(
            self._redis_url,
            socket_connect_timeout=5,
            socket_timeout=5,
            decode_responses=True,
        )

    async def _load_scripts(self, client) -> None:
        """Load Lua scripts into Redis and cache SHA hashes."""
        if self._lua_enqueue is not None:
            return
        self._lua_enqueue = await client.script_load(_LUA_ENQUEUE)
        self._lua_enqueue_non_idempotent = await client.script_load(_LUA_ENQUEUE_NON_IDEMPOTENT)
        self._lua_claim = await client.script_load(_LUA_CLAIM)
        self._lua_heartbeat = await client.script_load(_LUA_HEARTBEAT)
        self._lua_complete = await client.script_load(_LUA_COMPLETE)
        self._lua_fail_retry = await client.script_load(_LUA_FAIL_RETRY)
        self._lua_fail_dead = await client.script_load(_LUA_FAIL_DEAD)
        self._lua_reaper = await client.script_load(_LUA_REAPER)
        self._lua_retry_claim = await client.script_load(_LUA_RETRY_CLAIM)

    async def close(self) -> None:
        """Close the persistent Redis connection."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception as e:
                logger.warning("Error closing task queue Redis connection: %s", e)
            self._redis = None

    # ── NOSCRIPT recovery ──

    async def _evalsha_or_reload(self, client, sha_name: str, num_keys: int, *args) -> Any:
        """Call evalsha, reloading the script on NOSCRIPT error."""
        sha = getattr(self, sha_name, None)
        if sha is None:
            await self._load_scripts(client)
            sha = getattr(self, sha_name, None)
        try:
            return await client.evalsha(sha, num_keys, *args)
        except redis_exc.NoScriptError:
            # SCRIPT FLUSH or restart — all scripts were evicted. Reload everything.
            self._lua_enqueue = None
            self._lua_enqueue_non_idempotent = None
            self._lua_claim = None
            self._lua_heartbeat = None
            self._lua_complete = None
            self._lua_fail_retry = None
            self._lua_fail_dead = None
            self._lua_reaper = None
            self._lua_retry_claim = None
            await self._load_scripts(client)
            sha = getattr(self, sha_name, None)
            return await client.evalsha(sha, num_keys, *args)

    # ── enqueue ──

    async def enqueue(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        task_id: str | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        idempotent: bool = True,
    ) -> EnqueueResult:
        """Enqueue a task. Returns EnqueueResult with accepted/reason.

        In production/cloud_api mode, returns ``EnqueueResult(accepted=False)``
        with an appropriate reason when Redis is unavailable or at capacity.
        """
        tid = task_id or f"task_{uuid.uuid4().hex}"

        task = Task(
            task_id=tid,
            task_type=task_type,
            payload=payload,
            max_retries=max_retries,
        )
        task_json = json.dumps(task.to_dict(), default=str)

        max_ready = _get_max_ready(task_type)

        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return EnqueueResult(accepted=False, task_id=None, reason="redis_unavailable", retry_after=30)
                await self._load_scripts(client)

                if idempotent and task_id:
                    result = await self._evalsha_or_reload(
                        client, "_lua_enqueue", 3,
                        _q_key(task_type),        # KEYS[1]: queue_key
                        _TASK_PREFIX,              # KEYS[2]: task_hash_prefix
                        _IDEMPOTENCY_PREFIX,       # KEYS[3]: idempotent_prefix
                        tid,                       # ARGV[1]: task_id
                        task_json,                 # ARGV[2]: task_json
                        str(_IDEMPOTENT_TTL),      # ARGV[3]: idempotent_ttl
                        str(max_ready),            # ARGV[4]: max_ready
                    )
                else:
                    result = await self._evalsha_or_reload(
                        client, "_lua_enqueue_non_idempotent", 2,
                        _q_key(task_type),        # KEYS[1]: queue_key
                        _TASK_PREFIX,              # KEYS[2]: task_hash_prefix
                        tid,                       # ARGV[1]: task_id
                        task_json,                 # ARGV[2]: task_json
                        str(max_ready),            # ARGV[3]: max_ready
                    )

                await client.aclose()

                if result == "__duplicate__":
                    logger.info("Duplicate task rejected (idempotent): task_id=%s", tid)
                    queue_metrics["duplicate_enqueue_prevented"] += 1
                    return EnqueueResult(accepted=True, task_id=tid, reason="duplicate")

                if result == "__queue_full__":
                    logger.warning("Queue full, rejected: task_id=%s type=%s", tid, task_type)
                    queue_metrics["enqueue_rejected"] += 1
                    return EnqueueResult(accepted=False, task_id=None, reason="queue_full", retry_after=30)

                if result is None:
                    logger.error("Enqueue failed (nil result): task_id=%s type=%s", tid, task_type)
                    queue_metrics["enqueue_rejected"] += 1
                    return EnqueueResult(accepted=False, task_id=None, reason="internal_error", retry_after=30)

                logger.info("Task enqueued: task_id=%s type=%s", tid, task_type)
                return EnqueueResult(accepted=True, task_id=tid)

            except redis_exc.ConnectionError:
                if not self._allow_local_fallback:
                    logger.error("Redis connection error, rejecting enqueue task_id=%s", tid)
                    queue_metrics["enqueue_rejected"] += 1
                    return EnqueueResult(accepted=False, task_id=None, reason="redis_unavailable", retry_after=30)
                logger.warning("Redis enqueue failed, fallen back to local: task_id=%s", tid)

            except Exception as e:
                if not self._allow_local_fallback:
                    logger.error("Redis enqueue failed (no fallback): %s", e)
                    queue_metrics["enqueue_rejected"] += 1
                    return EnqueueResult(accepted=False, task_id=None, reason="enqueue_failed", retry_after=30)
                logger.warning("Redis enqueue failed, falling back to local: %s", e)

        # Local fallback (dev only, bounded)
        if self._allow_local_fallback:
            if tid in self._local_tasks:
                return EnqueueResult(accepted=True, task_id=tid)
            if len(self._local_tasks) >= _LOCAL_TASK_MAX:
                logger.error("Local task queue full, rejected task_id=%s", tid)
                queue_metrics["enqueue_rejected"] += 1
                return EnqueueResult(accepted=False, task_id=None, reason="queue_full", retry_after=30)
            self._local_tasks[tid] = task
            return EnqueueResult(accepted=True, task_id=tid)

        return EnqueueResult(accepted=False, task_id=None, reason="no_backend")

    # ── dequeue ──

    async def dequeue(
        self,
        task_type: str,
        *,
        lease_sec: int = _DEFAULT_LEASE_SEC,
    ) -> Task | None:
        """Atomically claim a task from the queue.

        Tries the ready queue first, then the retry ZSET.
        Uses atomic Lua with owner_token and execution_generation.

        Returns None if queue is empty or Redis unavailable.
        """
        if self._redis_enabled:
            try:
                client = await self._get_client()
                if client is None:
                    return None
                await self._load_scripts(client)

                # 1. Try ready queue
                q_key = _q_key(task_type)
                p_key = _p_key(task_type)
                lease_expiry = time.time() + lease_sec
                owner_token = uuid.uuid4().hex
                generation = int(time.time() * 1000)  # monotonic generation

                result = await self._evalsha_or_reload(
                    client, "_lua_claim", 4,
                    q_key,                    # KEYS[1]: queue_key
                    p_key,                    # KEYS[2]: processing_key
                    _HEARTBEAT_PREFIX,        # KEYS[3]: heartbeat_prefix
                    _TASK_PREFIX,             # KEYS[4]: task_hash_prefix
                    str(lease_expiry),        # ARGV[1]: lease_expiry
                    str(lease_sec),           # ARGV[2]: lease_ttl
                    owner_token,              # ARGV[3]: owner_token
                    str(generation),          # ARGV[4]: execution_generation
                )

                if result is not None:
                    raw_payload, stored_token, stored_gen = result
                    task = Task.from_dict(json.loads(raw_payload))
                    task.status = TaskStatus.PROCESSING
                    task.lease_expires_at = lease_expiry
                    task.owner_token = stored_token or owner_token
                    task.generation = int(stored_gen or generation)
                    task.updated_at = time.time()
                    logger.info(
                        "Task dequeued: task_id=%s type=%s lease=%ds gen=%d",
                        task.task_id, task_type, lease_sec, task.generation,
                    )
                    return task

                # 2. Retry ZSET (payload returned inline from Lua)
                retry_data = await self._dequeue_retry(
                    client, task_type, lease_sec, generation,
                )
                if retry_data is None:
                    return None

                raw_payload, task_id, rtoken, rgen = retry_data
                task = Task.from_dict(json.loads(raw_payload))
                task.status = TaskStatus.PROCESSING
                task.lease_expires_at = time.time() + lease_sec
                task.owner_token = rtoken
                task.generation = int(rgen or generation)
                task.updated_at = time.time()

                logger.info(
                    "Task dequeued (retry): task_id=%s type=%s lease=%ds gen=%d",
                    task.task_id, task_type, lease_sec, task.generation,
                )
                return task

            except redis_exc.ConnectionError:
                logger.warning("Redis dequeue failed (connection): task_type=%s", task_type)
                return None
            except Exception as e:
                logger.warning("Redis dequeue failed: %s", e)
                return None

        # Local fallback (dev only)
        if self._allow_local_fallback:
            for tid, t in list(self._local_tasks.items()):
                if t.task_type == task_type and t.status == TaskStatus.PENDING:
                    t.status = TaskStatus.PROCESSING
                    t.lease_expires_at = time.time() + lease_sec
                    t.owner_token = uuid.uuid4().hex
                    return t
        return None

    async def _dequeue_retry(
        self, client, task_type: str, lease_sec: int, generation: int,
    ) -> tuple[str, str, str, str] | None:
        """Atomically claim from retry ZSET.

        Returns (raw_payload, task_id, owner_token, gen) or None.
        Payload is validated inside Lua to avoid ghosts.
        """
        now = time.time()
        lease_expiry = now + lease_sec
        owner_token = uuid.uuid4().hex

        result = await self._evalsha_or_reload(
            client, "_lua_retry_claim", 4,
            _retry_key(task_type),      # KEYS[1]: retry ZSET
            _p_key(task_type),           # KEYS[2]: processing ZSET
            _HEARTBEAT_PREFIX,           # KEYS[3]: heartbeat_prefix
            _TASK_PREFIX,               # KEYS[4]: task_hash_prefix
            str(now),                    # ARGV[1]: now
            str(lease_expiry),           # ARGV[2]: lease_expiry
            str(lease_sec),              # ARGV[3]: lease_ttl
            owner_token,                 # ARGV[4]: owner_token
            str(generation),             # ARGV[5]: execution_generation
        )

        if result is not None:
            task_id, rtoken, rgen, raw_payload = result
            return raw_payload, task_id, rtoken or owner_token, rgen or str(generation)
        return None

    # ── heartbeat ──

    async def heartbeat(
        self,
        task_or_id: Task | str,
        *,
        task_type: str | None = None,
        lease_sec: int = _DEFAULT_LEASE_SEC,
    ) -> bool:
        """Extend the lease for a task.

        Atomic Lua: verifies owner_token, updates processing ZSET score,
        and extends heartbeat key TTL.

        Accepts a ``Task`` object or ``(task_id, task_type, owner_token)`` tuple.
        Returns True if heartbeat was accepted. Returns False if owner
        mismatch (stale worker) — caller should stop processing.

        When given a bare task_id without owner_token, falls back to simple
        SETEX (legacy compatibility, no fencing).
        """
        if isinstance(task_or_id, Task):
            task_id = task_or_id.task_id
            token = task_or_id.owner_token
            task_type = task_or_id.task_type
        elif isinstance(task_or_id, tuple):
            task_id, tt_hint, token = task_or_id
            task_type = task_type or tt_hint
        else:
            task_id = task_or_id
            token = ""

        if not task_id or not task_type:
            return False

        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return False
                await self._load_scripts(client)

                if token:
                    new_expiry = time.time() + lease_sec
                    result = await self._evalsha_or_reload(
                        client, "_lua_heartbeat", 2,
                        _p_key(task_type or ""),   # KEYS[1]: processing_key
                        _HEARTBEAT_PREFIX,          # KEYS[2]: heartbeat_prefix
                        task_id,                    # ARGV[1]: task_id
                        str(new_expiry),             # ARGV[2]: new_lease_expiry
                        str(lease_sec),              # ARGV[3]: lease_ttl
                        token,                       # ARGV[4]: owner_token
                    )
                    await client.aclose()

                    if result == 0:
                        logger.warning(
                            "Heartbeat rejected (owner mismatch): task_id=%s", task_id,
                        )
                        queue_metrics["lease_renewal_failure"] += 1
                        queue_metrics["owner_fencing_rejected"] += 1
                        return False

                    # Update in-memory Task object if available
                    if isinstance(task_or_id, Task):
                        task_or_id.lease_expires_at = new_expiry
                    return True
                else:
                    # Legacy path (no owner_token) — just extend TTL
                    await client.expire(_heartbeat_key(task_id), lease_sec)
                    await client.aclose()
                    return True

            except redis_exc.ConnectionError:
                return False
            except Exception:
                return False

        return False

    # ── complete ──

    async def complete(
        self,
        task_or_id: Task | str,
        *,
        task_type: str | None = None,
    ) -> bool:
        """Mark a task as completed.

        Atomic Lua with owner fencing: verifies owner_token, ZREM from
        processing, sets completed status, DEL heartbeat/idempotent.

        Returns True on success. Returns False if owner mismatch (fencing
        rejection) — caller should not retry as the task was re-assigned.
        """
        if isinstance(task_or_id, Task):
            task_id = task_or_id.task_id
            tt = task_or_id.task_type
            token = task_or_id.owner_token
        else:
            task_id = task_or_id
            tt = task_type or ""
            token = ""

        if not task_id or not tt:
            return False

        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return False
                await self._load_scripts(client)

                p_key = _p_key(tt)
                r_key = _retry_key(tt)
                result = await self._evalsha_or_reload(
                    client, "_lua_complete", 4,
                    p_key,                    # KEYS[1]: processing_key
                    r_key,                    # KEYS[2]: retry_key
                    _TASK_PREFIX,             # KEYS[3]: task_hash_prefix
                    _HEARTBEAT_PREFIX,        # KEYS[4]: heartbeat_prefix
                    task_id,                  # ARGV[1]: task_id
                    token,                    # ARGV[2]: owner_token
                    str(_COMPLETED_TTL),      # ARGV[3]: completed_ttl
                )
                await client.aclose()

                if result == 0:
                    logger.warning(
                        "Complete rejected (owner mismatch, fencing): task_id=%s", task_id,
                    )
                    queue_metrics["owner_fencing_rejected"] += 1
                    return False

                logger.info("Task completed: task_id=%s", task_id)
                return True

            except Exception as e:
                logger.warning("Task complete failed: %s", e)
                return False
        else:
            if self._allow_local_fallback and isinstance(task_or_id, Task):
                self._local_tasks.pop(task_id, None)
            return True

    # ── fail ──

    async def fail(
        self,
        task_or_id: Task | str,
        error: str,
        *,
        task_type: str | None = None,
        lease_sec: int = _DEFAULT_LEASE_SEC,
    ) -> bool:
        """Handle task failure with owner fencing.

        Accepts a ``Task`` object or ``(task_id, task_type)`` pair.
        When given a Task object, tracks retry_count and may retry.
        With just IDs, skips retry and moves directly to dead-letter.

        Returns True on success. Returns False if owner mismatch (fencing).
        """
        if isinstance(task_or_id, Task):
            task = task_or_id
            task_id = task.task_id
            tt = task.task_type
            token = task.owner_token
        else:
            task_id = task_or_id
            tt = task_type or ""
            token = ""

        if not task_id or not tt:
            return False

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
                        return False
                    await self._load_scripts(client)

                    p_key = _p_key(tt)
                    retry_at = time.time() + delay
                    task_json = json.dumps(task.to_dict(), default=str)

                    result = await self._evalsha_or_reload(
                        client, "_lua_fail_retry", 4,
                        p_key,                    # KEYS[1]: processing_key
                        _retry_key(tt),           # KEYS[2]: retry_key
                        _TASK_PREFIX,             # KEYS[3]: task_hash_prefix
                        _HEARTBEAT_PREFIX,        # KEYS[4]: heartbeat_prefix
                        task_id,                  # ARGV[1]: task_id
                        str(retry_at),            # ARGV[2]: retry_at
                        task_json,                # ARGV[3]: task_json
                        token,                    # ARGV[4]: owner_token
                        str(task.retry_count),    # ARGV[5]: retry_count
                        error[:200],              # ARGV[6]: error
                    )
                    await client.aclose()

                    if result == 0:
                        logger.warning(
                            "Fail/retry rejected (owner mismatch): task_id=%s", task_id,
                        )
                        queue_metrics["owner_fencing_rejected"] += 1
                        return False

                except Exception as e:
                    logger.warning("Task fail/retry Redis error: %s", e)
                    return False
            else:
                if self._allow_local_fallback:
                    task.status = TaskStatus.PENDING
                    task.lease_expires_at = 0

            logger.warning(
                "Task failed (retry %d/%d, +%ds): task_id=%s error=%s",
                task.retry_count, task.max_retries, delay,
                task_id, error[:200],
            )
            return True

        # Dead-letter path (no more retries or no Task object)
        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return False
                await self._load_scripts(client)

                p_key = _p_key(tt)
                task_json = json.dumps(
                    task.to_dict() if isinstance(task_or_id, Task) else {"task_id": task_id},
                    default=str,
                )

                result = await self._evalsha_or_reload(
                    client, "_lua_fail_dead", 4,
                    p_key,                    # KEYS[1]: processing_key
                    _dead_key(tt),            # KEYS[2]: dead_key
                    _TASK_PREFIX,             # KEYS[3]: task_hash_prefix
                    _HEARTBEAT_PREFIX,        # KEYS[4]: heartbeat_prefix
                    task_id,                  # ARGV[1]: task_id
                    task_json,                # ARGV[2]: task_json
                    token,                    # ARGV[3]: owner_token
                    str(_DEAD_MAX),           # ARGV[4]: dead_max
                )
                await client.aclose()

                if result == 0:
                    logger.warning(
                        "Fail/dead rejected (owner mismatch): task_id=%s", task_id,
                    )
                    queue_metrics["owner_fencing_rejected"] += 1
                    return False

            except Exception as e:
                logger.warning("Task fail/dead Redis error: %s", e)
                return False
        else:
            if self._allow_local_fallback:
                self._local_tasks.pop(task_id, None)

        logger.error(
            "Task moved to dead-letter: task_id=%s type=%s error=%s",
            task_id, tt, error[:200],
        )
        return True

    # ── reaper ──

    async def _reclaim_expired(self, task_type: str) -> int:
        """Re-enqueue tasks whose lease has expired and worker heartbeat is gone.

        Atomic Lua: ZRANGEBYSCORE processing → check heartbeat → ZREM → RPUSH queue.
        Only reclaims tasks whose heartbeat key is also gone (worker dead).

        Returns the number of reclaimed tasks.
        """
        if not self._redis_enabled:
            return 0

        try:
            client = await self._get_script_client()
            if client is None:
                return 0

            p_key = _p_key(task_type)
            q_key = _q_key(task_type)
            now = time.time()

            reclaimed = await self._evalsha_or_reload(
                client, "_lua_reaper", 4,
                p_key,                    # KEYS[1]: processing_key
                q_key,                    # KEYS[2]: queue_key
                _HEARTBEAT_PREFIX,        # KEYS[3]: heartbeat_prefix
                _TASK_PREFIX,             # KEYS[4]: task_hash_prefix
                str(now),                 # ARGV[1]: now
                "100",                    # ARGV[2]: batch_size
            ) or 0
            reclaimed = int(reclaimed)

            await client.aclose()

            if reclaimed:
                logger.info("Reclaimed %d expired tasks for %s", reclaimed, task_type)
                queue_metrics["reaper_reclaimed"] += reclaimed

            return reclaimed

        except Exception as e:
            logger.warning("Reclaim failed for %s: %s", task_type, e)
            return 0

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
        return len([t for t in self._local_tasks.values()
                     if t.task_type == task_type and t.status == TaskStatus.PENDING]) if self._allow_local_fallback else 0

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
        return len([t for t in self._local_tasks.values()
                     if t.task_type == task_type and t.status == TaskStatus.PROCESSING]) if self._allow_local_fallback else 0

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

    async def corrupt_length(self, task_type: str) -> int:
        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return 0
                length = await client.llen(_corrupt_key(task_type))
                await client.aclose()
                return length
            except Exception:
                pass
        return 0

    async def oldest_ready_age(self, task_type: str) -> float:
        """Return age in seconds of the oldest ready task, or 0 if empty."""
        if not self._redis_enabled:
            return 0.0
        try:
            client = await self._get_script_client()
            if client is None:
                return 0.0
            task_id = await client.lindex(_q_key(task_type), 0)
            if not task_id:
                await client.aclose()
                return 0.0
            raw = await client.hget(_task_hash_key(task_id), "data")
            await client.aclose()
            if raw:
                task_data = json.loads(raw)
                created_at = task_data.get("created_at", 0)
                if created_at:
                    return time.time() - created_at
            return 0.0
        except Exception:
            return 0.0

    # ── Dead-letter management ──

    async def get_metrics(self, task_types: list[str] | None = None) -> dict[str, Any]:
        """Return current queue metrics including live Redis state.

        Returns both cumulative counters and current queue length snapshots.
        """
        results = dict(queue_metrics)
        types = task_types or []

        ready = 0
        processing = 0
        retry_count = 0
        dead = 0

        for tt in types:
            ready += await self.queue_length(tt)
            processing += await self.processing_length(tt)
            retry_count += await self.retry_length(tt)
            dead += await self.dead_length(tt)

        results["ready"] = ready
        results["processing"] = processing
        results["retry"] = retry_count
        results["dead"] = dead
        return results

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
                        result.append(json.loads(raw))
                    except json.JSONDecodeError:
                        result.append({"task_id": tid, "error": "corrupt_payload"})
                else:
                    result.append({"task_id": tid, "error": "hash_expired"})
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
                else:
                    # Hash already expired — clean up list entry
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
