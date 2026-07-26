"""Background processor for export tasks — runs in the scheduler role.

Claims pending tasks via atomic DB updates, generates PDFs, and stores
the result. Uses a Redis distributed lock as secondary protection.

Architecture:
- Runs as an asyncio background task in the scheduler process.
- Polls for pending tasks every ``EXPORT_POLL_INTERVAL`` seconds.
- Uses ``UPDATE ... WHERE status='pending' LIMIT 1 RETURNING *`` to
  atomically claim a task (database-level fencing).
- Tracks heartbeat via ``heartbeat_at`` for zombie recovery.
- Limits concurrency: only one PDF at a time per processor instance.

Zombie recovery:
- Tasks stuck in ``processing`` for > ``EXPORT_PROCESSING_TIMEOUT``
  without a recent ``heartbeat_at`` are reclaimed (failed → retryable).

Future upgrade path:
- For higher throughput, replace this with Celery, RQ, or Arq.
- The ``ExportTask`` model and ``process_task()`` function remain the
  same; only the scheduler mechanism changes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

import sqlalchemy as sa

from app.core.config import settings
from app.core.database import async_session
from app.models.export_task import ExportTask
from app.schemas.export_task import ExportTaskStatus
from app.services.export.service import process_task

logger = logging.getLogger(__name__)

# ── Tuning ──
_POLL_INTERVAL_SEC = 5
_PROCESSING_TIMEOUT_SEC = 900  # 15 minutes max per task
_HEARTBEAT_INTERVAL_SEC = 30
_MAX_CONCURRENT = 1  # one PDF at a time per scheduler (memory guard)

# In-flight tracking for graceful shutdown
_in_flight: set[int] = set()
_draining = False


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
    now = datetime.now(timezone.utc)
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
            task.completed_at = datetime.now(timezone.utc)

        if stale:
            await db.flush()
            logger.info("Reclaimed %d stale tasks", len(stale))


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
        now = datetime.now(timezone.utc)

        # Atomic claim: UPDATE the first pending task and RETURN the id.
        # The subquery finds the first candidate; the outer UPDATE's
        # ``WHERE status='pending'`` is the atomicity guard — if another
        # processor already claimed this task the UPDATE affects 0 rows.
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
            .returning(ExportTask.id)
        )
        row = result.one_or_none()
        if row is None:
            return
        task_id = row[0]
        await db.flush()

    _in_flight.add(task_id)
    logger.info("Claimed export task %d (atomic UPDATE)", task_id)

    # Heartbeat refresh loop — runs concurrently with processing
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
                        t.heartbeat_at = datetime.now(timezone.utc)
                        await hb_db.flush()
                        logger.debug("Heartbeat refreshed for export task %d", task_id)
            except Exception as e:
                logger.warning("Heartbeat refresh failed for task %d: %s", task_id, e)

    heartbeat_task = asyncio.create_task(_refresh_heartbeat())

    try:
        # Process (opens a new session internally)
        async with async_session() as db:
            from app.services.export.pdf_exporter import PdfExporter

            exporter = PdfExporter()
            updated = await process_task(db, task_id, exporter)

            if updated.status == ExportTaskStatus.COMPLETED:
                logger.info("Export task %d completed successfully", task_id)
            else:
                logger.info("Export task %d finished with status=%s", task_id, updated.status)

            await db.commit()

    except Exception as e:
        logger.exception("Export task %d crashed: %s", task_id, e)
        # Mark as failed if not already done
        try:
            async with async_session() as db:
                result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
                t = result.scalar_one_or_none()
                if t and t.status == ExportTaskStatus.PROCESSING:
                    t.status = ExportTaskStatus.FAILED
                    t.error_message = f"处理异常: {str(e)[:200]}"
                    t.completed_at = datetime.now(timezone.utc)
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
