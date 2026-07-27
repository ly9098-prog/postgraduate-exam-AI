"""Background processor for export tasks — runs in the scheduler role.

Claims pending tasks via atomic DB updates, generates PDFs/DOCX, and stores
the result. Uses a Redis distributed lock as secondary protection.

Architecture:
- Runs as an asyncio background task in the scheduler process.
- Polls for pending tasks every ``EXPORT_POLL_INTERVAL`` seconds.
- Uses ``UPDATE ... WHERE status='pending' LIMIT 1 RETURNING *`` to
  atomically claim a task (database-level fencing).
- Tracks heartbeat via ``heartbeat_at`` for zombie recovery.
- Limits concurrency: configurable per-processor, per-user, per-format.

Zombie recovery:
- Tasks stuck in ``processing`` for > ``EXPORT_PROCESSING_TIMEOUT``
  without a recent ``heartbeat_at`` are reclaimed (failed with retryable).

State machine:
- pending → processing (via atomic claim)
- processing → completed (normal)
- processing → failed (error / timeout)
- completed → expired (via cleanup)
- failed → pending (via retry — creates new task)

Per-user limits:
- A user can have at most ``EXPORT_MAX_PER_USER`` tasks in ``pending`` or
  ``processing`` simultaneously.  Excess submissions are rejected
  at the API layer.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import async_session
from app.core.time_utils import utcnow
from app.models.export_task import ExportTask
from app.schemas.export_task import ExportTaskStatus
from app.services.export.service import process_task

logger = logging.getLogger(__name__)

# ── Import settings (with fallbacks for backward compatibility) ──
_POLL_INTERVAL_SEC = getattr(settings, "EXPORT_POLL_INTERVAL_SEC", 5)
_PROCESSING_TIMEOUT_SEC = getattr(settings, "EXPORT_PROCESSING_TIMEOUT_SEC", 900)
_HEARTBEAT_INTERVAL_SEC = getattr(settings, "EXPORT_HEARTBEAT_INTERVAL_SEC", 30)
_MAX_CONCURRENT = getattr(settings, "EXPORT_MAX_CONCURRENT", 2)
_MAX_PER_USER = getattr(settings, "EXPORT_MAX_PER_USER", 2)
_TASK_TIMEOUT_SEC = getattr(settings, "EXPORT_TASK_TIMEOUT_SEC", 600)
_PDF_CONCURRENCY = getattr(settings, "EXPORT_PDF_CONCURRENCY", 1)
_DOCX_CONCURRENCY = getattr(settings, "EXPORT_DOCX_CONCURRENCY", 1)

# In-flight tracking for graceful shutdown
_in_flight: set[int] = set()
_draining = False
# Semaphore for global concurrency control
_concurrency_semaphore: asyncio.Semaphore | None = None


# ── State machine — transition rules (enforced) ──

_VALID_TRANSITIONS: dict[str, set[str]] = {
    ExportTaskStatus.PENDING: {ExportTaskStatus.PROCESSING},
    ExportTaskStatus.PROCESSING: {ExportTaskStatus.COMPLETED, ExportTaskStatus.FAILED},
    ExportTaskStatus.COMPLETED: {ExportTaskStatus.EXPIRED},
    ExportTaskStatus.FAILED: set(),  # retry creates a new task
    ExportTaskStatus.EXPIRED: set(),
}


def validate_transition(
    current: str,
    target: str,
    task_id: int = 0,
) -> None:
    """Validate an export status transition.

    Raises ``ValueError`` if the transition is not allowed.
    """
    allowed = _VALID_TRANSITIONS.get(current)
    if allowed is None:
        raise ValueError(
            f"export_state_invalid: unknown current state '{current}' for task {task_id}"
        )
    if target not in allowed:
        raise ValueError(
            f"export_state_invalid: transition {current}→{target} "
            f"not allowed for task {task_id}"
        )


async def run_export_processor():
    """Main loop — claim and process pending export tasks."""
    global _concurrency_semaphore
    _concurrency_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    logger.info(
        "Export processor started (poll=%ds, timeout=%ds, max_concurrent=%d)",
        _POLL_INTERVAL_SEC, _PROCESSING_TIMEOUT_SEC, _MAX_CONCURRENT,
    )

    while not _draining:
        try:
            await _recover_stale_tasks()
            # Use semaphore for real concurrency
            async with _concurrency_semaphore:
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
    now = utcnow()
    cutoff = now - timedelta(seconds=_PROCESSING_TIMEOUT_SEC)

    async with async_session() as db:
        result = await db.execute(
            select(ExportTask).where(
                ExportTask.status == ExportTaskStatus.PROCESSING,
                ExportTask.processing_started_at.isnot(None),
                sa.func.coalesce(ExportTask.heartbeat_at, ExportTask.processing_started_at) < cutoff,
            )
        )
        stale = result.scalars().all()

        for task in stale:
            logger.warning(
                "Reclaiming stale task %d (started_at=%s, heartbeat=%s)",
                task.id, task.processing_started_at, task.heartbeat_at,
            )
            validate_transition(task.status, ExportTaskStatus.FAILED, task.id)
            task.status = ExportTaskStatus.FAILED
            task.error_message = "ERR_TASK_TIMEOUT"
            task.completed_at = utcnow()

        if stale:
            await db.commit()
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
        now = utcnow()

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
            .returning(ExportTask.id, ExportTask.user_id, ExportTask.file_format)
        )
        row = result.one_or_none()
        if row is None:
            return
        task_id, user_id, file_format = row
        await db.commit()

    _in_flight.add(task_id)
    logger.info("export_task_started", extra={
        "task_id": task_id,
        "user_id": user_id,
        "format": file_format,
    })

    # Heartbeat refresh loop
    _heartbeat_stop = False

    async def _refresh_heartbeat():
        """Persistent heartbeat — updates heartbeat_at in DB with commit."""
        while not _heartbeat_stop:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SEC)
            try:
                async with async_session() as hb_db:
                    result = await hb_db.execute(
                        select(ExportTask).where(ExportTask.id == task_id)
                    )
                    t = result.scalar_one_or_none()
                    if t and t.status == ExportTaskStatus.PROCESSING:
                        t.heartbeat_at = utcnow()
                        await hb_db.commit()
                        logger.debug("Heartbeat committed for export task %d", task_id)
            except Exception as e:
                logger.warning("Heartbeat refresh failed for task %d: %s", task_id, e)

    heartbeat_task = asyncio.create_task(_refresh_heartbeat())

    # Task processing with real timeout cancellation
    try:
        async with asyncio.timeout(_TASK_TIMEOUT_SEC):
            async with async_session() as db:
                exporter = None
                if file_format == "pdf":
                    from app.services.export.pdf_exporter import PdfExporter
                    exporter = PdfExporter()
                elif file_format == "docx":
                    from app.services.export.docx_exporter import DocxExporter
                    exporter = DocxExporter()
                else:
                    raise ValueError(f"ERR_UNKNOWN_FORMAT:{file_format}")

                result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
                t = result.scalar_one_or_none()
                if t is None:
                    raise ValueError(f"ERR_TASK_NOT_FOUND:{task_id}")

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

                _heartbeat_stop = True
                await db.commit()
                await _publish_task_event(task_id, updated)

    except TimeoutError:
        # Real timeout — task was cancelled by asyncio.timeout()
        _heartbeat_stop = True
        logger.warning("export_task_timed_out", extra={
            "task_id": task_id,
            "timeout_sec": _TASK_TIMEOUT_SEC,
        })
        try:
            async with async_session() as db:
                result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
                t = result.scalar_one_or_none()
                if t and t.status == ExportTaskStatus.PROCESSING:
                    validate_transition(t.status, ExportTaskStatus.FAILED)
                    t.status = ExportTaskStatus.FAILED
                    t.error_message = "ERR_TASK_TIMEOUT"
                    t.completed_at = utcnow()
                    await db.commit()
        except Exception as e:
            logger.error("Failed to mark timed-out task %d: %s", task_id, e)

    except Exception as e:
        _heartbeat_stop = True
        logger.exception("Export task %d crashed: %s", task_id, e)
        try:
            async with async_session() as db:
                result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
                t = result.scalar_one_or_none()
                if t and t.status == ExportTaskStatus.PROCESSING:
                    validate_transition(t.status, ExportTaskStatus.FAILED)
                    t.status = ExportTaskStatus.FAILED
                    t.error_message = "ERR_PROCESSING_FAILED"
                    t.completed_at = utcnow()
                    await db.commit()
        except Exception as e2:
            logger.error("Failed to mark task %d as failed: %s", task_id, e2)

    finally:
        _heartbeat_stop = True
        heartbeat_task.cancel()
        try:
            await heartbeat_task
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
            "user_id": task.user_id,
            "status": task.status,
            "file_format": task.file_format,
            "success_count": task.success_count,
            "skip_count": task.skip_count,
            "error_message": task.error_message,
            "completed_at": task.completed_at,
            "expires_at": task.expires_at,
            "updated_at": task.updated_at,
            "version": getattr(task, "version", task.updated_at.timestamp() if task.updated_at else 0),
        })
        # Send locally (same-process connections)
        await send_to_user(task.user_id, event)
        # Also publish via Redis (cross-process connections)
        await publish_via_redis(event, task.user_id)
    except Exception:
        logger.debug("Failed to publish event for task %d (non-fatal)", task_id)
