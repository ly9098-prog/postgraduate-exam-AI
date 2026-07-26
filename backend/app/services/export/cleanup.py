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
from app.services.storage_backend import get_storage

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

    storage = get_storage()

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


async def cleanup_orphan_files(
    db: AsyncSession,
    batch_size: int = 50,
) -> dict:
    """Find completed tasks without existing files and log them.

    This detects storage inconsistency (DB says completed, file missing).
    Returns counts for monitoring.
    """
    result = await db.execute(
        select(ExportTask)
        .where(
            ExportTask.status == ExportTaskStatus.COMPLETED,
            ExportTask.file_key.isnot(None),
        )
        .limit(batch_size)
    )
    tasks = result.scalars().all()
    storage = get_storage()
    missing = 0

    for task in tasks:
        if task.file_key:
            # We can only check local files
            import os
            if not task.file_key.startswith("http"):
                from app.core.config import settings
                from app.services.storage_backend import LocalFileStorage
                filepath = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    task.file_key,
                )
                if not os.path.exists(filepath.replace("static/exports", "static/exports")):
                    logger.error(
                        "Orphan task %d: completed but file missing at %s",
                        task.id, task.file_key,
                    )
                    missing += 1

    return {"orphan_tasks_checked": len(tasks), "missing_files": missing}
