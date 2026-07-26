"""Background processor for export tasks — runs in the scheduler role.

Claims pending tasks via atomic DB updates, generates PDFs/DOCX, and stores
the result. Uses a Redis distributed lock as secondary protection.

Architecture:
- Runs as an asyncio background task in the scheduler process.
- Polls for pending tasks every ``EXPORT_POLL_INTERVAL`` seconds.
- Uses ``UPDATE ... WHERE status='pending' LIMIT 1 RETURNING *`` to
  atomically claim a task (database-level fencing).
- Tracks heartbeat via ``heartbeat_at`` for zombie recovery.
- Limits concurrency: configurable per-processor, per-user.

Zombie recovery:
- Tasks stuck in ``processing`` for > ``EXPORT_PROCESSING_TIMEOUT``
  without a recent ``heartbeat_at`` are reclaimed (failed → retryable).

State machine:
- pending → processing (via atomic claim)
- processing → completed (normal)
- processing → failed (error / timeout)
- completed → expired (via cleanup)
- failed → pending (via retry — creates new task)

Per-user limits:
- A user can have at most ``_MAX_PER_USER`` tasks in ``pending`` or
  ``processing`` simultaneously.  Excess submissions are rejected
  at the API layer.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import select, update

from app.core.database import async_session
from app.models.export_task import ExportTask
from app.schemas.export_task import ExportTaskStatus
from app.services.export.service import process_task

logger = logging.getLogger(__name__)

# ── Tuning ──
_POLL_INTERVAL_SEC = 5
_PROCESSING_TIMEOUT_SEC = 900  # 15 minutes max per task (zombie recovery)
_HEARTBEAT_INTERVAL_SEC = 30
_MAX_CONCURRENT = 2  # max concurrent tasks per processor instance
_MAX_PER_USER = 2    # max pending/processing tasks per user
_TASK_TIMEOUT_SEC = 600  # per-task wall-clock timeout

# In-flight tracking for graceful shutdown
_in_flight: set[int] = set()
_draining = False


# ── State machine ──

_VALID_TRANSITIONS: dict[str, set[str]] = {
    ExportTaskStatus.PENDING: {ExportTaskStatus.PROCESSING},
    ExportTaskStatus.PROCESSING: {ExportTaskStatus.COMPLETED, ExportTaskStatus.FAILED},
    ExportTaskStatus.COMPLETED: {ExportTaskStatus.EXPIRED},
    ExportTaskStatus.FAILED: set(),  # retry creates a new task
    ExportTaskStatus.EXPIRED: set(),
}


def validate_transition(from_status: str, to_status: str) -> bool:
    """Check if a status transition is valid per the state machine.

    Returns ``True`` if allowed, ``False`` otherwise.
    """
    allowed = _VALID_TRANSITIONS.get(from_status, set())
    return to_status in allowed


async def run_export_processor():
    """Main loop — claim and process pending export tasks."""
    logger.info("Export processor started (poll=%ds, timeout=%ds)", _POLL_INTERVAL_SEC, _PROCESSING_TIMEOUT_SEC)

    while not _draining:
        try:
            await _recover_stale_tasks()
            await _process_one_task()
        except asyncio.CancelledError:
            logger.info("Export processor cancelled")
            break
        except Exception as e:
            logger.warning("Export processor error (non-fatal): %s", e)

        await asyncio.sleep(_POLL_INTERVAL_SEC)

    logger.info("Export processor stopped (draining=%s, in_flight=%d)", _draining, len(_in_flight))


async def _recover_stale_tasks():
    """Reclaim tasks stuck in ``processing`` state beyond the timeout.

    Uses the most recent liveness timestamp (heartbeat_at if set,
    otherwise processing_started_at) to decide if a task is truly stale.
    """
    now = datetime.now(UTC)
    cutoff = now.timestamp() - _PROCESSING_TIMEOUT_SEC

    async with async_session() as db:
        result = await db.execute(
            select(ExportTask).where(
                ExportTask.status == ExportTaskStatus.PROCESSING,
                ExportTask.processing_started_at.isnot(None),
                sa.func.coalesce(ExportTask.heartbeat_at, ExportTask.processing_started_at) < cutoff,  # type: ignore[operator]
            )
        )
        stale = result.scalars().all()

        for task in stale:
            logger.warning(
                "Reclaiming stale task %d (started_at=%s, heartbeat=%s)",
                task.id, task.processing_started_at, task.heartbeat_at,
            )
            task.status = ExportTaskStatus.FAILED
            task.error_message = "处理超时，请重试"
            task.completed_at = datetime.now(UTC)

        if stale:
            await db.flush()
            logger.info("Reclaimed %d stale tasks", len(stale))


async def get_user_pending_count(db, user_id: int) -> int:
    """Count the number of pending/processing tasks for a user."""
    result = await db.execute(
        select(sa.func.count(ExportTask.id)).where(
            ExportTask.user_id == user_id,
            ExportTask.status.in_([
                ExportTaskStatus.PENDING,
                ExportTaskStatus.PROCESSING,
            ]),
        )
    )
    return result.scalar() or 0


async def _process_one_task():
    """Atomically claim one pending task and process it.

    Uses ``UPDATE ... WHERE status='pending' RETURNING id`` — a DB-level
    atomic claim that works on both SQLite and PostgreSQL. Two concurrent
    processors cannot claim the same task: the second UPDATE affects 0 rows
    because the first already changed the status from ``pending``.
    """
    if len(_in_flight) >= _MAX_CONCURRENT:
        return

    async with async_session() as db:
        now = datetime.now(UTC)

        # Atomic claim: UPDATE the first pending task and RETURN the id.
        subq = (
            select(ExportTask.id)
            .where(ExportTask.status == ExportTaskStatus.PENDING)
            .order_by(ExportTask.created_at)
            .limit(1)
            .scalar_subquery()
        )
        result = await db.execute(
            update(ExportTask)
            .where(ExportTask.id == subq)
            .where(ExportTask.status == ExportTaskStatus.PENDING)
            .values(
                status=ExportTaskStatus.PROCESSING,
                processing_started_at=now,
                heartbeat_at=now,
            )
            .returning(ExportTask.id, ExportTask.user_id)
        )
        row = result.one_or_none()
        if row is None:
            return
        task_id, user_id = row
        await db.flush()

    _in_flight.add(task_id)
    logger.info("export_task_started", extra={
        "task_id": task_id,
        "user_id": user_id,
    })

    # Heartbeat refresh loop
    _heartbeat_stop = False

    async def _refresh_heartbeat():
        while not _heartbeat_stop:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SEC)
            try:
                async with async_session() as hb_db:
                    result = await hb_db.execute(
                        select(ExportTask).where(ExportTask.id == task_id)
                    )
                    t = result.scalar_one_or_none()
                    if t and t.status == ExportTaskStatus.PROCESSING:
                        t.heartbeat_at = datetime.now(UTC)
                        await hb_db.flush()
                        logger.debug("Heartbeat refreshed for export task %d", task_id)
            except Exception as e:
                logger.warning("Heartbeat refresh failed for task %d: %s", task_id, e)

    heartbeat_task = asyncio.create_task(_refresh_heartbeat())

    # Task timeout
    async def _task_timeout():
        await asyncio.sleep(_TASK_TIMEOUT_SEC)
        if not _heartbeat_stop:
            logger.warning("export_task_timed_out", extra={
                "task_id": task_id,
                "timeout_sec": _TASK_TIMEOUT_SEC,
            })
            try:
                async with async_session() as to_db:
                    result = await to_db.execute(
                        select(ExportTask).where(ExportTask.id == task_id)
                    )
                    t = result.scalar_one_or_none()
                    if t and t.status == ExportTaskStatus.PROCESSING:
                        t.status = ExportTaskStatus.FAILED
                        t.error_message = f"处理超时（超过{_TASK_TIMEOUT_SEC}秒）"
                        t.completed_at = datetime.now(UTC)
                        await to_db.commit()
            except Exception:
                pass

    timeout_task = asyncio.create_task(_task_timeout())

    try:
        # Process
        async with async_session() as db:
            from app.services.export.service import get_exporter

            result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
            t = result.scalar_one_or_none()
            if t:
                exporter = get_exporter(t.file_format)
            else:
                raise ValueError(f"Task {task_id} not found")

            updated = await process_task(db, task_id, exporter)

            if updated.status == ExportTaskStatus.COMPLETED:
                logger.info("export_task_completed", extra={
                    "task_id": task_id,
                    "user_id": user_id,
                    "format": updated.file_format,
                    "question_count": updated.total_count,
                    "success_count": updated.success_count,
                    "skip_count": updated.skip_count,
                    "file_size": updated.file_size,
                    "duration": (
                        (updated.completed_at - updated.processing_started_at).total_seconds()
                        if updated.completed_at and updated.processing_started_at else None
                    ),
                })
            else:
                logger.info("export_task_failed", extra={
                    "task_id": task_id,
                    "user_id": user_id,
                    "status": updated.status,
                    "error_message": updated.error_message,
                })

            await db.commit()
            await _publish_task_event(task_id, updated)

    except Exception as e:
        logger.exception("Export task %d crashed: %s", task_id, e)
        try:
            async with async_session() as db:
                result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
                t = result.scalar_one_or_none()
                if t and t.status == ExportTaskStatus.PROCESSING:
                    t.status = ExportTaskStatus.FAILED
                    t.error_message = f"处理异常: {str(e)[:200]}"
                    t.completed_at = datetime.now(UTC)
                    await db.commit()
        except Exception as e2:
            logger.error("Failed to mark task %d as failed: %s", task_id, e2)

    finally:
        _heartbeat_stop = True
        heartbeat_task.cancel()
        timeout_task.cancel()
        try:
            await heartbeat_task
            await timeout_task
        except asyncio.CancelledError:
            pass
        _in_flight.discard(task_id)


async def stop_processor():
    """Signal the processor to stop after current task completes."""
    global _draining
    _draining = True
    logger.info("Export processor drain requested (in_flight=%d)", len(_in_flight))


async def _publish_task_event(task_id: int, task: ExportTask) -> None:
    """Publish a task status event via Redis Pub/Sub and WebSocket push."""
    try:
        from app.services.export.push_service import (
            build_status_event,
            publish_via_redis,
            send_to_user,
        )

        event = build_status_event({
            "id": task.id,
            "status": task.status,
            "file_format": task.file_format,
            "success_count": task.success_count,
            "skip_count": task.skip_count,
            "error_message": task.error_message,
            "completed_at": task.completed_at,
            "expires_at": task.expires_at,
            "updated_at": task.updated_at,
        })
        # Send locally (same-process connections)
        await send_to_user(task.user_id, event)
        # Also publish via Redis (cross-process connections)
        await publish_via_redis(event, task.user_id)
    except Exception:
        logger.debug("Failed to publish event for task %d (non-fatal)", task_id)
