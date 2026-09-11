"""Durable Redis-backed task queue with atomic Lua operations and owner fencing.

Architecture (Redis data model):
- ``taskq:queue:{type}`` — List of task_ids (ready queue).
- ``taskq:processing:{type}`` — Sorted Set of task_ids, score = lease expiry.
- ``taskq:retry:{type}`` — Sorted Set of task_ids, score = retry_at timestamp.
- ``taskq:dead:{type}`` — List of task_ids (dead-letter, LRIM to 1000).
- ``taskq:task:{task_id}`` — Hash of task payload/metadata (TTL 7d in dead, 24h after complete).
- ``taskq:heartbeat:{task_id}`` — String = owner_token, TTL = lease_sec.
- ``taskq:idempotent:{task_id}`` — String, TTL = 8d (idempotency guard).

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
from app.services.practice.answer_projection_contract import (
    ANSWER_PROJECTION_MINIMUM_WORKER_VERSION,
    ANSWER_PROJECTION_TASK_SCHEMA_VERSION,
    ANSWER_PROJECTION_TASK_TYPE,
    parse_answer_projection_payload,
)

logger = logging.getLogger("postgraduate-ai.task-queue")


class QueueHealthError(Exception):
    """Raised when a queue health check fails due to Redis being unavailable.

    Used by v2 queue health methods to distinguish "empty queue" from
    "cannot determine queue state" — the latter is a health failure.
    """


class QueueFencingError(Exception):
    """Raised when owner or generation fencing check fails.

    Indicates a stale worker is trying to modify a task it no longer owns.
    """


class TaskQueueUnavailableError(Exception):
    """Raised when the task queue Redis backend is unreachable.

    Distinct from an empty queue — indicates a network error, timeout,
    connection refused, or protocol error. Callers MUST treat this as a
    service degradation, NOT as "no tasks available."

    Properties:
        retry_after: Suggested seconds before retrying (default 30).
    """

    def __init__(self, message: str = "", retry_after: int = 30) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# v1 Redis key prefixes (legacy — used for drain/migration)
_QUEUE_PREFIX = "taskq:queue"
_PROCESSING_PREFIX = "taskq:processing"
_DEAD_PREFIX = "taskq:dead"
_RETRY_PREFIX = "taskq:retry"
_CORRUPT_PREFIX = "taskq:corrupt"
_TASK_PREFIX = "taskq:task"
_IDEMPOTENCY_PREFIX = "taskq:idempotent"
_HEARTBEAT_PREFIX = "taskq:heartbeat"

# v2 Redis key namespace (production — fencing generation via HINCRBY)
# The v2 namespace adds a fencing_key that is NEVER deleted — the HINCRBY
# counter is monotonic for the entire lifetime of a task_id.
_V2_QUEUE_PREFIX = "taskq:v2:ready"
_V2_PROCESSING_PREFIX = "taskq:v2:processing"
_V2_DEAD_PREFIX = "taskq:v2:dead"
_V2_RETRY_PREFIX = "taskq:v2:retry"
_V2_CORRUPT_PREFIX = "taskq:v2:corrupt"
_V2_TASK_PREFIX = "taskq:v2:task"
_V2_IDEMPOTENCY_PREFIX = "taskq:v2:idempotent"
_V2_HEARTBEAT_PREFIX = "taskq:v2:heartbeat"
_V2_FENCING_PREFIX = "taskq:v2:fencing"  # HINCRBY monotonic counter — NEVER deleted

# Defaults
_DEFAULT_LEASE_SEC = 300  # 5 minutes
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE_DELAY = 10  # seconds
_REAPER_INTERVAL_SEC = 60
_LOCAL_TASK_MAX = 100  # bounded local fallback (dev only)
_DEAD_MAX = 1000  # max dead-letter entries
_CORRUPT_MAX = 100  # max corrupt entries
_IDEMPOTENT_TTL = (
    86400 * 8
)  # 8d — deliberately outlives 7d Outbox/dead retention boundary
_COMPLETED_TTL = 86400  # 24h retention for completed task hashes
_DEAD_HASH_TTL = 86400 * 7  # 7d retention for dead task hashes
_FENCING_TOMBSTONE_TTL = (
    86400 * 7
)  # 7d — covers max task time + lease + retry window + late writes


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"
    CORRUPT = "corrupt"
    CANCELLED = "cancelled"
    CANCEL_REQUESTED = "cancel_requested"


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


# Current task schema version for rolling deployment compatibility.
# Increment when making backward-incompatible changes to task payload structure.
_CURRENT_TASK_SCHEMA_VERSION: int = 2
# Default minimum worker for generic task types. Task-specific schemas may
# require a newer worker via ``_minimum_worker_version_for_task``.
_MINIMUM_WORKER_VERSION: int = 1


def _normalize_task_schema_version(task_type: str, schema_version: int) -> int:
    """Validate task schema versions; never silently upgrade incompatible work."""
    if task_type == ANSWER_PROJECTION_TASK_TYPE:
        if schema_version != ANSWER_PROJECTION_TASK_SCHEMA_VERSION:
            raise ValueError(
                "unsupported answer_projection schema_version="
                f"{schema_version}; required={ANSWER_PROJECTION_TASK_SCHEMA_VERSION}"
            )
        return ANSWER_PROJECTION_TASK_SCHEMA_VERSION
    return schema_version


def _minimum_worker_version_for_task(task_type: str, schema_version: int) -> int:
    """Return the oldest worker allowed to execute one task schema.

    Most task types still use the generic v1 worker contract. Answer
    projection schema v2 is deliberately stricter because it assumes the
    per-answer ``practice_records`` model and must never be executed by a
    worker that still hydrates the retired batch-shaped columns.
    """
    if (
        task_type == ANSWER_PROJECTION_TASK_TYPE
        and schema_version >= ANSWER_PROJECTION_TASK_SCHEMA_VERSION
    ):
        return ANSWER_PROJECTION_MINIMUM_WORKER_VERSION
    return _MINIMUM_WORKER_VERSION


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
    # Rolling deployment versioning fields
    schema_version: int = _CURRENT_TASK_SCHEMA_VERSION
    minimum_worker_version: int = _MINIMUM_WORKER_VERSION
    created_by_version: str = ""
    trace_id: str = ""
    request_id: str = ""

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
            "schema_version": self.schema_version,
            "minimum_worker_version": self.minimum_worker_version,
            "created_by_version": self.created_by_version,
            "trace_id": self.trace_id,
            "request_id": self.request_id,
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
            schema_version=d.get("schema_version", 1),
            minimum_worker_version=d.get("minimum_worker_version", 1),
            created_by_version=d.get("created_by_version", ""),
            trace_id=d.get("trace_id", ""),
            request_id=d.get("request_id", ""),
        )


def _task_correlation(payload: dict[str, Any]) -> tuple[str, str]:
    """Resolve trace/request IDs at enqueue time.

    Prefer the active HTTP/log context. Fall back to reserved payload metadata
    used by already-detached import jobs so cross-process dispatch keeps the
    original correlation IDs.
    """
    try:
        from app.core.log_context import get_log_context

        ctx = get_log_context()
    except Exception:
        ctx = {}

    trace_id = str(ctx.get("trace_id") or "")
    request_id = str(ctx.get("request_id") or "")

    options = payload.get("options")
    if isinstance(options, dict):
        trace_id = trace_id or str(options.get("_trace_id") or "")
        request_id = request_id or str(options.get("_request_id") or "")

    reserved = payload.get("_trace")
    if isinstance(reserved, dict):
        trace_id = trace_id or str(reserved.get("trace_id") or "")
        request_id = request_id or str(reserved.get("request_id") or "")

    return trace_id, request_id


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
        "answer_projection": settings.TASK_QUEUE_MAX_READY_ANSWER_PROJECTION,
        "error_diagnosis": settings.TASK_QUEUE_MAX_READY_AI,
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


# ══════════════════════════════════════════════════════════════════════════════
# v2 Lua Scripts — Fencing Generation via HINCRBY
#
# v2 key namespace: taskq:v2:{ready|processing|retry|dead|corrupt}:{type}
# v2 task hash:     taskq:v2:task:{task_id}
# v2 fencing key:   taskq:v2:fencing:{task_id}  — HINCRBY counter, NEVER deleted
# v2 heartbeat:     taskq:v2:heartbeat:{task_id}
# v2 idempotent:    taskq:v2:idempotent:{task_id}
#
# Generation is a HINCRBY monotonic counter stored in the fencing key.
# It is NEVER reset — not by reaper, retry, complete, purge, or re-enqueue.
# All v2 heartbeat/complete/fail scripts verify BOTH owner_token AND generation.
# ══════════════════════════════════════════════════════════════════════════════

# ENQUEUE_V2 with idempotency and capacity limit (v2 keys)
# KEYS: [queue_key, task_hash_prefix, idempotent_prefix]
# ARGS: [task_id, task_json, idempotent_ttl_sec, max_ready]
_LUA_ENQUEUE_V2 = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local idem_ttl = tonumber(ARGV[3])
local max_ready = tonumber(ARGV[4])

local exists = redis.call("EXISTS", KEYS[3] .. ":" .. task_id)
if exists == 1 then
    return "__duplicate__"
end

local ready_len = redis.call("LLEN", KEYS[1])
if max_ready > 0 and ready_len >= max_ready then
    return "__queue_full__"
end

redis.call("SETEX", KEYS[3] .. ":" .. task_id, idem_ttl, "1")

redis.call("HSET", KEYS[2] .. ":" .. task_id, "data", task_json,
    "status", "pending",
    "owner_token", "",
    "generation", 0,
    "retry_count", 0)

redis.call("RPUSH", KEYS[1], task_id)
return task_id
"""

# ENQUEUE_NON_IDEMPOTENT_V2 (v2 keys)
# KEYS: [queue_key, task_hash_prefix]
# ARGS: [task_id, task_json, max_ready]
_LUA_ENQUEUE_NON_IDEMPOTENT_V2 = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local max_ready = tonumber(ARGV[3])

local ready_len = redis.call("LLEN", KEYS[1])
if max_ready > 0 and ready_len >= max_ready then
    return "__queue_full__"
end

redis.call("HSET", KEYS[2] .. ":" .. task_id, "data", task_json,
    "status", "pending")
redis.call("RPUSH", KEYS[1], task_id)
return task_id
"""

# CLAIM_V2 — HINCRBY generation, NEVER reset.
# KEYS: [queue_key, processing_key, heartbeat_prefix, task_hash_prefix, fencing_prefix]
# ARGS: [task_id_placeholder_not_used, lease_expiry_abs, lease_ttl_rel, owner_token]
# The task_id comes from RPOP of the queue (not ARGV).
# Returns: {raw_payload, owner_token, generation} or nil.
_LUA_CLAIM_V2 = """
local lease_ttl = tonumber(ARGV[1])
local owner_token = ARGV[2]
local corrupt_max = tonumber(ARGV[3]) or 100
local corrupt_ttl = tonumber(ARGV[4]) or 604800
local now = tonumber(redis.call("TIME")[1])
local lease_expiry = now + lease_ttl

for _ = 1, 100 do
    local task_id = redis.call("LPOP", KEYS[1])
    if not task_id then
        return nil
    end

    local raw = redis.call("HGET", KEYS[4] .. ":" .. task_id, "data")
    local status = redis.call("HGET", KEYS[4] .. ":" .. task_id, "status")
    if not raw then
        redis.call("HSET", KEYS[4] .. ":" .. task_id,
            "status", "corrupt", "error", "missing task payload")
        redis.call("ZADD", KEYS[6], now, task_id)
        local corrupt_len = redis.call("ZCARD", KEYS[6])
        if corrupt_max > 0 and corrupt_len > corrupt_max then
            redis.call("ZREMRANGEBYRANK", KEYS[6], 0, corrupt_len - corrupt_max - 1)
        end
        redis.call("EXPIRE", KEYS[6], corrupt_ttl)
        redis.call("EXPIRE", KEYS[4] .. ":" .. task_id, corrupt_ttl)
    elseif status == "completed" or status == "dead" or status == "corrupt" or status == "cancelled" then
        -- Stale ready entry. Drop it and continue to the next task id.
    elseif status == "cancel_requested" then
        redis.call("HSET", KEYS[4] .. ":" .. task_id,
            "status", "cancelled", "owner_token", "", "lease_expires_at", 0)
        redis.call("EXPIRE", KEYS[4] .. ":" .. task_id, corrupt_ttl)
    else
        local generation = redis.call("HINCRBY", KEYS[5] .. ":" .. task_id, "gen", 1)
        redis.call("ZADD", KEYS[2], lease_expiry, task_id)
        redis.call("SETEX", KEYS[3] .. ":" .. task_id, lease_ttl, owner_token)
        redis.call("HSET", KEYS[4] .. ":" .. task_id,
            "owner_token", owner_token,
            "generation", generation,
            "status", "processing",
            "lease_expires_at", lease_expiry)
        return {task_id, raw, owner_token, tostring(generation), tostring(lease_expiry)}
    end
end
return nil
"""

# HEARTBEAT_V2 — verify BOTH owner_token AND generation
# Uses Redis TIME instead of client-provided timestamps to prevent clock skew.
# KEYS: [processing_key, heartbeat_prefix, task_hash_prefix, fencing_prefix]
# ARGS: [task_id, lease_ttl, owner_token]
# Returns: 1 on success, 0 on owner mismatch, -1 on generation mismatch
_LUA_HEARTBEAT_V2 = """
local task_id = ARGV[1]
local lease_ttl = tonumber(ARGV[2])
local owner_token = ARGV[3]
local redis_now = redis.call("TIME")
local new_expiry = tonumber(redis_now[1]) + lease_ttl
local stored = redis.call("GET", KEYS[2] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end

local stored_gen = redis.call("HGET", KEYS[3] .. ":" .. task_id, "generation")
local fencing_gen = redis.call("HGET", KEYS[4] .. ":" .. task_id, "gen")
if not fencing_gen or not stored_gen or tostring(stored_gen) ~= tostring(fencing_gen) then
    return -1
end

local status = redis.call("HGET", KEYS[3] .. ":" .. task_id, "status")
if status ~= "processing" and status ~= "cancel_requested" then
    return 0
end
redis.call("ZADD", KEYS[1], new_expiry, task_id)
redis.call("SETEX", KEYS[2] .. ":" .. task_id, lease_ttl, owner_token)
redis.call("HSET", KEYS[3] .. ":" .. task_id, "lease_expires_at", new_expiry)
return 1
"""

# COMPLETE_V2 — verify owner_token AND generation
# KEYS: [processing_key, retry_key, task_hash_prefix, heartbeat_prefix, fencing_prefix]
# ARGS: [task_id, owner_token, task_json, completed_ttl, fencing_tombstone_ttl]
# Returns: 1 on success, 0 on owner mismatch, -1 on generation mismatch
_LUA_COMPLETE_V2 = """
local task_id = ARGV[1]
local owner_token = ARGV[2]
local task_json = ARGV[3]
local ttl = tonumber(ARGV[4])
local fence_ttl = tonumber(ARGV[5])
local stored = redis.call("GET", KEYS[4] .. ":" .. task_id)
if not stored or stored ~= owner_token then
    return 0
end
local stored_gen = redis.call("HGET", KEYS[3] .. ":" .. task_id, "generation")
local fencing_gen = redis.call("HGET", KEYS[5] .. ":" .. task_id, "gen")
if not fencing_gen or not stored_gen or tostring(stored_gen) ~= tostring(fencing_gen) then
    return -1
end
redis.call("ZREM", KEYS[1], task_id)
redis.call("ZREM", KEYS[2], task_id)
redis.call("HSET", KEYS[3] .. ":" .. task_id,
    "data", task_json, "status", "completed",
    "owner_token", "", "lease_expires_at", 0, "error", "")
redis.call("HDEL", KEYS[3] .. ":" .. task_id, "cancel_requested", "cancel_reason")
redis.call("EXPIRE", KEYS[3] .. ":" .. task_id, ttl)
redis.call("DEL", KEYS[4] .. ":" .. task_id)
redis.call("EXPIRE", KEYS[5] .. ":" .. task_id, fence_ttl)
return 1
"""

# FAIL_RETRY_V2 — verify owner+generation, retry-full atomic → dead-letter.
# KEYS: [processing_key, retry_key, dead_key, task_hash_prefix, heartbeat_prefix, fencing_prefix]
# ARGS: [task_id, retry_at, task_json, owner_token, retry_count, error, retry_max, dead_max]
# Returns: 1 (retry), 2 (dead-letter due to full), 0 (owner mismatch), -1 (gen mismatch)
_LUA_FAIL_RETRY_V2 = """
local task_id = ARGV[1]
local retry_delay = tonumber(ARGV[2]) or 0
local task_json = ARGV[3]
local owner_token = ARGV[4]
local retry_count = tonumber(ARGV[5]) or 1
local error_msg = ARGV[6] or ""
local retry_max = tonumber(ARGV[7]) or 500
local dead_max = tonumber(ARGV[8]) or 1000
local fence_ttl = tonumber(ARGV[9]) or 604800
local now = tonumber(redis.call("TIME")[1])
local retry_at = now + retry_delay
local stored = redis.call("GET", KEYS[5] .. ":" .. task_id)
if not stored or stored ~= owner_token then return 0 end
local stored_gen = redis.call("HGET", KEYS[4] .. ":" .. task_id, "generation")
local fencing_gen = redis.call("HGET", KEYS[6] .. ":" .. task_id, "gen")
if not fencing_gen or not stored_gen or tostring(stored_gen) ~= tostring(fencing_gen) then return -1 end
redis.call("ZREM", KEYS[1], task_id)
redis.call("DEL", KEYS[5] .. ":" .. task_id)

if retry_max > 0 and redis.call("ZCARD", KEYS[2]) >= retry_max then
    redis.call("LPUSH", KEYS[3], task_id)
    redis.call("LTRIM", KEYS[3], 0, dead_max - 1)
    redis.call("EXPIRE", KEYS[3], fence_ttl)
    local dead_json = task_json
    local decoded_ok, decoded = pcall(cjson.decode, task_json)
    if decoded_ok and type(decoded) == "table" then
        decoded["status"] = "dead"
        decoded["owner_token"] = ""
        decoded["lease_expires_at"] = 0
        dead_json = cjson.encode(decoded)
    end
    redis.call("HSET", KEYS[4] .. ":" .. task_id,
        "data", dead_json, "status", "dead", "retry_count", retry_count,
        "error", error_msg, "owner_token", "", "lease_expires_at", 0)
    redis.call("EXPIRE", KEYS[4] .. ":" .. task_id, fence_ttl)
    redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, fence_ttl)
    return 2
end

redis.call("ZADD", KEYS[2], retry_at, task_id)
redis.call("HSET", KEYS[4] .. ":" .. task_id,
    "data", task_json, "status", "failed", "retry_count", retry_count,
    "error", error_msg, "owner_token", "", "lease_expires_at", 0)
return 1
"""

# FAIL_DEAD_V2 — verify owner+generation → ZREM processing → LPUSH dead → HSET status=dead
# KEYS: [processing_key, dead_key, task_hash_prefix, heartbeat_prefix, fencing_prefix]
# ARGS: [task_id, task_json, owner_token, dead_max, fencing_tombstone_ttl]
# Returns: 1 on success, 0 on owner mismatch, -1 on generation mismatch
_LUA_FAIL_DEAD_V2 = """
local task_id = ARGV[1]
local task_json = ARGV[2]
local owner_token = ARGV[3]
local dead_max = tonumber(ARGV[4]) or 1000
local fence_ttl = tonumber(ARGV[5])
local stored = redis.call("GET", KEYS[4] .. ":" .. task_id)
if not stored or stored ~= owner_token then return 0 end
local stored_gen = redis.call("HGET", KEYS[3] .. ":" .. task_id, "generation")
local fencing_gen = redis.call("HGET", KEYS[5] .. ":" .. task_id, "gen")
if not fencing_gen or not stored_gen or tostring(stored_gen) ~= tostring(fencing_gen) then return -1 end
local retry_count = 0
local last_error = ""
local decoded_ok, decoded = pcall(cjson.decode, task_json)
if decoded_ok and type(decoded) == "table" then
    retry_count = tonumber(decoded["retry_count"]) or 0
    last_error = tostring(decoded["error"] or "")
end
redis.call("ZREM", KEYS[1], task_id)
redis.call("LPUSH", KEYS[2], task_id)
redis.call("LTRIM", KEYS[2], 0, dead_max - 1)
redis.call("EXPIRE", KEYS[2], fence_ttl)
redis.call("HSET", KEYS[3] .. ":" .. task_id,
    "data", task_json, "status", "dead", "owner_token", "", "lease_expires_at", 0,
    "retry_count", retry_count, "error", string.sub(last_error, 1, 500))
redis.call("EXPIRE", KEYS[3] .. ":" .. task_id, fence_ttl)
redis.call("DEL", KEYS[4] .. ":" .. task_id)
redis.call("EXPIRE", KEYS[5] .. ":" .. task_id, fence_ttl)
return 1
"""

# REAPER_V2 — reclaim expired tasks using Redis server time
# Uses ``redis.call("TIME")`` instead of client-provided timestamps
# so that all workers agree on lease expiry regardless of clock skew.
# KEYS: [processing_key, queue_key, heartbeat_prefix, task_hash_prefix]
# ARGS: [batch_size, max_ready]
# Returns: count of reclaimed tasks (tasks that exceeded capacity are skipped)
_LUA_REAPER_V2 = """
local now = tonumber(redis.call("TIME")[1])
local limit = tonumber(ARGV[1]) or 100
local max_ready = tonumber(ARGV[2]) or 0
local corrupt_max = tonumber(ARGV[3]) or 100
local terminal_ttl = tonumber(ARGV[4]) or 604800
local expired = redis.call("ZRANGEBYSCORE", KEYS[1], 0, now, "LIMIT", 0, limit)
local count = 0
for _, task_id in ipairs(expired) do
    if redis.call("EXISTS", KEYS[3] .. ":" .. task_id) == 0 then
        local task_key = KEYS[4] .. ":" .. task_id
        local status = redis.call("HGET", task_key, "status")
        if status == "completed" or status == "dead" or status == "corrupt" or status == "cancelled" then
            redis.call("ZREM", KEYS[1], task_id)
        elseif status == "cancel_requested" then
            redis.call("ZREM", KEYS[1], task_id)
            redis.call("HSET", task_key,
                "status", "cancelled", "owner_token", "", "lease_expires_at", 0)
            redis.call("HDEL", task_key, "cancel_requested")
            redis.call("EXPIRE", task_key, terminal_ttl)
            redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, terminal_ttl)
        elseif redis.call("HEXISTS", task_key, "data") == 1 then
            local ready_len = redis.call("LLEN", KEYS[2])
            if max_ready > 0 and ready_len >= max_ready then
                break
            end
            redis.call("ZREM", KEYS[1], task_id)
            redis.call("HSET", task_key,
                "status", "pending", "owner_token", "", "lease_expires_at", 0)
            redis.call("HDEL", task_key, "cancel_requested", "cancel_reason")
            redis.call("RPUSH", KEYS[2], task_id)
            count = count + 1
        else
            redis.call("ZREM", KEYS[1], task_id)
            redis.call("HSET", task_key,
                "status", "corrupt", "error", "missing task payload",
                "owner_token", "", "lease_expires_at", 0)
            redis.call("ZADD", KEYS[5], now, task_id)
            local corrupt_len = redis.call("ZCARD", KEYS[5])
            if corrupt_max > 0 and corrupt_len > corrupt_max then
                redis.call("ZREMRANGEBYRANK", KEYS[5], 0, corrupt_len - corrupt_max - 1)
            end
            redis.call("EXPIRE", KEYS[5], terminal_ttl)
            redis.call("EXPIRE", task_key, terminal_ttl)
            redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, terminal_ttl)
        end
    end
end
return count
"""

# RETRY_CLAIM_V2 — HINCRBY generation from retry ZSET
# KEYS: [retry_key, processing_key, heartbeat_prefix, task_hash_prefix, fencing_prefix]
# ARGS: [now_timestamp, lease_expiry_abs, lease_ttl_rel, owner_token, execution_generation_unused]
# Returns: {task_id, owner_token, generation, raw_payload} or nil
_LUA_RETRY_CLAIM_V2 = """
local lease_ttl = tonumber(ARGV[1])
local owner_token = ARGV[2]
local corrupt_max = tonumber(ARGV[3]) or 100
local terminal_ttl = tonumber(ARGV[4]) or 604800
local now = tonumber(redis.call("TIME")[1])
local lease_expiry = now + lease_ttl
for _ = 1, 100 do
    local candidates = redis.call("ZRANGEBYSCORE", KEYS[1], 0, now, "LIMIT", 0, 1)
    if #candidates == 0 then return nil end
    local task_id = candidates[1]
    redis.call("ZREM", KEYS[1], task_id)
    local task_key = KEYS[4] .. ":" .. task_id
    local raw = redis.call("HGET", task_key, "data")
    local status = redis.call("HGET", task_key, "status")
    if not raw then
        redis.call("HSET", task_key, "status", "corrupt", "error", "missing task payload")
        redis.call("ZADD", KEYS[6], now, task_id)
        local corrupt_len = redis.call("ZCARD", KEYS[6])
        if corrupt_max > 0 and corrupt_len > corrupt_max then
            redis.call("ZREMRANGEBYRANK", KEYS[6], 0, corrupt_len - corrupt_max - 1)
        end
        redis.call("EXPIRE", KEYS[6], terminal_ttl)
        redis.call("EXPIRE", task_key, terminal_ttl)
    elseif status == "completed" or status == "dead" or status == "corrupt" or status == "cancelled" then
        -- stale retry entry; discard
    elseif status == "cancel_requested" then
        redis.call("HSET", task_key, "status", "cancelled", "owner_token", "", "lease_expires_at", 0)
        redis.call("EXPIRE", task_key, terminal_ttl)
    else
        local generation = redis.call("HINCRBY", KEYS[5] .. ":" .. task_id, "gen", 1)
        redis.call("ZADD", KEYS[2], lease_expiry, task_id)
        redis.call("SETEX", KEYS[3] .. ":" .. task_id, lease_ttl, owner_token)
        redis.call("HSET", task_key,
            "owner_token", owner_token, "generation", generation,
            "status", "processing", "lease_expires_at", lease_expiry)
        return {task_id, raw, owner_token, tostring(generation), tostring(lease_expiry)}
    end
end
return nil
"""

# MARK_CORRUPT_V2 — atomically remove from processing, add to corrupt ZSET
# KEYS: [processing_key, corrupt_key, task_hash_prefix, heartbeat_prefix, fencing_prefix]
# ARGS: [task_id, error_summary, corrupt_max, fencing_tombstone_ttl]
_LUA_MARK_CORRUPT_V2 = """
local task_id = ARGV[1]
local error_summary = ARGV[2] or ""
local corrupt_max = tonumber(ARGV[3]) or 100
local fence_ttl = tonumber(ARGV[4])

redis.call("ZREM", KEYS[1], task_id)
redis.call("ZADD", KEYS[2], redis.call("TIME")[1], task_id)
local corrupt_len = redis.call("ZCARD", KEYS[2])
if corrupt_max > 0 and corrupt_len > corrupt_max then
    redis.call("ZREMRANGEBYRANK", KEYS[2], 0, corrupt_len - corrupt_max - 1)
end
redis.call("HSET", KEYS[3] .. ":" .. task_id,
    "status", "corrupt",
    "error", error_summary,
    "owner_token", "",
    "lease_expires_at", 0,
    "discovered_at", redis.call("TIME")[1])
redis.call("EXPIRE", KEYS[2], fence_ttl)
redis.call("EXPIRE", KEYS[3] .. ":" .. task_id, fence_ttl)
redis.call("DEL", KEYS[4] .. ":" .. task_id)
redis.call("EXPIRE", KEYS[5] .. ":" .. task_id, fence_ttl)
return 1
"""

# CANCEL_V2 — atomic cancel with status-dependent behavior
# KEYS: [queue_key, processing_key, retry_key, dead_key, heartbeat_prefix, task_hash_prefix, fencing_prefix]
# ARGS: [task_id, reason, fencing_tombstone_ttl]
# Returns:
#   0 — already terminal or not found (idempotent)
#   1 — pending → cancelled (removed from ready)
#   2 — processing → cancel_requested (flag set on task hash)
#   3 — retrying → cancelled (removed from retry ZSET)
#   4 — in dead-letter → cancelled (removed from dead list)
_LUA_CANCEL_V2 = """
local task_id = ARGV[1]
local reason = ARGV[2] or "cancelled by admin"
local fence_ttl = tonumber(ARGV[3])

-- Check task exists
local status = redis.call("HGET", KEYS[6] .. ":" .. task_id, "status")
if not status then
    return 0  -- not found
end

-- Already terminal
if status == "completed" or status == "cancelled" or status == "corrupt" then
    return 0
end

if status == "pending" then
    -- Remove from ready queue, set cancelled
    redis.call("LREM", KEYS[1], 0, task_id)
    redis.call("HSET", KEYS[6] .. ":" .. task_id, "status", "cancelled", "error", reason)
    redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, 86400)
    return 1
end

if status == "processing" then
    -- Set cancel_requested flag — worker will check at heartbeat boundary
    redis.call("HSET", KEYS[6] .. ":" .. task_id, "cancel_requested", "1", "cancel_reason", reason)
    return 2
end

if status == "failed" then
    -- Remove from retry ZSET, set cancelled
    redis.call("ZREM", KEYS[3], task_id)
    redis.call("HSET", KEYS[6] .. ":" .. task_id, "status", "cancelled", "error", reason)
    redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, 86400)
    return 3
end

if status == "dead" then
    redis.call("LREM", KEYS[4], 0, task_id)
    redis.call("HSET", KEYS[6] .. ":" .. task_id, "status", "cancelled", "error", reason)
    redis.call("EXPIRE", KEYS[6] .. ":" .. task_id, 86400)
    redis.call("DEL", KEYS[5] .. ":" .. task_id)
    return 4
end

return 0
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


# ── v2 key helpers ──


def _v2_q_key(task_type: str) -> str:
    return f"{_V2_QUEUE_PREFIX}:{task_type}"


def _v2_p_key(task_type: str) -> str:
    return f"{_V2_PROCESSING_PREFIX}:{task_type}"


def _v2_dead_key(task_type: str) -> str:
    return f"{_V2_DEAD_PREFIX}:{task_type}"


def _v2_retry_key(task_type: str) -> str:
    return f"{_V2_RETRY_PREFIX}:{task_type}"


def _v2_corrupt_key(task_type: str) -> str:
    return f"{_V2_CORRUPT_PREFIX}:{task_type}"


def _v2_task_hash_key(task_id: str) -> str:
    return f"{_V2_TASK_PREFIX}:{task_id}"


def _v2_heartbeat_key(task_id: str) -> str:
    return f"{_V2_HEARTBEAT_PREFIX}:{task_id}"


def _v2_fencing_key(task_id: str) -> str:
    return f"{_V2_FENCING_PREFIX}:{task_id}"


def _v2_idempotent_key(task_id: str) -> str:
    return f"{_V2_IDEMPOTENCY_PREFIX}:{task_id}"


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
        self._pool: redis_async.ConnectionPool | None = (
            None  # shared pool for script ops
        )
        self._lua_enqueue = None
        self._lua_enqueue_non_idempotent = None
        self._lua_claim = None
        self._lua_heartbeat = None
        self._lua_complete = None
        self._lua_fail_retry = None
        self._lua_fail_dead = None
        self._lua_reaper = None
        self._lua_retry_claim = None
        # v2 Lua script SHA caches
        self._lua_enqueue_v2 = None
        self._lua_enqueue_non_idempotent_v2 = None
        self._lua_claim_v2 = None
        self._lua_heartbeat_v2 = None
        self._lua_complete_v2 = None
        self._lua_fail_retry_v2 = None
        self._lua_fail_dead_v2 = None
        self._lua_reaper_v2 = None
        self._lua_retry_claim_v2 = None
        self._lua_mark_corrupt_v2 = None
        self._lua_cancel_v2 = None

    @property
    def _allow_local_fallback(self) -> bool:
        """Local in-memory fallback allowed only when:
        - NOT production/cloud_api environment, AND
        - ALLOW_IN_MEMORY_TASK_QUEUE=true is explicitly set.
        """
        if self._is_restricted:
            return False
        return (
            settings.ALLOW_IN_MEMORY_TASK_QUEUE
            if hasattr(settings, "ALLOW_IN_MEMORY_TASK_QUEUE")
            else False
        )

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
        """Get a Redis connection from the shared pool for non-blocking operations.

        Uses a lazily-created ``redis.asyncio.ConnectionPool`` shared across
        all script-based operations. Callers MUST return connections to the pool
        by calling ``await client.aclose()`` (or using ``async with``) — but
        with a pool, ``aclose()`` returns the connection, not destroys it.
        """
        if not self._redis_enabled:
            return None
        if self._pool is None:
            self._pool = redis_async.ConnectionPool.from_url(
                self._redis_url,
                socket_connect_timeout=5,
                socket_timeout=5,
                decode_responses=True,
                max_connections=20,
            )
        return redis_async.Redis(connection_pool=self._pool)

    async def _load_scripts(self, client) -> None:
        """Load Lua scripts into Redis and cache SHA hashes."""
        if self._lua_enqueue is not None and self._lua_enqueue_v2 is not None:
            return
        self._lua_enqueue = await client.script_load(_LUA_ENQUEUE)
        self._lua_enqueue_non_idempotent = await client.script_load(
            _LUA_ENQUEUE_NON_IDEMPOTENT
        )
        self._lua_claim = await client.script_load(_LUA_CLAIM)
        self._lua_heartbeat = await client.script_load(_LUA_HEARTBEAT)
        self._lua_complete = await client.script_load(_LUA_COMPLETE)
        self._lua_fail_retry = await client.script_load(_LUA_FAIL_RETRY)
        self._lua_fail_dead = await client.script_load(_LUA_FAIL_DEAD)
        self._lua_reaper = await client.script_load(_LUA_REAPER)
        self._lua_retry_claim = await client.script_load(_LUA_RETRY_CLAIM)
        # v2 scripts
        self._lua_enqueue_v2 = await client.script_load(_LUA_ENQUEUE_V2)
        self._lua_enqueue_non_idempotent_v2 = await client.script_load(
            _LUA_ENQUEUE_NON_IDEMPOTENT_V2
        )
        self._lua_claim_v2 = await client.script_load(_LUA_CLAIM_V2)
        self._lua_heartbeat_v2 = await client.script_load(_LUA_HEARTBEAT_V2)
        self._lua_complete_v2 = await client.script_load(_LUA_COMPLETE_V2)
        self._lua_fail_retry_v2 = await client.script_load(_LUA_FAIL_RETRY_V2)
        self._lua_fail_dead_v2 = await client.script_load(_LUA_FAIL_DEAD_V2)
        self._lua_reaper_v2 = await client.script_load(_LUA_REAPER_V2)
        self._lua_retry_claim_v2 = await client.script_load(_LUA_RETRY_CLAIM_V2)
        self._lua_mark_corrupt_v2 = await client.script_load(_LUA_MARK_CORRUPT_V2)
        self._lua_cancel_v2 = await client.script_load(_LUA_CANCEL_V2)

    async def close(self) -> None:
        """Close the persistent Redis connection and shared pool."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception as e:
                logger.warning("Error closing task queue Redis connection: %s", e)
            self._redis = None
        if self._pool is not None:
            try:
                await self._pool.aclose()
            except Exception as e:
                logger.warning("Error closing task queue Redis pool: %s", e)
            self._pool = None

    # ── NOSCRIPT recovery ──

    async def _evalsha_or_reload(
        self, client, sha_name: str, num_keys: int, *args
    ) -> Any:
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
            self._lua_enqueue_v2 = None
            self._lua_enqueue_non_idempotent_v2 = None
            self._lua_claim_v2 = None
            self._lua_heartbeat_v2 = None
            self._lua_complete_v2 = None
            self._lua_fail_retry_v2 = None
            self._lua_fail_dead_v2 = None
            self._lua_reaper_v2 = None
            self._lua_retry_claim_v2 = None
            self._lua_mark_corrupt_v2 = None
            self._lua_cancel_v2 = None
            await self._load_scripts(client)
            sha = getattr(self, sha_name, None)
            return await client.evalsha(sha, num_keys, *args)

    # ── enqueue (DEPRECATED v1 — use enqueue_v2) ──

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

        DEPRECATED: Use ``enqueue_v2`` instead. This method is kept for
        backward compatibility with legacy callers but writes to v1 keys
        (``taskq:queue:*``) which are NOT consumed by the v2 dispatcher.
        In production/cloud_api, this method logs a warning on every call.
        """
        if self._is_restricted:
            logger.warning(
                "v1 enqueue() called in restricted environment — "
                "tasks go to v1 keys not consumed by v2 dispatcher. "
                "Call enqueue_v2() instead. task_id=%s type=%s",
                task_id or "?",
                task_type,
            )
        tid = task_id or f"task_{uuid.uuid4().hex}"

        trace_id, request_id = _task_correlation(payload)
        task = Task(
            task_id=tid,
            task_type=task_type,
            payload=payload,
            max_retries=max_retries,
            trace_id=trace_id,
            request_id=request_id,
        )
        task_json = json.dumps(task.to_dict(), default=str)

        max_ready = _get_max_ready(task_type)

        if self._redis_enabled:
            try:
                client = await self._get_script_client()
                if client is None:
                    return EnqueueResult(
                        accepted=False,
                        task_id=None,
                        reason="redis_unavailable",
                        retry_after=30,
                    )
                await self._load_scripts(client)

                if task_id is not None:
                    result = await self._evalsha_or_reload(
                        client,
                        "_lua_enqueue",
                        3,
                        _q_key(task_type),  # KEYS[1]: queue_key
                        _TASK_PREFIX,  # KEYS[2]: task_hash_prefix
                        _IDEMPOTENCY_PREFIX,  # KEYS[3]: idempotent_prefix
                        tid,  # ARGV[1]: task_id
                        task_json,  # ARGV[2]: task_json
                        str(_IDEMPOTENT_TTL),  # ARGV[3]: idempotent_ttl
                        str(max_ready),  # ARGV[4]: max_ready
                    )
                else:
                    result = await self._evalsha_or_reload(
                        client,
                        "_lua_enqueue_non_idempotent",
                        2,
                        _q_key(task_type),  # KEYS[1]: queue_key
                        _TASK_PREFIX,  # KEYS[2]: task_hash_prefix
                        tid,  # ARGV[1]: task_id
                        task_json,  # ARGV[2]: task_json
                        str(max_ready),  # ARGV[3]: max_ready
                    )

                await client.aclose()

                if result == "__duplicate__":
                    logger.info("Duplicate task rejected (idempotent): task_id=%s", tid)
                    queue_metrics["duplicate_enqueue_prevented"] += 1
                    return EnqueueResult(accepted=True, task_id=tid, reason="duplicate")

                if result == "__queue_full__":
                    logger.warning(
                        "Queue full, rejected: task_id=%s type=%s", tid, task_type
                    )
                    queue_metrics["enqueue_rejected"] += 1
                    return EnqueueResult(
                        accepted=False,
                        task_id=None,
                        reason="queue_full",
                        retry_after=30,
                    )

                if result is None:
                    logger.error(
                        "Enqueue failed (nil result): task_id=%s type=%s",
                        tid,
                        task_type,
                    )
                    queue_metrics["enqueue_rejected"] += 1
                    return EnqueueResult(
                        accepted=False,
                        task_id=None,
                        reason="internal_error",
                        retry_after=30,
                    )

                logger.info("Task enqueued: task_id=%s type=%s", tid, task_type)
                return EnqueueResult(accepted=True, task_id=tid)

            except redis_exc.ConnectionError:
                if not self._allow_local_fallback:
                    logger.error(
                        "Redis connection error, rejecting enqueue task_id=%s", tid
                    )
                    queue_metrics["enqueue_rejected"] += 1
                    return EnqueueResult(
                        accepted=False,
                        task_id=None,
                        reason="redis_unavailable",
                        retry_after=30,
                    )
                logger.warning(
                    "Redis enqueue failed, fallen back to local: task_id=%s", tid
                )

            except Exception as e:
                if not self._allow_local_fallback:
                    logger.error("Redis enqueue failed (no fallback): %s", e)
                    queue_metrics["enqueue_rejected"] += 1
                    return EnqueueResult(
                        accepted=False,
                        task_id=None,
                        reason="enqueue_failed",
                        retry_after=30,
                    )
                logger.warning("Redis enqueue failed, falling back to local: %s", e)

        # Local fallback (dev only, bounded)
        if self._allow_local_fallback:
            if tid in self._local_tasks:
                return EnqueueResult(accepted=True, task_id=tid)
            if len(self._local_tasks) >= _LOCAL_TASK_MAX:
                logger.error("Local task queue full, rejected task_id=%s", tid)
                queue_metrics["enqueue_rejected"] += 1
                return EnqueueResult(
                    accepted=False, task_id=None, reason="queue_full", retry_after=30
                )
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
                    client,
                    "_lua_claim",
                    4,
                    q_key,  # KEYS[1]: queue_key
                    p_key,  # KEYS[2]: processing_key
                    _HEARTBEAT_PREFIX,  # KEYS[3]: heartbeat_prefix
                    _TASK_PREFIX,  # KEYS[4]: task_hash_prefix
                    str(lease_expiry),  # ARGV[1]: lease_expiry
                    str(lease_sec),  # ARGV[2]: lease_ttl
                    owner_token,  # ARGV[3]: owner_token
                    str(generation),  # ARGV[4]: execution_generation
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
                        task.task_id,
                        task_type,
                        lease_sec,
                        task.generation,
                    )
                    return task

                # 2. Retry ZSET (payload returned inline from Lua)
                retry_data = await self._dequeue_retry(
                    client,
                    task_type,
                    lease_sec,
                    generation,
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
                    task.task_id,
                    task_type,
                    lease_sec,
                    task.generation,
                )
                return task

            except redis_exc.ConnectionError:
                logger.warning(
                    "Redis dequeue failed (connection): task_type=%s", task_type
                )
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
        self,
        client,
        task_type: str,
        lease_sec: int,
        generation: int,
    ) -> tuple[str, str, str, str] | None:
        """Atomically claim from retry ZSET.

        Returns (raw_payload, task_id, owner_token, gen) or None.
        Payload is validated inside Lua to avoid ghosts.
        """
        now = time.time()
        lease_expiry = now + lease_sec
        owner_token = uuid.uuid4().hex

        result = await self._evalsha_or_reload(
            client,
            "_lua_retry_claim",
            4,
            _retry_key(task_type),  # KEYS[1]: retry ZSET
            _p_key(task_type),  # KEYS[2]: processing ZSET
            _HEARTBEAT_PREFIX,  # KEYS[3]: heartbeat_prefix
            _TASK_PREFIX,  # KEYS[4]: task_hash_prefix
            str(now),  # ARGV[1]: now
            str(lease_expiry),  # ARGV[2]: lease_expiry
            str(lease_sec),  # ARGV[3]: lease_ttl
            owner_token,  # ARGV[4]: owner_token
            str(generation),  # ARGV[5]: execution_generation
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
                        client,
                        "_lua_heartbeat",
                        2,
                        _p_key(task_type or ""),  # KEYS[1]: processing_key
                        _HEARTBEAT_PREFIX,  # KEYS[2]: heartbeat_prefix
                        task_id,  # ARGV[1]: task_id
                        str(new_expiry),  # ARGV[2]: new_lease_expiry
                        str(lease_sec),  # ARGV[3]: lease_ttl
                        token,  # ARGV[4]: owner_token
                    )
                    await client.aclose()

                    if result == 0:
                        logger.warning(
                            "Heartbeat rejected (owner mismatch): task_id=%s",
                            task_id,
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
        processing, sets completed status, and deletes the heartbeat. The
        idempotency guard is intentionally preserved until its TTL expires.

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
                    client,
                    "_lua_complete",
                    4,
                    p_key,  # KEYS[1]: processing_key
                    r_key,  # KEYS[2]: retry_key
                    _TASK_PREFIX,  # KEYS[3]: task_hash_prefix
                    _HEARTBEAT_PREFIX,  # KEYS[4]: heartbeat_prefix
                    task_id,  # ARGV[1]: task_id
                    token,  # ARGV[2]: owner_token
                    str(_COMPLETED_TTL),  # ARGV[3]: completed_ttl
                )
                await client.aclose()

                if result == 0:
                    logger.warning(
                        "Complete rejected (owner mismatch, fencing): task_id=%s",
                        task_id,
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
                        client,
                        "_lua_fail_retry",
                        4,
                        p_key,  # KEYS[1]: processing_key
                        _retry_key(tt),  # KEYS[2]: retry_key
                        _TASK_PREFIX,  # KEYS[3]: task_hash_prefix
                        _HEARTBEAT_PREFIX,  # KEYS[4]: heartbeat_prefix
                        task_id,  # ARGV[1]: task_id
                        str(retry_at),  # ARGV[2]: retry_at
                        task_json,  # ARGV[3]: task_json
                        token,  # ARGV[4]: owner_token
                        str(task.retry_count),  # ARGV[5]: retry_count
                        error[:200],  # ARGV[6]: error
                    )
                    await client.aclose()

                    if result == 0:
                        logger.warning(
                            "Fail/retry rejected (owner mismatch): task_id=%s",
                            task_id,
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
                task.retry_count,
                task.max_retries,
                delay,
                task_id,
                error[:200],
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
                    task.to_dict()
                    if isinstance(task_or_id, Task)
                    else {"task_id": task_id},
                    default=str,
                )

                result = await self._evalsha_or_reload(
                    client,
                    "_lua_fail_dead",
                    4,
                    p_key,  # KEYS[1]: processing_key
                    _dead_key(tt),  # KEYS[2]: dead_key
                    _TASK_PREFIX,  # KEYS[3]: task_hash_prefix
                    _HEARTBEAT_PREFIX,  # KEYS[4]: heartbeat_prefix
                    task_id,  # ARGV[1]: task_id
                    task_json,  # ARGV[2]: task_json
                    token,  # ARGV[3]: owner_token
                    str(_DEAD_MAX),  # ARGV[4]: dead_max
                )
                await client.aclose()

                if result == 0:
                    logger.warning(
                        "Fail/dead rejected (owner mismatch): task_id=%s",
                        task_id,
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
            task_id,
            tt,
            error[:200],
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

            reclaimed = (
                await self._evalsha_or_reload(
                    client,
                    "_lua_reaper",
                    4,
                    p_key,  # KEYS[1]: processing_key
                    q_key,  # KEYS[2]: queue_key
                    _HEARTBEAT_PREFIX,  # KEYS[3]: heartbeat_prefix
                    _TASK_PREFIX,  # KEYS[4]: task_hash_prefix
                    str(now),  # ARGV[1]: now
                    "100",  # ARGV[2]: batch_size
                )
                or 0
            )
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
        return (
            len(
                [
                    t
                    for t in self._local_tasks.values()
                    if t.task_type == task_type and t.status == TaskStatus.PENDING
                ]
            )
            if self._allow_local_fallback
            else 0
        )

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
        return (
            len(
                [
                    t
                    for t in self._local_tasks.values()
                    if t.task_type == task_type and t.status == TaskStatus.PROCESSING
                ]
            )
            if self._allow_local_fallback
            else 0
        )

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

    # ══════════════════════════════════════════════════════════════════════════
    # v2 Fencing Methods (HINCRBY-based generation)
    # ══════════════════════════════════════════════════════════════════════════

    async def enqueue_v2(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        task_id: str | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        idempotent: bool = True,
        schema_version: int | None = None,
        minimum_worker_version: int | None = None,
    ) -> EnqueueResult:
        """Enqueue a task into the v2 key namespace.

        Same semantics as ``enqueue()`` but uses v2 Redis keys
        (``taskq:v2:*`` namespace).
        """
        tid = task_id or f"task_{uuid.uuid4().hex}"
        trace_id, request_id = _task_correlation(payload)
        effective_schema_version = int(
            _CURRENT_TASK_SCHEMA_VERSION if schema_version is None else schema_version
        )
        if effective_schema_version <= 0:
            raise ValueError("schema_version must be positive")
        effective_schema_version = _normalize_task_schema_version(
            task_type, effective_schema_version
        )
        if task_type == ANSWER_PROJECTION_TASK_TYPE:
            # Reject retired batch-shaped payloads at the producer boundary.
            # Do not enqueue an incompatible task and hope a newer worker can
            # reinterpret it later.
            parse_answer_projection_payload(payload)
        effective_minimum_worker_version = int(
            _minimum_worker_version_for_task(task_type, effective_schema_version)
            if minimum_worker_version is None
            else minimum_worker_version
        )
        if effective_minimum_worker_version <= 0:
            raise ValueError("minimum_worker_version must be positive")
        task = Task(
            task_id=tid,
            task_type=task_type,
            payload=payload,
            max_retries=max_retries,
            trace_id=trace_id,
            request_id=request_id,
            schema_version=effective_schema_version,
            minimum_worker_version=effective_minimum_worker_version,
        )
        task_json = json.dumps(task.to_dict(), default=str)
        max_ready = _get_max_ready(task_type)

        if not self._redis_enabled:
            return EnqueueResult(
                accepted=False, task_id=None, reason="redis_unavailable", retry_after=30
            )
        client = None
        try:
            client = await self._get_script_client()
            if client is None:
                return EnqueueResult(
                    accepted=False,
                    task_id=None,
                    reason="redis_unavailable",
                    retry_after=30,
                )
            await self._load_scripts(client)

            if task_id is not None:
                result = await self._evalsha_or_reload(
                    client,
                    "_lua_enqueue_v2",
                    3,
                    _v2_q_key(task_type),
                    _V2_TASK_PREFIX,
                    _V2_IDEMPOTENCY_PREFIX,
                    tid,
                    task_json,
                    str(_IDEMPOTENT_TTL),
                    str(max_ready),
                )
            else:
                result = await self._evalsha_or_reload(
                    client,
                    "_lua_enqueue_non_idempotent_v2",
                    2,
                    _v2_q_key(task_type),
                    _V2_TASK_PREFIX,
                    tid,
                    task_json,
                    str(max_ready),
                )

            if result == "__duplicate__":
                logger.info("v2 Duplicate task: task_id=%s", tid)
                queue_metrics["duplicate_enqueue_prevented"] += 1
                return EnqueueResult(accepted=True, task_id=tid, reason="duplicate")
            if result == "__queue_full__":
                logger.warning("v2 Queue full: task_id=%s type=%s", tid, task_type)
                queue_metrics["enqueue_rejected"] += 1
                return EnqueueResult(
                    accepted=False, task_id=None, reason="queue_full", retry_after=30
                )
            if result is None:
                logger.error("v2 Enqueue nil: task_id=%s type=%s", tid, task_type)
                return EnqueueResult(
                    accepted=False,
                    task_id=None,
                    reason="internal_error",
                    retry_after=30,
                )

            return EnqueueResult(accepted=True, task_id=tid)
        except (redis_exc.ConnectionError, redis_exc.TimeoutError) as e:
            # Redis availability is surfaced structurally to callers.  The
            # Outbox dispatcher owns outage-level pause/resume logging, so do
            # not emit one ERROR per enqueue attempt here.
            logger.debug("v2 Enqueue Redis unavailable: %s", e)
            return EnqueueResult(
                accepted=False, task_id=None, reason="redis_unavailable", retry_after=30
            )
        finally:
            # Redis failures can occur while loading/evaluating scripts. Always
            # release the wrapper back to the shared pool so an outage cannot
            # gradually exhaust dispatcher connections.
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass

    async def dequeue_v2(
        self,
        task_type: str,
        *,
        lease_sec: int = _DEFAULT_LEASE_SEC,
    ) -> Task | None:
        """Atomically claim one ready/retry task using Redis server time."""
        if not self._redis_enabled:
            return None
        try:
            client = await self._get_client()
            if client is None:
                return None
            await self._load_scripts(client)
            owner_token = uuid.uuid4().hex

            result = await self._evalsha_or_reload(
                client,
                "_lua_claim_v2",
                6,
                _v2_q_key(task_type),
                _v2_p_key(task_type),
                _V2_HEARTBEAT_PREFIX,
                _V2_TASK_PREFIX,
                _V2_FENCING_PREFIX,
                _v2_corrupt_key(task_type),
                str(lease_sec),
                owner_token,
                str(settings.TASK_QUEUE_CORRUPT_MAX),
                str(_DEAD_HASH_TTL),
            )
            if result is None:
                result = await self._dequeue_retry_v2(client, task_type, lease_sec)
            if result is None:
                return None

            task_id, raw_payload, stored_token, stored_gen, lease_expiry = result
            try:
                payload = json.loads(raw_payload)
                task = Task.from_dict(payload)
                if task.task_id != task_id or task.task_type != task_type:
                    raise ValueError(
                        f"task identity mismatch: hash={task_id}/{task_type} "
                        f"payload={task.task_id}/{task.task_type}"
                    )
            except Exception as exc:
                await self.mark_corrupt_v2(task_id, task_type, str(exc)[:200])
                logger.error(
                    "v2 Claimed corrupt task: task_id=%s error=%s", task_id, exc
                )
                return None

            task.status = TaskStatus.PROCESSING
            task.lease_expires_at = float(lease_expiry or 0)
            task.owner_token = stored_token or owner_token
            task.generation = int(stored_gen or 0)
            task.updated_at = time.time()
            logger.info(
                "v2 Dequeued: task_id=%s type=%s gen=%d",
                task.task_id,
                task_type,
                task.generation,
            )
            return task
        except (redis_exc.ConnectionError, redis_exc.TimeoutError) as exc:
            logger.error("v2 Dequeue Redis unavailable: %s", exc)
            raise TaskQueueUnavailableError(
                f"Redis unavailable during dequeue: {exc}",
                retry_after=30,
            ) from exc
        except redis_exc.ResponseError as exc:
            logger.error("v2 Dequeue Redis protocol error: %s", exc)
            raise TaskQueueUnavailableError(
                f"Redis protocol error during dequeue: {exc}",
                retry_after=30,
            ) from exc

    async def _dequeue_retry_v2(
        self,
        client,
        task_type: str,
        lease_sec: int,
    ) -> list[str] | None:
        """Claim one due retry task using the same fenced state transition."""
        owner_token = uuid.uuid4().hex
        return await self._evalsha_or_reload(
            client,
            "_lua_retry_claim_v2",
            6,
            _v2_retry_key(task_type),
            _v2_p_key(task_type),
            _V2_HEARTBEAT_PREFIX,
            _V2_TASK_PREFIX,
            _V2_FENCING_PREFIX,
            _v2_corrupt_key(task_type),
            str(lease_sec),
            owner_token,
            str(settings.TASK_QUEUE_CORRUPT_MAX),
            str(_DEAD_HASH_TTL),
        )

    async def heartbeat_v2(
        self,
        task_or_id: Task | str,
        *,
        task_type: str | None = None,
        lease_sec: int = _DEFAULT_LEASE_SEC,
    ) -> int:
        """Extend task lease with v2 owner+generation fencing.

        Returns:
            1 — heartbeat accepted
            0 — owner mismatch (stale worker)
           -1 — generation mismatch (claim superseded)
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

        if not task_id or not task_type or not token:
            return 0

        if not self._redis_enabled:
            return 0

        try:
            client = await self._get_script_client()
            if client is None:
                return 0
            await self._load_scripts(client)

            # Note: Lua uses Redis TIME internally for lease expiry, not client time
            result = await self._evalsha_or_reload(
                client,
                "_lua_heartbeat_v2",
                4,
                _v2_p_key(task_type),
                _V2_HEARTBEAT_PREFIX,
                _V2_TASK_PREFIX,
                _V2_FENCING_PREFIX,
                task_id,
                str(lease_sec),
                token,
            )
            await client.aclose()

            result = int(result) if result is not None else 0
            if result == 0:
                logger.warning(
                    "v2 Heartbeat owner mismatch: task_id=%s",
                    task_id,
                )
                queue_metrics["owner_fencing_rejected"] += 1
            elif result == -1:
                logger.warning(
                    "v2 Heartbeat generation mismatch: task_id=%s",
                    task_id,
                )
                queue_metrics["owner_fencing_rejected"] += 1
            elif result == 1 and isinstance(task_or_id, Task):
                # Best-effort local lease estimate (Redis TIME is authoritative)
                task_or_id.lease_expires_at = time.time() + lease_sec

            return result

        except (redis_exc.ConnectionError, redis_exc.TimeoutError):
            raise

    async def complete_v2(
        self,
        task_or_id: Task | str,
        *,
        task_type: str | None = None,
    ) -> int:
        """Mark v2 task completed with owner+generation fencing.

        Returns:
            1 — success
            0 — owner mismatch
           -1 — generation mismatch (stale claim)
        """
        if isinstance(task_or_id, Task):
            task_id = task_or_id.task_id
            tt = task_or_id.task_type
            token = task_or_id.owner_token
        else:
            task_id = task_or_id
            tt = task_type or ""
            token = ""

        if not task_id or not tt or not token:
            return 0

        if not self._redis_enabled:
            return 0

        try:
            client = await self._get_script_client()
            if client is None:
                return 0
            await self._load_scripts(client)

            if isinstance(task_or_id, Task):
                task_data = task_or_id.to_dict()
                task_data.update(
                    {
                        "status": TaskStatus.COMPLETED.value,
                        "updated_at": time.time(),
                        "lease_expires_at": 0.0,
                        "owner_token": "",
                        "error": "",
                    }
                )
                task_json = json.dumps(task_data, default=str)
            else:
                current = await client.hget(_v2_task_hash_key(task_id), "data")
                data = (
                    json.loads(current)
                    if current
                    else {"task_id": task_id, "task_type": tt, "payload": {}}
                )
                data.update(
                    {
                        "status": "completed",
                        "updated_at": time.time(),
                        "lease_expires_at": 0.0,
                        "owner_token": "",
                        "error": "",
                    }
                )
                task_json = json.dumps(data, default=str)

            result = await self._evalsha_or_reload(
                client,
                "_lua_complete_v2",
                5,
                _v2_p_key(tt),
                _v2_retry_key(tt),
                _V2_TASK_PREFIX,
                _V2_HEARTBEAT_PREFIX,
                _V2_FENCING_PREFIX,
                task_id,
                token,
                task_json,
                str(_COMPLETED_TTL),
                str(_FENCING_TOMBSTONE_TTL),
            )
            await client.aclose()

            result = int(result) if result is not None else 0
            if result == 0:
                logger.warning("v2 Complete owner mismatch: task_id=%s", task_id)
                queue_metrics["owner_fencing_rejected"] += 1
            elif result == -1:
                logger.warning("v2 Complete generation mismatch: task_id=%s", task_id)
                queue_metrics["owner_fencing_rejected"] += 1
            else:
                if isinstance(task_or_id, Task):
                    task_or_id.status = TaskStatus.COMPLETED
                    task_or_id.updated_at = time.time()
                    task_or_id.lease_expires_at = 0.0
                    task_or_id.error = ""
                logger.info("v2 Task completed: task_id=%s", task_id)

            return result

        except (
            redis_exc.ConnectionError,
            redis_exc.TimeoutError,
            redis_exc.ResponseError,
        ) as exc:
            raise TaskQueueUnavailableError(
                f"Redis unavailable during complete: {exc}",
                retry_after=2,
            ) from exc
        except Exception as e:
            logger.warning("v2 Complete error: %s", e)
            return 0

    async def fail_v2(
        self,
        task_or_id: Task | str,
        error: str,
        *,
        task_type: str | None = None,
        lease_sec: int = _DEFAULT_LEASE_SEC,
    ) -> int:
        """Handle task failure with v2 owner+generation fencing.

        If retry ZSET is full, transitions directly to dead-letter
        (returns 2). Otherwise enqueues for retry (returns 1).

        Returns:
            1 — retry enqueued
            2 — dead-letter (retry full or exhausted)
            0 — owner mismatch
           -1 — generation mismatch
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

        if not task_id or not tt or not token:
            return 0

        if not self._redis_enabled:
            return 0

        retry_count = 0
        max_retries = _DEFAULT_MAX_RETRIES
        updated_at = time.time()
        if isinstance(task_or_id, Task):
            retry_count = task.retry_count + 1
            max_retries = task.max_retries

        try:
            client = await self._get_script_client()
            if client is None:
                return 0
            await self._load_scripts(client)

            if isinstance(task_or_id, Task) and retry_count < max_retries:
                delay = _DEFAULT_RETRY_BASE_DELAY * (2 ** (retry_count - 1))
                task_data = task.to_dict()
                task_data.update(
                    {
                        "status": TaskStatus.FAILED.value,
                        "retry_count": retry_count,
                        "error": error,
                        "updated_at": updated_at,
                        "lease_expires_at": 0.0,
                        "owner_token": "",
                    }
                )
                task_json = json.dumps(task_data, default=str)

                result = await self._evalsha_or_reload(
                    client,
                    "_lua_fail_retry_v2",
                    6,
                    _v2_p_key(tt),
                    _v2_retry_key(tt),
                    _v2_dead_key(tt),
                    _V2_TASK_PREFIX,
                    _V2_HEARTBEAT_PREFIX,
                    _V2_FENCING_PREFIX,
                    task_id,
                    str(delay),
                    task_json,
                    token,
                    str(retry_count),
                    error[:200],
                    str(settings.TASK_QUEUE_RETRY_MAX),
                    str(settings.TASK_QUEUE_DEAD_MAX),
                    str(_FENCING_TOMBSTONE_TTL),
                )
                await client.aclose()

                result = int(result) if result is not None else 0
                if result == 1:
                    task.retry_count = retry_count
                    task.error = error
                    task.updated_at = updated_at
                    task.status = TaskStatus.FAILED
                    task.lease_expires_at = 0.0
                    logger.warning(
                        "v2 Fail/retry (%d/%d, +%ds): task_id=%s",
                        retry_count,
                        max_retries,
                        delay,
                        task_id,
                    )
                elif result == 2:
                    task.retry_count = retry_count
                    task.error = error
                    task.updated_at = updated_at
                    task.status = TaskStatus.DEAD
                    task.lease_expires_at = 0.0
                    logger.warning(
                        "v2 Fail/retry-full dead: task_id=%s (retry ZSET full)",
                        task_id,
                    )
                elif result == 0:
                    logger.warning("v2 Fail/retry owner mismatch: task_id=%s", task_id)
                    queue_metrics["owner_fencing_rejected"] += 1
                elif result == -1:
                    logger.warning("v2 Fail/retry gen mismatch: task_id=%s", task_id)
                    queue_metrics["owner_fencing_rejected"] += 1
                return result

            # Dead-letter path
            if isinstance(task_or_id, Task):
                task_data = task.to_dict()
                task_data.update(
                    {
                        "status": TaskStatus.DEAD.value,
                        "retry_count": retry_count,
                        "error": error,
                        "lease_expires_at": 0.0,
                        "owner_token": "",
                        "updated_at": updated_at,
                    }
                )
                task_json = json.dumps(task_data, default=str)
            else:
                task_json = json.dumps(
                    {
                        "task_id": task_id,
                        "task_type": tt,
                        "payload": {},
                        "status": "dead",
                    },
                    default=str,
                )
            result = await self._evalsha_or_reload(
                client,
                "_lua_fail_dead_v2",
                5,
                _v2_p_key(tt),
                _v2_dead_key(tt),
                _V2_TASK_PREFIX,
                _V2_HEARTBEAT_PREFIX,
                _V2_FENCING_PREFIX,
                task_id,
                task_json,
                token,
                str(settings.TASK_QUEUE_DEAD_MAX),
                str(_FENCING_TOMBSTONE_TTL),
            )
            await client.aclose()

            result = int(result) if result is not None else 0
            if result == 1:
                if isinstance(task_or_id, Task):
                    task_or_id.retry_count = retry_count
                    task_or_id.error = error
                    task_or_id.updated_at = updated_at
                    task_or_id.status = TaskStatus.DEAD
                    task_or_id.lease_expires_at = 0.0
                logger.error("v2 Dead-letter: task_id=%s type=%s", task_id, tt)
            elif result == 0:
                logger.warning("v2 Fail/dead owner mismatch: task_id=%s", task_id)
                queue_metrics["owner_fencing_rejected"] += 1
            elif result == -1:
                logger.warning("v2 Fail/dead gen mismatch: task_id=%s", task_id)
                queue_metrics["owner_fencing_rejected"] += 1
            return result

        except (
            redis_exc.ConnectionError,
            redis_exc.TimeoutError,
            redis_exc.ResponseError,
        ) as exc:
            raise TaskQueueUnavailableError(
                f"Redis unavailable during fail transition: {exc}",
                retry_after=2,
            ) from exc
        except Exception as e:
            logger.warning("v2 Fail error: %s", e)
            return 0

    async def mark_corrupt_v2(
        self,
        task_id: str,
        task_type: str,
        error_summary: str = "",
    ) -> bool:
        """Atomically move a task from processing to corrupt collection."""
        if not self._redis_enabled:
            return False

        try:
            client = await self._get_script_client()
            if client is None:
                return False
            await self._load_scripts(client)

            result = await self._evalsha_or_reload(
                client,
                "_lua_mark_corrupt_v2",
                5,
                _v2_p_key(task_type),
                _v2_corrupt_key(task_type),
                _V2_TASK_PREFIX,
                _V2_HEARTBEAT_PREFIX,
                _V2_FENCING_PREFIX,
                task_id,
                error_summary,
                str(settings.TASK_QUEUE_CORRUPT_MAX),
                str(_FENCING_TOMBSTONE_TTL),
            )
            await client.aclose()
            return bool(result)

        except Exception as e:
            logger.warning("v2 Mark corrupt error: %s", e)
            return False

    async def cancel_v2(
        self,
        task_id: str,
        task_type: str,
        reason: str = "cancelled by admin",
    ) -> int:
        """Cancel a v2 task atomically using Lua.

        Behavior by task status:

        * ``pending`` → ``cancelled`` (removed from ready queue)
        * ``processing`` → ``cancel_requested`` (flag set, worker checks at heartbeat)
        * ``failed`` (retrying) → ``cancelled`` (removed from retry ZSET)
        * ``dead`` → ``cancelled`` (removed from dead list)
        * ``completed`` / ``cancelled`` / ``corrupt`` → no-op

        Returns:
            0 — already terminal or not found (idempotent)
            1 — pending → cancelled
            2 — processing → cancel_requested
            3 — retrying → cancelled
            4 — dead → cancelled
        """
        if not self._redis_enabled:
            return 0

        try:
            client = await self._get_script_client()
            if client is None:
                return 0
            await self._load_scripts(client)

            result = await self._evalsha_or_reload(
                client,
                "_lua_cancel_v2",
                7,
                _v2_q_key(task_type),
                _v2_p_key(task_type),
                _v2_retry_key(task_type),
                _v2_dead_key(task_type),
                _V2_HEARTBEAT_PREFIX,
                _V2_TASK_PREFIX,
                _V2_FENCING_PREFIX,
                task_id,
                reason[:200],
                str(_FENCING_TOMBSTONE_TTL),
            )
            await client.aclose()

            result = int(result) if result is not None else 0
            if result > 0:
                logger.info(
                    "v2 Cancel (code=%d): task_id=%s type=%s",
                    result,
                    task_id,
                    task_type,
                )
            return result

        except Exception as e:
            logger.warning("v2 Cancel error: %s", e)
            return 0

    async def _reclaim_expired_v2(self, task_type: str) -> int:
        """Reclaim expired v2 tasks whose worker heartbeat is gone."""
        if not self._redis_enabled:
            return 0

        try:
            client = await self._get_script_client()
            if client is None:
                return 0

            await self._load_scripts(client)
            reclaimed = (
                await self._evalsha_or_reload(
                    client,
                    "_lua_reaper_v2",
                    6,
                    _v2_p_key(task_type),
                    _v2_q_key(task_type),
                    _V2_HEARTBEAT_PREFIX,
                    _V2_TASK_PREFIX,
                    _v2_corrupt_key(task_type),
                    _V2_FENCING_PREFIX,
                    "100",
                    str(_get_max_ready(task_type)),
                    str(settings.TASK_QUEUE_CORRUPT_MAX),
                    str(_DEAD_HASH_TTL),
                )
                or 0
            )
            reclaimed = int(reclaimed)
            await client.aclose()

            if reclaimed:
                logger.info(
                    "v2 Reclaimed %d expired tasks for %s", reclaimed, task_type
                )
                queue_metrics["reaper_reclaimed"] += reclaimed

            return reclaimed

        except Exception as e:
            logger.warning("v2 Reclaim failed for %s: %s", task_type, e)
            return 0

    # ══════════════════════════════════════════════════════════════════════════
    # v2 Queue Health Methods (raise QueueHealthError on Redis error)
    # ══════════════════════════════════════════════════════════════════════════

    async def queue_length_v2(self, task_type: str) -> int:
        """v2 ready queue length. Raises QueueHealthError on Redis error."""
        if not self._redis_enabled:
            raise QueueHealthError("Redis is not configured")
        client = await self._get_script_client()
        if client is None:
            raise QueueHealthError("Cannot obtain Redis client")
        try:
            length = await client.llen(_v2_q_key(task_type))
            return length or 0
        except redis_exc.RedisError as e:
            raise QueueHealthError(f"Redis error: {e}") from e
        finally:
            await client.aclose()

    async def ready_length_v2(self, task_type: str) -> int:
        """Canonical name for the v2 ready-list length."""
        return await self.queue_length_v2(task_type)

    async def oldest_ready_age_v2(self, task_type: str) -> float:
        """Age of the oldest FIFO-ready task, based on its immutable payload."""
        if not self._redis_enabled:
            raise QueueHealthError("Redis is not configured")
        client = await self._get_script_client()
        if client is None:
            raise QueueHealthError("Cannot obtain Redis client")
        try:
            task_id = await client.lindex(_v2_q_key(task_type), 0)
            if not task_id:
                return 0.0
            raw = await client.hget(_v2_task_hash_key(task_id), "data")
            if not raw:
                return 0.0
            created_at = float(json.loads(raw).get("created_at", 0) or 0)
            return max(0.0, time.time() - created_at) if created_at else 0.0
        except (ValueError, TypeError, json.JSONDecodeError):
            return 0.0
        except redis_exc.RedisError as exc:
            raise QueueHealthError(f"Redis error: {exc}") from exc
        finally:
            await client.aclose()

    async def processing_length_v2(self, task_type: str) -> int:
        """v2 processing ZSET cardinality. Raises QueueHealthError on Redis error."""
        if not self._redis_enabled:
            raise QueueHealthError("Redis is not configured")
        client = await self._get_script_client()
        if client is None:
            raise QueueHealthError("Cannot obtain Redis client")
        try:
            return await client.zcard(_v2_p_key(task_type)) or 0
        except redis_exc.RedisError as e:
            raise QueueHealthError(f"Redis error: {e}") from e
        finally:
            await client.aclose()

    async def dead_length_v2(self, task_type: str) -> int:
        """v2 dead-letter list length. Raises QueueHealthError on Redis error."""
        if not self._redis_enabled:
            raise QueueHealthError("Redis is not configured")
        client = await self._get_script_client()
        if client is None:
            raise QueueHealthError("Cannot obtain Redis client")
        try:
            return await client.llen(_v2_dead_key(task_type)) or 0
        except redis_exc.RedisError as e:
            raise QueueHealthError(f"Redis error: {e}") from e
        finally:
            await client.aclose()

    async def retry_length_v2(self, task_type: str) -> int:
        """v2 retry ZSET cardinality. Raises QueueHealthError on Redis error."""
        if not self._redis_enabled:
            raise QueueHealthError("Redis is not configured")
        client = await self._get_script_client()
        if client is None:
            raise QueueHealthError("Cannot obtain Redis client")
        try:
            return await client.zcard(_v2_retry_key(task_type)) or 0
        except redis_exc.RedisError as e:
            raise QueueHealthError(f"Redis error: {e}") from e
        finally:
            await client.aclose()

    async def corrupt_length_v2(self, task_type: str) -> int:
        """v2 corrupt ZSET cardinality. Raises QueueHealthError on Redis error."""
        if not self._redis_enabled:
            raise QueueHealthError("Redis is not configured")
        client = await self._get_script_client()
        if client is None:
            raise QueueHealthError("Cannot obtain Redis client")
        try:
            return await client.zcard(_v2_corrupt_key(task_type)) or 0
        except redis_exc.RedisError as e:
            raise QueueHealthError(f"Redis error: {e}") from e
        finally:
            await client.aclose()

    async def get_metrics_v2(
        self, task_types: list[str] | None = None
    ) -> dict[str, Any]:
        """v2 queue metrics. Raises QueueHealthError on Redis error."""
        results = dict(queue_metrics)
        types = task_types or []

        ready = 0
        processing = 0
        retry_count = 0
        dead = 0

        for tt in types:
            ready += await self.queue_length_v2(tt)
            processing += await self.processing_length_v2(tt)
            retry_count += await self.retry_length_v2(tt)
            dead += await self.dead_length_v2(tt)

        results["ready"] = ready
        results["processing"] = processing
        results["retry"] = retry_count
        results["dead"] = dead
        return results

    # ══════════════════════════════════════════════════════════════════════════
    # v2 Dead/Corrupt Management API
    # ══════════════════════════════════════════════════════════════════════════

    async def list_dead_v2(self, task_type: str, limit: int = 100) -> list[dict]:
        """List dead-letter entries from v2 namespace (newest first)."""
        if not self._redis_enabled:
            return []
        try:
            client = await self._get_script_client()
            if client is None:
                return []
            task_ids = await client.lrange(_v2_dead_key(task_type), 0, limit - 1)
            result = []
            for tid in task_ids:
                raw = await client.hget(_v2_task_hash_key(tid), "data")
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
            logger.warning("v2 List dead failed: %s", e)
            return []

    async def purge_dead_v2(self, task_type: str, max_age_sec: int = 86400 * 7) -> int:
        """Remove old dead-letter entries from v2 namespace."""
        if not self._redis_enabled:
            return 0
        try:
            client = await self._get_script_client()
            if client is None:
                return 0
            dk = _v2_dead_key(task_type)
            task_ids = await client.lrange(dk, 0, -1)
            now = time.time()
            purged = 0
            for tid in task_ids:
                raw = await client.hget(_v2_task_hash_key(tid), "data")
                if raw:
                    try:
                        task_dict = json.loads(raw)
                        updated = task_dict.get("updated_at", 0)
                        if now - updated > max_age_sec:
                            await client.lrem(dk, 1, tid)
                            await client.delete(_v2_task_hash_key(tid))
                            purged += 1
                    except json.JSONDecodeError:
                        await client.lrem(dk, 1, tid)
                        purged += 1
                else:
                    await client.lrem(dk, 1, tid)
                    purged += 1
            await client.aclose()
            if purged:
                logger.info("v2 Purged %d old dead tasks for %s", purged, task_type)
            return purged
        except Exception as e:
            logger.warning("v2 Purge dead failed: %s", e)
            return 0

    async def list_corrupt_v2(self, task_type: str, limit: int = 100) -> list[dict]:
        """List corrupt entries from v2 namespace (newest first)."""
        if not self._redis_enabled:
            return []
        try:
            client = await self._get_script_client()
            if client is None:
                return []
            members = await client.zrange(
                _v2_corrupt_key(task_type),
                0,
                limit - 1,
                desc=True,
                withscores=True,
            )
            result = []
            for tid, score in members:
                raw = await client.hget(_v2_task_hash_key(tid), "data")
                entry = {"task_id": tid, "discovered_at": score}
                if raw:
                    try:
                        entry.update(json.loads(raw))
                    except json.JSONDecodeError:
                        entry["error"] = "corrupt_payload"
                result.append(entry)
            await client.aclose()
            return result
        except Exception as e:
            logger.warning("v2 List corrupt failed: %s", e)
            return []

    async def delete_from_dead_v2(self, task_type: str, task_id: str) -> bool:
        """Remove a specific task from v2 dead-letter list and delete its hash."""
        if not self._redis_enabled:
            return False
        try:
            client = await self._get_script_client()
            if client is None:
                return False
            dk = _v2_dead_key(task_type)
            await client.lrem(dk, 1, task_id)
            await client.delete(_v2_task_hash_key(task_id))
            await client.aclose()
            return True
        except Exception as e:
            logger.warning("v2 Delete from dead failed: %s", e)
            return False

    async def retry_from_dead_v2(self, task_type: str, task_id: str) -> bool:
        """Re-enqueue a dead-letter task to the v2 ready queue.

        An administrator retry is a *new retry cycle*: reset the exhausted retry
        budget and stale error fields while preserving the fencing generation.
        Previously only the Redis hash status was changed, leaving the JSON task
        payload at ``dead`` with its old ``retry_count``/``error``.  The next
        claim therefore inherited the exhausted retry budget and the admin UI
        continued to display the previous failure even after re-queueing.

        Returns True on success. The task's fencing key is NOT reset — the
        generation counter continues monotonically.
        """
        if not self._redis_enabled:
            return False
        client = None
        try:
            client = await self._get_script_client()
            if client is None:
                return False

            hash_key = _v2_task_hash_key(task_id)
            raw = await client.hget(hash_key, "data")
            if not raw:
                # The dead-list entry can outlive the task hash TTL. Remove all
                # duplicate stale entries so diagnostics do not keep surfacing it.
                await client.lrem(_v2_dead_key(task_type), 0, task_id)
                logger.warning("v2 Dead task hash expired: task_id=%s", task_id)
                return False

            try:
                task_data = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                logger.warning(
                    "v2 Dead task payload is corrupt: task_id=%s error=%s", task_id, exc
                )
                return False
            if not isinstance(task_data, dict):
                logger.warning(
                    "v2 Dead task payload is not an object: task_id=%s", task_id
                )
                return False
            if (
                task_data.get("task_id") != task_id
                or task_data.get("task_type") != task_type
            ):
                logger.warning(
                    "v2 Dead task identity mismatch: expected=%s/%s actual=%s/%s",
                    task_id,
                    task_type,
                    task_data.get("task_id"),
                    task_data.get("task_type"),
                )
                return False

            now = time.time()
            raw_schema_version = int(task_data.get("schema_version", 1) or 1)
            schema_version = _normalize_task_schema_version(
                task_type,
                raw_schema_version,
            )
            if task_type == ANSWER_PROJECTION_TASK_TYPE:
                parse_answer_projection_payload(task_data.get("payload"))
            required_worker = _minimum_worker_version_for_task(
                task_type, schema_version
            )
            task_data.update(
                {
                    "status": TaskStatus.PENDING.value,
                    "retry_count": 0,
                    "error": "",
                    "updated_at": now,
                    "lease_expires_at": 0.0,
                    "owner_token": "",
                    # Re-evaluate the worker floor for a fresh retry cycle. The
                    # schema itself was validated above and is never auto-upgraded.
                    "schema_version": schema_version,
                    "minimum_worker_version": max(
                        int(task_data.get("minimum_worker_version", 1) or 1),
                        required_worker,
                    ),
                }
            )
            task_json = json.dumps(task_data, default=str)

            # Keep the hash and embedded JSON metadata consistent.  LREM count=0
            # also heals duplicate dead-list entries left by older queue code.
            pipe = client.pipeline(transaction=True)
            pipe.lrem(_v2_dead_key(task_type), 0, task_id)
            pipe.hset(
                hash_key,
                mapping={
                    "data": task_json,
                    "status": TaskStatus.PENDING.value,
                    "retry_count": 0,
                    "error": "",
                    "owner_token": "",
                    "lease_expires_at": 0,
                },
            )
            pipe.rpush(_v2_q_key(task_type), task_id)
            await pipe.execute()
            logger.info(
                "v2 Retried from dead with fresh retry budget: task_id=%s", task_id
            )
            return True

        except Exception as e:
            logger.warning("v2 Retry from dead failed: %s", e)
            return False
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass

    async def delete_from_corrupt_v2(self, task_type: str, task_id: str) -> bool:
        """Remove a specific task from v2 corrupt ZSET."""
        if not self._redis_enabled:
            return False
        try:
            client = await self._get_script_client()
            if client is None:
                return False
            await client.zrem(_v2_corrupt_key(task_type), task_id)
            await client.aclose()
            return True
        except Exception as e:
            logger.warning("v2 Delete from corrupt failed: %s", e)
            return False

    async def get_task_v2(self, task_id: str) -> dict | None:
        """Retrieve a task by task_id from the v2 namespace.

        Returns the task hash contents (including "data", "status", etc.)
        or None if the task does not exist (hash missing or expired).

        This is a read-only inspection method used by the outbox reconciler
        and admin CLI. It does NOT modify any Redis state.

        Raises:
            QueueHealthError: Redis is unreachable.
        """
        if not self._redis_enabled:
            raise QueueHealthError("Redis is not configured")
        client = None
        try:
            client = await self._get_script_client()
            if client is None:
                raise QueueHealthError("Cannot obtain Redis client")
            if not await client.exists(_v2_task_hash_key(task_id)):
                return None
            raw = await client.hgetall(_v2_task_hash_key(task_id))
            if not raw:
                return None
            result: dict = {"task_id": task_id}
            for k, v in raw.items():
                if k == "data":
                    try:
                        result[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        result[k] = v
                else:
                    result[k] = v
            return result
        except redis_exc.RedisError as e:
            raise QueueHealthError(f"Redis error fetching task {task_id}: {e}") from e
        finally:
            # ``_get_script_client`` returns a wrapper backed by the shared pool;
            # closing it returns its connection even when EXISTS/HGETALL raised.
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass

    async def has_idempotency_v2(self, task_id: str) -> bool:
        """Return whether Redis still remembers an accepted v2 task id.

        Completed task hashes intentionally expire sooner than the v2
        idempotency guard.  The outbox reconciler uses this tombstone to
        distinguish normal task-hash expiry from actual Redis data loss.

        Raises:
            QueueHealthError: Redis is unreachable.
        """
        if not self._redis_enabled:
            raise QueueHealthError("Redis is not configured")
        client = None
        try:
            client = await self._get_script_client()
            if client is None:
                raise QueueHealthError("Cannot obtain Redis client")
            return bool(await client.exists(_v2_idempotent_key(task_id)))
        except redis_exc.RedisError as e:
            raise QueueHealthError(
                f"Redis error fetching idempotency guard {task_id}: {e}"
            ) from e
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass

    # ══════════════════════════════════════════════════════════════════════════
    # v1 → v2 Drain / Migration
    # ══════════════════════════════════════════════════════════════════════════

    async def drain_v1_to_v2(self, task_type: str, batch_size: int = 100) -> int:
        """Drain v1 ready queue tasks into v2 keys (one-time migration).

        Reads task_ids from v1 ready queue, reads their payloads from v1
        task hashes, and re-enqueues them into v2 keys. Tasks already in
        v2 (idempotent guard) are skipped.

        Tasks in v1 processing or retry are NOT drained — the reaper will
        clean them up after lease expiry. Those need to be handled via
        drain_active_v1_to_v2 instead.

        This is idempotent: running it multiple times only drains
        previously-undrained tasks.

        Returns count of migrated tasks.
        """
        if not self._redis_enabled:
            return 0
        migrated = 0
        try:
            client = await self._get_script_client()
            if client is None:
                return 0
            await self._load_scripts(client)

            for _ in range(batch_size):
                task_id = await client.lpop(_q_key(task_type))
                if not task_id:
                    break

                # Check v2 idempotent guard
                v2_idem_exists = await client.exists(_v2_idempotent_key(task_id))
                if v2_idem_exists:
                    logger.info("v1→v2 drain: task %s already in v2, skipping", task_id)
                    continue

                raw = await client.hget(_task_hash_key(task_id), "data")
                if not raw:
                    logger.warning(
                        "v1→v2 drain: task %s has no payload, skipping", task_id
                    )
                    continue

                # Re-enqueue into v2
                max_ready = _get_max_ready(task_type)
                result = await self._evalsha_or_reload(
                    client,
                    "_lua_enqueue_v2",
                    3,
                    _v2_q_key(task_type),
                    _V2_TASK_PREFIX,
                    _V2_IDEMPOTENCY_PREFIX,
                    task_id,
                    raw,
                    str(_IDEMPOTENT_TTL),
                    str(max_ready),
                )
                if result and result != "__duplicate__" and result != "__queue_full__":
                    migrated += 1

            await client.aclose()
            if migrated:
                logger.info(
                    "v1→v2 drain: migrated %d tasks for %s", migrated, task_type
                )
            return migrated
        except Exception as e:
            logger.warning("v1→v2 drain failed for %s: %s", task_type, e)
            return migrated

    async def drain_all_v1_to_v2(
        self, task_types: list[str] | None = None
    ) -> dict[str, int]:
        """Drain all v1 queues into v2. Returns {task_type: count_migrated}."""
        types = task_types or []
        results: dict[str, int] = {}
        for tt in types:
            results[tt] = await self.drain_v1_to_v2(tt)
        return results

    async def delete_v1_keys(self, task_type: str) -> dict[str, int]:
        """Delete v1 Redis keys for a task type (safe after drain).

        Returns counts of deleted keys by category.
        Only call after confirming no tasks remain in v1 keys.
        """
        if not self._redis_enabled:
            return {}
        deleted: dict[str, int] = {}
        try:
            client = await self._get_script_client()
            if client is None:
                return {}
            for name, key in [
                ("queue", _q_key(task_type)),
                ("processing", _p_key(task_type)),
                ("retry", _retry_key(task_type)),
                ("dead", _dead_key(task_type)),
                ("corrupt", _corrupt_key(task_type)),
            ]:
                count = await client.delete(key)
                deleted[name] = count
            await client.aclose()
            return deleted
        except Exception as e:
            logger.warning("v1 key deletion failed for %s: %s", task_type, e)
            return deleted


# Process-wide singleton
task_queue = DurableTaskQueue()
