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
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.core.error_codes import ApiError, ErrorCode, task_not_found
from app.schemas.observability import TaskDiagnosticsResponse, TaskTraceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/v1/tasks", tags=["admin-tasks"])

TASK_TYPES = [
    "import_pipeline", "image_pipeline", "excel_pipeline",
    "resume_pipeline", "admin_resume", "batch_image",
    "formula_batch", "prewarm_analysis", "export_mistakes",
    "answer_projection", "ocr_pipeline",
]


# ── Response models ──


class TaskSummary(BaseModel):
    task_id: str
    task_type: str
    status: str
    queue_location: str | None = None
    retry_count: int = 0
    max_retries: int = 0
    generation: int = 0
    trace_id: str | None = None
    request_id: str | None = None
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


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


class ScheduledTaskSummary(BaseModel):
    task_id: str
    name: str
    description: str
    task_type: str = "scheduled"
    executor: str = "scheduler"
    status: str
    enabled: bool
    schedule: str
    next_run_at: str | None = None
    next_run_label: str | None = None
    last_run_at: str | None = None
    last_status: str | None = None
    last_message: str | None = None
    last_duration_ms: int | None = None
    last_source: str | None = None
    can_run_now: bool = False
    executor_available: bool | None = None
    executor_state: str | None = None
    note: str | None = None
    artifact_name: str | None = None
    artifact_size_bytes: int | None = None
    artifact_created_at: str | None = None
    backup_count: int | None = None
    script_available: bool | None = None
    pg_dump_available: bool | None = None
    timer_unit: str | None = None
    service_unit: str | None = None
    service_loaded: bool | None = None


class ScheduledTaskListResponse(BaseModel):
    generated_at: str
    tasks: list[ScheduledTaskSummary]


class DatabaseBackupArtifact(BaseModel):
    name: str
    size_bytes: int
    created_at: str
    method: str | None = None
    database: str | None = None


class DatabaseBackupHistoryResponse(BaseModel):
    items: list[DatabaseBackupArtifact]
    total: int


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
    """Parse the JSON ``data`` field stored in a Redis v2 task hash."""
    raw_data = data.get("data", "")
    if isinstance(raw_data, dict):
        return raw_data
    if raw_data:
        try:
            parsed = json.loads(raw_data)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _format_task_timestamp(value) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value), UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return str(value)[:64]


# ── Routes ──


_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


@router.get("/diagnostics", response_model=TaskDiagnosticsResponse)
async def task_diagnostics(
    _=Depends(require_permissions("system:read")),
    db: AsyncSession = Depends(get_db),
):
    """Return a live PostgreSQL + Redis + answer-projection health snapshot."""
    from app.services.task_observability_service import collect_task_diagnostics

    return await collect_task_diagnostics(db)


@router.get("/trace/{trace_id}", response_model=TaskTraceResponse)
async def trace_task_lifecycle(
    trace_id: str,
    limit: int = Query(50, ge=1, le=100),
    _=Depends(require_permissions("system:read")),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a trace id to its durable outbox/queue/projection lifecycle."""
    if not _TRACE_ID_RE.fullmatch(trace_id):
        raise HTTPException(status_code=400, detail="Invalid trace id")

    from app.services.task_observability_service import find_trace_tasks

    return await find_trace_tasks(db, trace_id=trace_id, limit=limit)


@router.get("/queue-status", response_model=QueueStatusResponse)
async def get_queue_status(
    _=Depends(require_permissions("system:read")),
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


@router.get("/scheduled", response_model=ScheduledTaskListResponse)
async def list_scheduled_tasks(
    _=Depends(require_permissions("system:read")),
):
    """List recurring scheduler jobs with cross-process execution telemetry."""
    from app.core.time_utils import serialize_utc_datetime, utcnow
    from app.services.system_task_service import list_system_scheduled_tasks

    tasks = await list_system_scheduled_tasks()
    return ScheduledTaskListResponse(
        generated_at=serialize_utc_datetime(utcnow()),
        tasks=[ScheduledTaskSummary(**item) for item in tasks],
    )


@router.get("/system/postgres-backup/history", response_model=DatabaseBackupHistoryResponse)
async def postgres_backup_history(
    limit: int = Query(10, ge=1, le=50),
    _=Depends(require_permissions("system:backup")),
):
    """List recent PostgreSQL backup artifacts visible to the admin service."""
    from app.services.database_backup_service import inspect_database_backup, list_backup_artifacts

    info = await inspect_database_backup()
    items = list_backup_artifacts(limit)
    return DatabaseBackupHistoryResponse(
        items=[
            DatabaseBackupArtifact(
                name=str(item.get("name") or ""),
                size_bytes=int(item.get("size_bytes") or 0),
                created_at=str(item.get("created_at") or ""),
                method=item.get("method"),
                database=item.get("database"),
            )
            for item in items
        ],
        total=int(info.get("backup_count") or len(items)),
    )


@router.post("/scheduled/{task_id}/run", response_model=TaskOperationResult)
async def run_scheduled_task(
    task_id: str,
    current_admin=Depends(require_permissions("system:write")),
    db: AsyncSession = Depends(get_db),
):
    """Run a recurring maintenance job with explicit system privileges.

    Database backup requires the additional ``system:backup`` permission even
    when the caller can run other system maintenance tasks.
    """
    if task_id == "postgres_backup":
        from app.services.admin_auth_service import get_admin_permission_names

        granted = set(await get_admin_permission_names(db, current_admin.role_id))
        if "system:backup" not in granted:
            raise HTTPException(status_code=403, detail="Permission denied")

    from app.services.system_task_service import run_scheduled_task_now

    try:
        outcome = await run_scheduled_task_now(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown scheduled task: {task_id}")
    except Exception as exc:
        logger.exception("Admin scheduled task run failed: task_id=%s", task_id)
        raise HTTPException(status_code=500, detail=str(exc)[:300]) from exc

    return TaskOperationResult(
        task_id=task_id,
        operation="run_now",
        success=outcome.status == "success",
        message=outcome.message,
    )


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    task_type: str | None = Query(None, description="Filter by task type"),
    status: str | None = Query(None, description="Filter by task status or queue location"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _=Depends(require_permissions("system:read")),
):
    """List live async task instances across ready/processing/retry/dead/corrupt queues."""
    from app.services.task_queue_service import (
        _v2_corrupt_key,
        _v2_dead_key,
        _v2_p_key,
        _v2_q_key,
        _v2_retry_key,
        _v2_task_hash_key,
    )

    client = await _get_redis_client()
    types_to_search = [task_type] if task_type else TASK_TYPES
    result_tasks: list[TaskSummary] = []
    seen: set[str] = set()

    async def append_tasks(tt: str, location: str, task_ids: list[str]) -> None:
        for task_id in task_ids:
            if task_id in seen:
                continue
            seen.add(task_id)
            data = await client.hgetall(_v2_task_hash_key(task_id))
            if not data:
                continue
            parsed = _parse_task_data(data)
            task_status = data.get("status") or location
            if status and status not in (task_status, location):
                continue
            result_tasks.append(TaskSummary(
                task_id=task_id,
                task_type=parsed.get("task_type", tt),
                status=task_status,
                queue_location=location,
                retry_count=int(data.get("retry_count", 0)),
                max_retries=int(parsed.get("max_retries", 0)),
                generation=int(data.get("generation", 0)),
                trace_id=str(parsed.get("trace_id") or "") or None,
                request_id=str(parsed.get("request_id") or "") or None,
                last_error=data.get("error", "")[:200] if data.get("error") else None,
                created_at=_format_task_timestamp(parsed.get("created_at")),
                updated_at=_format_task_timestamp(parsed.get("updated_at")),
            ))

    for tt in types_to_search:
        ready_ids = await client.lrange(_v2_q_key(tt), 0, -1)
        processing_ids = await client.zrange(_v2_p_key(tt), 0, -1)
        retry_ids = await client.zrange(_v2_retry_key(tt), 0, -1)
        dead_ids = await client.lrange(_v2_dead_key(tt), 0, -1)
        corrupt_ids = await client.zrange(_v2_corrupt_key(tt), 0, -1)
        await append_tasks(tt, "ready", ready_ids)
        await append_tasks(tt, "processing", processing_ids)
        await append_tasks(tt, "retry", retry_ids)
        await append_tasks(tt, "dead", dead_ids)
        await append_tasks(tt, "corrupt", corrupt_ids)

    def sort_key(item: TaskSummary):
        return item.updated_at or item.created_at or ""

    result_tasks.sort(key=sort_key, reverse=True)
    total = len(result_tasks)
    return TaskListResponse(tasks=result_tasks[offset:offset + limit], total=total)


@router.get("/{task_id}", response_model=TaskDetail)
async def inspect_task(
    task_id: str,
    _=Depends(require_permissions("system:read")),
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

    parsed = _parse_task_data(data)
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
        trace_id=str(parsed.get("trace_id") or "") or None,
        request_id=str(parsed.get("request_id") or "") or None,
        last_error=data.get("error", "")[:200] if data.get("error") else None,
        created_at=_format_task_timestamp(parsed.get("created_at")),
        updated_at=_format_task_timestamp(parsed.get("updated_at")),
        payload_summary=payload_summary,
        queue_location=queue_location,
        has_heartbeat=has_heartbeat,
        owner_token_prefix=owner_prefix,
    )


@router.post("/outbox/{outbox_id}/retry", response_model=TaskOperationResult)
async def retry_outbox(
    outbox_id: int,
    _=Depends(require_permissions("system:write")),
    db: AsyncSession = Depends(get_db),
):
    """Reset a permanently failed Outbox row to pending for normal dispatch."""
    from app.services.outbox_service import retry_failed_outbox

    row = await retry_failed_outbox(db, outbox_id)
    if row is None:
        raise HTTPException(status_code=409, detail="Outbox row is not in failed state")
    return TaskOperationResult(
        task_id=row.task_id,
        operation="outbox_retry",
        success=True,
        message="Outbox task scheduled for retry.",
    )


@router.post("/{task_id}/retry", response_model=TaskOperationResult)
async def retry_task(
    task_id: str,
    _=Depends(require_permissions("system:write")),
):
    """Retry a failed/dead/review_required task from dead-letter."""
    from app.services.task_queue_service import _v2_task_hash_key, task_queue

    client = await _get_redis_client()

    hash_key = _v2_task_hash_key(task_id)
    data = await client.hgetall(hash_key)

    if not data:
        raise task_not_found(task_id)

    parsed = _parse_task_data(data)
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
    _=Depends(require_permissions("system:write")),
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

    parsed = _parse_task_data(data)
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
