"""Periodic cleanup of expired export tasks — files, snapshots, and DB records.

Runs in the scheduler role alongside existing cleanup tasks.
Idempotent: multiple runs do not cause errors.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.export_task import ExportTask
from app.schemas.export_task import ExportTaskStatus
from app.services.export.snapshot_service import delete_snapshot
from app.services.storage_backend import get_export_storage

logger = logging.getLogger(__name__)


async def cleanup_expired(
    db: AsyncSession,
    batch_size: int = 50,
) -> dict:
    """Clean up all expired export tasks.

    For each expired task:
    1. Delete the stored PDF file (check return value — False = failure).
    2. Delete the snapshot.
    3. Update task status to ``expired``.

    Returns a dict with counts of processed items.
    """
    now = utcnow()
    stats = {
        "tasks_expired": 0,
        "files_deleted": 0,
        "files_delete_failed": 0,
        "snapshots_deleted": 0,
    }

    result = await db.execute(
        select(ExportTask)
        .where(
            ExportTask.expires_at.isnot(None),
            ExportTask.expires_at < now,
            ExportTask.status.in_([ExportTaskStatus.COMPLETED, ExportTaskStatus.PENDING, ExportTaskStatus.FAILED]),
        )
        .limit(batch_size)
    )
    tasks = result.scalars().all()

    storage = get_export_storage()

    for task in tasks:
        # Delete stored file — check return value
        file_deleted = False
        if task.file_key:
            try:
                was_deleted = await storage.delete(task.file_key)
                if was_deleted:
                    file_deleted = True
                else:
                    logger.warning("Cleanup: file delete returned false for task %d, key %s — will retry", task.id, task.file_key)
            except Exception as e:
                logger.warning("Cleanup: file delete raised for task %d: %s — will retry", task.id, e)
        else:
            file_deleted = True  # no file to delete

        if file_deleted:
            stats["files_deleted"] += 1
            # Delete snapshot — only if no other task references it
            if task.snapshot_id:
                try:
                    other_refs = await db.execute(
                        select(ExportTask.id)
                        .where(
                            ExportTask.snapshot_id == task.snapshot_id,
                            ExportTask.id != task.id,
                        )
                        .limit(1)
                    )
                    if other_refs.scalar_one_or_none() is None:
                        await delete_snapshot(db, task.snapshot_id)
                        stats["snapshots_deleted"] += 1
                except Exception as e:
                    logger.warning("Cleanup: snapshot delete check failed for task %d: %s", task.id, e)
        else:
            stats["files_delete_failed"] += 1

        # When file deletion succeeds (or no file), mark as expired.
        # When file deletion fails, keep the task in its current state
        # so cleanup can retry on the next cycle.
        if file_deleted:
            task.status = ExportTaskStatus.EXPIRED
            stats["tasks_expired"] += 1

    if stats["tasks_expired"] > 0:
        await db.commit()
        # Publish expired events for frontend sync
        for task in tasks:
            if task.status == ExportTaskStatus.EXPIRED:
                try:
                    await db.refresh(task)
                    await _publish_expired_event(task)
                except Exception:
                    logger.debug("Failed to publish expired event for task %d", task.id)
        logger.info("export_cleanup_completed", extra={
            "tasks_expired": stats["tasks_expired"],
            "files_deleted": stats["files_deleted"],
            "files_delete_failed": stats["files_delete_failed"],
            "snapshots_deleted": stats["snapshots_deleted"],
        })

    return stats


async def _publish_expired_event(task: ExportTask) -> None:
    """Publish an expired status event — same pattern as processor._publish_task_event."""
    try:
        from app.services.export.processor import _publish_task_event
        await _publish_task_event(task.id, task)
    except Exception:
        logger.debug("Failed to publish expired event for task %d", task.id)
