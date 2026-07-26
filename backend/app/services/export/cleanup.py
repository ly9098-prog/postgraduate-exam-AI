"""Periodic cleanup of expired export tasks — files, snapshots, and DB records.

Runs in the scheduler role alongside existing cleanup tasks.
Idempotent: multiple runs do not cause errors.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.export_task import ExportSnapshot, ExportTask
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
    1. Delete the stored PDF file.
    2. Delete the snapshot.
    3. Update task status to ``expired``.

    Returns a dict with counts of processed items.
    """
    now = datetime.now(timezone.utc)
    stats = {"tasks_expired": 0, "files_deleted": 0, "snapshots_deleted": 0}

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
        # Delete stored file
        if task.file_key:
            try:
                await storage.delete(task.file_key)
                stats["files_deleted"] += 1
            except Exception as e:
                logger.warning("Failed to delete file for task %d: %s", task.id, e)

        # Delete snapshot
        if task.snapshot_id:
            try:
                await delete_snapshot(db, task.snapshot_id)
                stats["snapshots_deleted"] += 1
            except Exception as e:
                logger.warning("Failed to delete snapshot for task %d: %s", task.id, e)

        # Update task status
        task.status = ExportTaskStatus.EXPIRED
        stats["tasks_expired"] += 1

    if stats["tasks_expired"] > 0:
        await db.flush()
        logger.info("Cleanup: %s", stats)

    return stats
