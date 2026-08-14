"""Admin task queue management API.

GET  /api/admin/v1/tasks              — list/search tasks
GET  /api/admin/v1/tasks/{task_id}    — inspect a task
POST /api/admin/v1/tasks/{task_id}/retry  — retry from dead-letter
POST /api/admin/v1/tasks/{task_id}/cancel — cancel a task
GET  /api/admin/v1/tasks/queue-status — aggregated queue metrics
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.admin_security import require_permissions
from app.core.error_codes import ApiError, ErrorCode, task_not_found

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/v1/tasks", tags=["admin-tasks"])

TASK_TYPES = [
    "import_pipeline", "image_pipeline", "excel_pipeline",
    "resume_pipeline", "admin_resume", "batch_image",
    "formula_batch", "prewarm_analysis", "export_mistakes",
    "answer_projection",
]


# ── Response models ──


class TaskSummary(BaseModel):
    task_id: str
    task_type: str
    status: str
    retry_count: int = 0
    max_retries: int = 0
    generation: int = 0
    last_error: str | None = None
    created_at: str | None = None


class TaskDetail(TaskSummary):
    payload_summary: dict | None = None
    queue_location: str | None = None  # ready/processing/retry/dead/corrupt
    has_heartbeat: bool = False
    owner_token_prefix: str | None = None


class QueueStatus(BaseModel):
    task_type: str
    ready: int = 0
    processing: int = 0
    retry: int = 0
    dead: int = 0
    corrupt: int = 0


class QueueStatusResponse(BaseModel):
    queues: list[QueueStatus]
    totals: dict[str, int]


class TaskOperationResult(BaseModel):
    task_id: str
    operation: str
    success: bool
    message: str


class TaskListResponse(BaseModel):
    tasks: list[TaskSummary]
    total: int


# ── Helpers ──


async def _get_redis_client():
    """Get a Redis client or raise QUEUE_UNAVAILABLE."""
    from app.services.task_queue_service import task_queue

    try:
        client = await task_queue._get_client()
    except Exception as e:
        raise ApiError(ErrorCode.QUEUE_UNAVAILABLE, str(e), retryable=True) from e

    if client is None:
        raise ApiError(ErrorCode.QUEUE_UNAVAILABLE, "Redis not configured", retryable=False)
    return client


async def _resolve_task_type(task_id: str, client) -> str | None:
    """Find which task type queue contains a given task_id."""
    from app.services.task_queue_service import (
        _v2_corrupt_key,
        _v2_dead_key,
        _v2_p_key,
        _v2_q_key,
        _v2_retry_key,
        _v2_task_hash_key,
    )

    # Parse task_type from the JSON data blob in the task hash
    hash_key = _v2_task_hash_key(task_id)
    raw_data = await client.hget(hash_key, "data")
    if raw_data:
        try:
            parsed = json.loads(raw_data)
            tt = parsed.get("task_type")
            if tt:
                return tt
        except json.JSONDecodeError:
            pass

    # Fallback: search all queues by presence
    for tt in TASK_TYPES:
        if await client.lpos(_v2_q_key(tt), task_id) is not None:
            return tt
        if await client.zscore(_v2_p_key(tt), task_id) is not None:
            return tt
        if await client.zscore(_v2_retry_key(tt), task_id) is not None:
            return tt
        if await client.lpos(_v2_dead_key(tt), task_id) is not None:
            return tt
        if await client.zscore(_v2_corrupt_key(tt), task_id) is not None:
            return tt
    return None


def _parse_task_data(data: dict) -> dict:
    """Extract fields from the Redis hash, parsing the JSON 'data' blob.

    Redis hash fields: data (JSON), status, owner_token, generation,
    retry_count, lease_expires_at, error.
    Fields like task_type, max_retries, payload, created_at are inside
    the JSON 'data' blob, not top-level hash keys.
    """
    result: dict = {}
    raw_data = data.get("data", "")
    if raw_data:
        try:
            parsed = json.loads(raw_data)
            result["_parsed"] = parsed
        except json.JSONDecodeError:
            result["_parsed"] = {}
    else:
        result["_parsed"] = {}
    return result


# ── Routes ──


@router.get("/queue-status", response_model=QueueStatusResponse)
async def get_queue_status(
    _=Depends(require_permissions("import:read")),
):
    """Aggregated queue metrics across all task types."""
    from app.services.task_queue_service import task_queue

    queues: list[QueueStatus] = []
    totals: dict[str, int] = {"ready": 0, "processing": 0, "retry": 0, "dead": 0, "corrupt": 0}

    try:
        for tt in TASK_TYPES:
            ready = await task_queue.queue_length_v2(tt)
            proc = await task_queue.processing_length_v2(tt)
            retry = await task_queue.retry_length_v2(tt)
            dead = await task_queue.dead_length_v2(tt)
            corrupt = await task_queue.corrupt_length_v2(tt)

            totals["ready"] += ready
            totals["processing"] += proc
            totals["retry"] += retry
            totals["dead"] += dead
            totals["corrupt"] += corrupt

            if ready + proc + retry + dead + corrupt > 0:
                queues.append(QueueStatus(
                    task_type=tt, ready=ready, processing=proc,
                    retry=retry, dead=dead, corrupt=corrupt,
                ))
    except Exception as e:
        raise ApiError(ErrorCode.QUEUE_UNAVAILABLE, str(e), retryable=True) from e

    return QueueStatusResponse(queues=queues, totals=totals)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    task_type: str | None = Query(None, description="Filter by task type"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _=Depends(require_permissions("import:read")),
):
    """List tasks with optional filtering. Searches dead-letter and corrupt queues."""
    from app.services.task_queue_service import (
        _v2_corrupt_key,
        _v2_task_hash_key,
    )

    client = await _get_redis_client()

    result_tasks: list[TaskSummary] = []
    types_to_search = [task_type] if task_type else TASK_TYPES

    try:
        for tt in types_to_search:
            # List dead tasks
            dead_entries = await client.lrange(f"taskq:v2:dead:{tt}", 0, -1)
            for task_id in dead_entries:
                hash_key = _v2_task_hash_key(task_id)
                data = await client.hgetall(hash_key)
                if not data:
                    continue
                if status and data.get("status") != status:
                    continue
                parsed = _parse_task_data(data)._parsed
                result_tasks.append(TaskSummary(
                    task_id=task_id,
                    task_type=parsed.get("task_type", tt),
                    status=data.get("status", "dead"),
                    retry_count=int(data.get("retry_count", 0)),
                    max_retries=int(parsed.get("max_retries", 0)),
                    generation=int(data.get("generation", 0)),
                    last_error=data.get("error", "")[:200] if data.get("error") else None,
                    created_at=parsed.get("created_at"),
                ))

            # List corrupt tasks
            corrupt_entries = await client.zrange(_v2_corrupt_key(tt), 0, -1)
            for task_id in corrupt_entries:
                hash_key = _v2_task_hash_key(task_id)
                data = await client.hgetall(hash_key)
                if not data:
                    continue
                if status and data.get("status") != status:
                    continue
                parsed = _parse_task_data(data)._parsed
                result_tasks.append(TaskSummary(
                    task_id=task_id,
                    task_type=parsed.get("task_type", tt),
                    status=data.get("status", "corrupt"),
                    retry_count=int(data.get("retry_count", 0)),
                    max_retries=int(parsed.get("max_retries", 0)),
                    generation=int(data.get("generation", 0)),
                    last_error=data.get("error", "")[:200] if data.get("error") else None,
                    created_at=parsed.get("created_at"),
                ))
    finally:
        pass  # client is managed by the queue service

    total = len(result_tasks)
    result_tasks = result_tasks[offset:offset + limit]

    return TaskListResponse(tasks=result_tasks, total=total)


@router.get("/{task_id}", response_model=TaskDetail)
async def inspect_task(
    task_id: str,
    _=Depends(require_permissions("import:read")),
):
    """Inspect a specific task. Returns safe summary only (no tokens or full payload)."""
    from app.services.task_queue_service import (
        _v2_corrupt_key,
        _v2_dead_key,
        _v2_heartbeat_key,
        _v2_p_key,
        _v2_q_key,
        _v2_retry_key,
        _v2_task_hash_key,
    )

    client = await _get_redis_client()

    hash_key = _v2_task_hash_key(task_id)
    data = await client.hgetall(hash_key)

    if not data:
        raise task_not_found(task_id)

    parsed = _parse_task_data(data)._parsed
    task_type = parsed.get("task_type", "")
    status = data.get("status", "unknown")

    # Determine queue location
    queue_location = None
    if task_type:
        if await client.lpos(_v2_q_key(task_type), task_id) is not None:
            queue_location = "ready"
        elif await client.zscore(_v2_p_key(task_type), task_id) is not None:
            queue_location = "processing"
        elif await client.zscore(_v2_retry_key(task_type), task_id) is not None:
            queue_location = "retry"
        elif await client.lpos(_v2_dead_key(task_type), task_id) is not None:
            queue_location = "dead"
        elif await client.zscore(_v2_corrupt_key(task_type), task_id) is not None:
            queue_location = "corrupt"

    # Safe payload summary
    payload_summary = None
    payload_raw = parsed.get("payload", "")
    if isinstance(payload_raw, dict):
        payload_summary = {
            k: v for k, v in payload_raw.items()
            if k not in ("file_content", "token", "secret", "password")
        }
    elif isinstance(payload_raw, str) and payload_raw:
        try:
            payload = json.loads(payload_raw)
            payload_summary = {
                k: v for k, v in payload.items()
                if k not in ("file_content", "token", "secret", "password")
            }
        except json.JSONDecodeError:
            payload_summary = {"_raw_str": payload_raw[:200]}

    # Heartbeat check
    hb = await client.get(_v2_heartbeat_key(task_id))
    has_heartbeat = hb is not None

    owner_prefix = None
    owner_token = data.get("owner_token", "")
    if owner_token:
        owner_prefix = owner_token[:16]

    return TaskDetail(
        task_id=task_id,
        task_type=task_type,
        status=status,
        retry_count=int(data.get("retry_count", 0)),
        max_retries=int(parsed.get("max_retries", 0)),
        generation=int(data.get("generation", 0)),
        last_error=data.get("error", "")[:200] if data.get("error") else None,
        created_at=parsed.get("created_at"),
        payload_summary=payload_summary,
        queue_location=queue_location,
        has_heartbeat=has_heartbeat,
        owner_token_prefix=owner_prefix,
    )


@router.post("/{task_id}/retry", response_model=TaskOperationResult)
async def retry_task(
    task_id: str,
    _=Depends(require_permissions("import:write")),
):
    """Retry a failed/dead/review_required task from dead-letter."""
    from app.services.task_queue_service import _v2_task_hash_key, task_queue

    client = await _get_redis_client()

    hash_key = _v2_task_hash_key(task_id)
    data = await client.hgetall(hash_key)

    if not data:
        raise task_not_found(task_id)

    parsed = _parse_task_data(data)._parsed
    task_type = parsed.get("task_type", "")
    status = data.get("status", "")

    if status not in ("failed", "dead", "review_required"):
        raise HTTPException(
            status_code=400,
            detail=f"Task status '{status}' is not retryable. Only failed/dead/review_required tasks can be retried.",
        )

    ok = await task_queue.retry_from_dead_v2(task_type, task_id)
    if ok:
        logger.info("Admin retry: task_id=%s type=%s", task_id, task_type)
        return TaskOperationResult(
            task_id=task_id,
            operation="retry",
            success=True,
            message=f"Task {task_id} re-queued from dead-letter.",
        )
    else:
        return TaskOperationResult(
            task_id=task_id,
            operation="retry",
            success=False,
            message=f"Failed to re-queue task {task_id}. It may not be in dead-letter.",
        )


@router.post("/{task_id}/cancel", response_model=TaskOperationResult)
async def cancel_task(
    task_id: str,
    _=Depends(require_permissions("import:write")),
):
    """Cancel a pending/retry task or request cancellation for a processing task.

    Uses the atomic ``cancel_v2`` Lua script which handles all task states
    (pending → cancelled, processing → cancel_requested, retry → cancelled,
    dead → cancelled, terminal → no-op).
    """
    from app.services.task_queue_service import (
        _v2_task_hash_key,
        task_queue,
    )

    client = await _get_redis_client()
    hash_key = _v2_task_hash_key(task_id)
    data = await client.hgetall(hash_key)

    if not data:
        await client.aclose()
        raise task_not_found(task_id)

    parsed = _parse_task_data(data)._parsed
    task_type = parsed.get("task_type", "")
    await client.aclose()

    if not task_type:
        raise HTTPException(status_code=400, detail=f"Cannot determine task_type for {task_id}")

    reason = "cancelled by admin"
    result = await task_queue.cancel_v2(task_id, task_type, reason=reason)

    messages = {
        1: f"Task {task_id} cancelled (was pending).",
        2: f"Cancellation requested for task {task_id}. Worker will stop at next safe checkpoint.",
        3: f"Task {task_id} cancelled (was retrying).",
        4: f"Task {task_id} cancelled (was in dead-letter).",
    }
    if result in messages:
        logger.info("Admin cancel: task_id=%s type=%s code=%d", task_id, task_type, result)
        return TaskOperationResult(
            task_id=task_id,
            operation="cancel",
            success=True,
            message=messages[result],
        )
    elif result == 0:
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} not found or already in terminal state (completed/cancelled/corrupt).",
        )
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Cancel failed for task {task_id} (error code {result}).",
        )
