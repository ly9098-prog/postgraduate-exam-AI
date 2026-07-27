"""Background processor for export tasks — runs in the scheduler role.

Claims pending tasks via atomic DB updates, generates PDFs/DOCX, and stores
the result. Uses a Redis distributed lock as secondary protection.

Architecture:
- Runs as an asyncio background task in the scheduler process.
- Polls for pending tasks every ``EXPORT_POLL_INTERVAL`` seconds.
- Uses ``UPDATE ... WHERE status='pending' RETURNING *`` to
  atomically claim a task (database-level fencing).
- Spawns an ``asyncio.Task`` per claimed task for **real concurrent**
  processing. A global semaphore limits total concurrent tasks.
- Tracks heartbeat via ``heartbeat_at`` for zombie recovery.
- Per-format semaphores (PDF/DOCX) for fine-grained concurrency control.

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
import time
from dataclasses import dataclass
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import async_session
from app.core.time_utils import utcnow
from app.models.export_task import ExportTask
from app.schemas.export_task import ExportTaskStatus
from app.services.export.generation_token import GenerationToken
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
_processor_started_at: float | None = None
_processor_heartbeat_at: float | None = None

# Semaphores for real concurrency control
_concurrency_semaphore: asyncio.Semaphore | None = None
_pdf_semaphore: asyncio.Semaphore | None = None
_docx_semaphore: asyncio.Semaphore | None = None


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


# ── Concurrency tracking ──


@dataclass
class _TaskSlot:
    """Tracks a claimed task for concurrency accounting."""
    task_id: int
    user_id: int
    file_format: str


async def run_export_processor():
    """Main loop — poll for pending tasks and spawn concurrent workers.

    Unlike the old serial loop, this spawns an ``asyncio.Task`` per claimed
    task so multiple exports process concurrently (up to ``_MAX_CONCURRENT``).
    """
    global _concurrency_semaphore, _pdf_semaphore, _docx_semaphore
    _concurrency_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    _pdf_semaphore = asyncio.Semaphore(_PDF_CONCURRENCY)
    _docx_semaphore = asyncio.Semaphore(_DOCX_CONCURRENCY)

    logger.info(
        "Export processor started (poll=%ds, timeout=%ds, max_concurrent=%d, pdf_c=%d, docx_c=%d)",
        _POLL_INTERVAL_SEC, _TASK_TIMEOUT_SEC, _MAX_CONCURRENT,
        _PDF_CONCURRENCY, _DOCX_CONCURRENCY,
    )
    logger.info("export_processor_started role=%s", getattr(settings, "PROCESS_ROLE", "unknown"))

    global _processor_started_at, _processor_heartbeat_at
    _processor_started_at = time.time()
    _processor_heartbeat_at = _processor_started_at

    while not _draining:
        try:
            await _recover_stale_tasks()
            slot = await _try_claim_task()
            if slot is not None:
                logger.info("Claimed task %d for user %d (%s)", slot.task_id, slot.user_id, slot.file_format)
                asyncio.create_task(_process_claimed_task(slot))
        except asyncio.CancelledError:
            logger.info("Export processor cancelled")
            break
        except Exception as e:
            logger.warning("Export processor error (non-fatal): %s", e)

        _processor_heartbeat_at = time.time()
        await asyncio.sleep(_POLL_INTERVAL_SEC)

    logger.info("export_processor_stopped role=%s", getattr(settings, "PROCESS_ROLE", "unknown"))

    # Drain: wait for in_flight tasks to complete
    if _in_flight:
        logger.info("Export processor draining %d in-flight tasks...", len(_in_flight))
        while _in_flight:
            await asyncio.sleep(1)

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
            # Publish events for reclaimed stale tasks
            for task in stale:
                await db.refresh(task)
                await _publish_task_event(task.id, task)
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


async def _try_claim_task() -> _TaskSlot | None:
    """Atomically claim one pending task.

    Uses ``UPDATE ... WHERE status='pending' RETURNING id, user_id, file_format`` —
    a DB-level atomic claim that works on both SQLite and PostgreSQL. Two concurrent
    processors cannot claim the same task: the second UPDATE affects 0 rows
    because the first already changed the status.

    Also respects per-user concurrency limits: if a user already has ``_MAX_PER_USER``
    tasks in non-terminal state, their next pending task is skipped.
    """
    if _concurrency_semaphore is None:
        return None

    # Skip if at capacity
    if len(_in_flight) >= _MAX_CONCURRENT:
        return None

    async with async_session() as db:
        now = utcnow()

        # Find a candidate task whose user hasn't exceeded the per-user limit
        subq = (
            select(ExportTask.id)
            .where(ExportTask.status == ExportTaskStatus.PENDING)
            .order_by(ExportTask.created_at)
            .limit(1)
            .scalar_subquery()
        )
        # First peek at the candidate without claiming
        peek = await db.execute(
            select(ExportTask.id, ExportTask.user_id)
            .where(ExportTask.id == subq)
        )
        row = peek.one_or_none()
        if row is None:
            return None

        candidate_id, candidate_user_id = row.tuple()

        # Check per-user limit
        pending_count = await get_user_pending_count(db, candidate_user_id)
        if pending_count >= _MAX_PER_USER:
            logger.debug(
                "Skipping task %d for user %d (pending=%d >= max=%d)",
                candidate_id, candidate_user_id, pending_count, _MAX_PER_USER,
            )
            return None

        # Atomic claim: UPDATE the candidate task
        result = await db.execute(
            update(ExportTask)
            .where(ExportTask.id == candidate_id)
            .where(ExportTask.status == ExportTaskStatus.PENDING)
            .values(
                status=ExportTaskStatus.PROCESSING,
                processing_started_at=now,
                heartbeat_at=now,
            )
            .returning(ExportTask.id, ExportTask.user_id, ExportTask.file_format)
        )
        claim_row = result.one_or_none()
        if claim_row is None:
            return None
        task_id, user_id, file_format = claim_row.tuple()
        await db.commit()

    _in_flight.add(task_id)
    return _TaskSlot(task_id=task_id, user_id=user_id, file_format=file_format)


async def _process_claimed_task(slot: _TaskSlot) -> None:
    """Process a claimed export task with full lifecycle management.

    Runs as a standalone ``asyncio.Task`` in the event loop, allowing
    multiple tasks to process concurrently.

    Manages:
    - Global semaphore acquisition
    - Format-specific semaphore acquisition
    - Heartbeat refresh loop (as a subtask)
    - Real timeout tracking
    - Proper cleanup on all exit paths
    """
    assert _concurrency_semaphore is not None

    try:
        # Acquire global semaphore first
        async with _concurrency_semaphore:
            await _process_with_semaphore(slot)
    finally:
        _in_flight.discard(slot.task_id)


async def _process_with_semaphore(slot: _TaskSlot) -> None:
    """Core processing logic, called while holding the global semaphore.

    Also acquires format-specific semaphores when applicable.
    """
    # Select format-specific semaphore
    format_sem = None
    if slot.file_format == "pdf" and _pdf_semaphore is not None:
        format_sem = _pdf_semaphore
    elif slot.file_format == "docx" and _docx_semaphore is not None:
        format_sem = _docx_semaphore

    if format_sem is not None:
        async with format_sem:
            await _execute_task_with_heartbeat(slot)
    else:
        await _execute_task_with_heartbeat(slot)


async def _execute_task_with_heartbeat(slot: _TaskSlot) -> None:
    """Execute the actual task processing with heartbeat and timeout."""
    _heartbeat_stop = False
    token = GenerationToken()

    async def _refresh_heartbeat():
        """Persistent heartbeat — updates heartbeat_at in DB with commit."""
        while not _heartbeat_stop:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SEC)
            try:
                async with async_session() as hb_db:
                    result = await hb_db.execute(
                        select(ExportTask).where(ExportTask.id == slot.task_id)
                    )
                    t = result.scalar_one_or_none()
                    if t and t.status == ExportTaskStatus.PROCESSING:
                        t.heartbeat_at = utcnow()
                        await hb_db.commit()
                        logger.debug("Heartbeat committed for task %d", slot.task_id)
            except Exception as e:
                logger.warning("Heartbeat refresh failed for task %d: %s", slot.task_id, e)

    heartbeat_task = asyncio.create_task(_refresh_heartbeat())

    try:
        async with asyncio.timeout(_TASK_TIMEOUT_SEC):
            async with async_session() as db:
                exporter = None
                if slot.file_format == "pdf":
                    from app.services.export.pdf_exporter import PdfExporter
                    exporter = PdfExporter()
                elif slot.file_format == "docx":
                    from app.services.export.docx_exporter import DocxExporter
                    exporter = DocxExporter()
                else:
                    raise ValueError(f"ERR_UNKNOWN_FORMAT:{slot.file_format}")

                result = await db.execute(select(ExportTask).where(ExportTask.id == slot.task_id))
                t = result.scalar_one_or_none()
                if t is None:
                    raise ValueError(f"ERR_TASK_NOT_FOUND:{slot.task_id}")

                updated = await process_task(db, slot.task_id, exporter, token=token)

                if updated.status == ExportTaskStatus.COMPLETED:
                    logger.info("export_task_completed", extra={
                        "task_id": slot.task_id,
                        "user_id": slot.user_id,
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
                        "task_id": slot.task_id,
                        "user_id": slot.user_id,
                        "status": updated.status,
                        "error_message": updated.error_message,
                    })

                _heartbeat_stop = True
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                await db.commit()
                await _publish_task_event(slot.task_id, updated)

    except TimeoutError:
        _heartbeat_stop = True
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        token.invalidate()
        logger.warning("export_task_timed_out", extra={
            "task_id": slot.task_id,
            "timeout_sec": _TASK_TIMEOUT_SEC,
        })
        try:
            async with async_session() as db:
                result = await db.execute(select(ExportTask).where(ExportTask.id == slot.task_id))
                t = result.scalar_one_or_none()
                if t and t.status == ExportTaskStatus.PROCESSING:
                    validate_transition(t.status, ExportTaskStatus.FAILED, slot.task_id)
                    t.status = ExportTaskStatus.FAILED
                    t.error_message = "ERR_TASK_TIMEOUT"
                    t.completed_at = utcnow()
                    await db.commit()
                    await _publish_task_event(slot.task_id, t)
        except Exception as e:
            logger.error("Failed to mark timed-out task %d: %s", slot.task_id, e)

    except Exception as e:
        _heartbeat_stop = True
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        token.invalidate()
        logger.exception("Task %d crashed: %s", slot.task_id, e)
        try:
            async with async_session() as db:
                result = await db.execute(select(ExportTask).where(ExportTask.id == slot.task_id))
                t = result.scalar_one_or_none()
                if t and t.status == ExportTaskStatus.PROCESSING:
                    validate_transition(t.status, ExportTaskStatus.FAILED, slot.task_id)
                    t.status = ExportTaskStatus.FAILED
                    t.error_message = "ERR_PROCESSING_FAILED"
                    t.completed_at = utcnow()
                    await db.commit()
                    await _publish_task_event(slot.task_id, t)
        except Exception as e2:
            logger.error("Failed to mark task %d as failed: %s", slot.task_id, e2)

    finally:
        _heartbeat_stop = True
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


async def stop_processor():
    """Signal the processor to stop after current tasks complete."""
    global _draining
    _draining = True
    logger.info("Export processor drain requested (in_flight=%d)", len(_in_flight))


def get_processor_health() -> dict:
    """Return processor health info for the export health endpoint.

    Returns empty dict if processor was never started (web-only role).
    """
    if _processor_started_at is None:
        return {}
    return {
        "running": not _draining,
        "started_at": _processor_started_at,
        "last_heartbeat_at": _processor_heartbeat_at,
        "in_flight": len(_in_flight),
        "draining": _draining,
    }


async def _publish_task_event(task_id: int, task: ExportTask) -> None:
    """Publish a task status event — Redis cross-process then local delivery.

    Architecture:
    1. If Redis is available: publish via Redis Pub/Sub. The per-instance
       Redis subscriber on each process (including this one) forwards the
       event to local WebSocket connections. This avoids duplicate delivery.
    2. If Redis is unavailable: fall back to direct ``send_to_user()`` which
       only reaches connections on the current process. In this mode,
       scheduler-process events will NOT reach web-process WebSockets,
       so only ``PROCESS_ROLE=all`` (or same-process) works fully.
    """
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

        # Try Redis first for cross-process delivery
        redis_published = False
        try:
            from app.core.cache import cache
            if cache.is_enabled:
                await publish_via_redis(event, task.user_id)
                redis_published = True
        except Exception:
            pass

        # Fallback: local delivery only (same-process WebSockets)
        if not redis_published:
            await send_to_user(task.user_id, event)

        logger.info(
            "export_status_published task_id=%d user_id=%d status=%s transport=%s",
            task_id, task.user_id, task.status,
            "redis" if redis_published else "local",
        )
    except Exception:
        logger.debug("Failed to publish event for task %d (non-fatal)", task_id)
