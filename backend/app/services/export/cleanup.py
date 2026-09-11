"""Safe periodic cleanup for expired export artifacts and snapshots.

The cleanup task intentionally operates only on terminal export states.  It
never expires ``pending`` or ``processing`` work, and it serializes each task
with user/API mutations using a row lock before touching external storage.

External file deletion happens before the database transition.  If a later DB
operation fails the transaction is rolled back and the next cleanup pass can
retry safely because storage deletion is idempotent.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time_utils import utcnow
from app.models.export_task import ExportTask
from app.schemas.export_task import ExportTaskStatus
from app.services.export.snapshot_service import delete_snapshot
from app.services.storage_backend import (
    COSStorage,
    LocalFileStorage,
    get_export_storage,
    get_export_storage_root,
)

logger = logging.getLogger(__name__)

_TERMINAL_EXPIRABLE = (ExportTaskStatus.COMPLETED, ExportTaskStatus.FAILED)


def inspect_export_cleanup_capability() -> tuple[bool, str | None]:
    """Check whether the configured export storage can be safely cleaned.

    This probe does not delete or create user artifacts.  Local storage must be
    readable/writable/traversable; COS must have an initialisable client.  A
    failed probe disables both scheduled and manual cleanup instead of letting
    a cleanup run partially mutate the database.
    """
    try:
        storage = get_export_storage()
        if isinstance(storage, LocalFileStorage):
            root = get_export_storage_root(create=False)
            if os.path.isdir(root):
                required = os.R_OK | os.W_OK | os.X_OK
                if not os.access(root, required):
                    return False, "导出目录当前进程不可读写"
                return True, None

            # A fresh deployment may not have produced an export yet. Cleanup
            # is still usable if the nearest existing parent can create the
            # configured directory; do not create it from a health probe.
            parent = root
            while parent and not os.path.exists(parent):
                next_parent = os.path.dirname(parent)
                if next_parent == parent:
                    break
                parent = next_parent
            if not parent or not os.path.isdir(parent):
                return False, "导出目录及其父目录当前进程不可见"
            if not os.access(parent, os.W_OK | os.X_OK):
                return False, "导出目录尚未创建，且父目录不可写"
            return True, "导出目录尚未创建；首次导出时会自动创建"

        if isinstance(storage, COSStorage):
            # _get_client only constructs the SDK client.  It does not mutate
            # remote state, and gives us a deterministic configuration check.
            if storage._get_client() is None:  # noqa: SLF001 - storage capability probe
                return False, "COS 导出存储未正确配置，清理任务已安全停用"
            return True, None

        return False, f"未知导出存储后端：{type(storage).__name__}"
    except Exception as exc:
        return False, f"导出存储检查失败：{type(exc).__name__}: {str(exc)[:180]}"


async def cleanup_expired(
    db: AsyncSession,
    batch_size: int = 50,
) -> dict[str, Any]:
    """Expire terminal export tasks whose retention window has elapsed.

    ``completed`` and ``failed`` are the only eligible states.  Failed tasks
    receive ``expires_at`` when they fail, so their snapshots also have a
    bounded lifetime.  Each candidate is re-read under ``FOR UPDATE`` before
    any destructive action to avoid racing re-export/delete operations.
    """
    batch_size = max(1, min(int(batch_size), 500))
    now = utcnow()
    retention_cutoff = now - timedelta(days=max(1, int(settings.EXPORT_RETENTION_DAYS)))
    stats: dict[str, Any] = {
        "candidates": 0,
        "tasks_expired": 0,
        "files_deleted": 0,
        "files_delete_failed": 0,
        "snapshots_deleted": 0,
        "snapshots_delete_failed": 0,
        "db_failures": 0,
        "limit_reached": False,
    }

    # Fetch one extra id so the task center can truthfully say whether more
    # work remains without scanning/counting the entire table.
    result = await db.execute(
        select(ExportTask.id)
        .where(
            ExportTask.status.in_(_TERMINAL_EXPIRABLE),
            or_(
                and_(ExportTask.expires_at.isnot(None), ExportTask.expires_at < now),
                and_(
                    ExportTask.expires_at.is_(None),
                    func.coalesce(
                        ExportTask.completed_at,
                        ExportTask.updated_at,
                        ExportTask.created_at,
                    )
                    < retention_cutoff,
                ),
            ),
        )
        .order_by(
            func.coalesce(
                ExportTask.expires_at,
                ExportTask.completed_at,
                ExportTask.updated_at,
                ExportTask.created_at,
            ).asc(),
            ExportTask.id.asc(),
        )
        .limit(batch_size + 1)
    )
    candidate_ids = list(result.scalars().all())
    stats["limit_reached"] = len(candidate_ids) > batch_size
    candidate_ids = candidate_ids[:batch_size]
    stats["candidates"] = len(candidate_ids)

    storage = get_export_storage()

    for task_id in candidate_ids:
        file_deleted = False
        had_file = False
        snapshot_deleted = False
        snapshot_op_failed = False
        snapshot_id: str | None = None
        try:
            locked = await db.execute(
                select(ExportTask).where(ExportTask.id == task_id).with_for_update()
            )
            task = locked.scalar_one_or_none()
            if task is None:
                await db.rollback()
                continue

            # Re-check after the lock. A user may have re-exported the task
            # after the candidate id query but before we acquired the row.
            terminal_at = task.completed_at or task.updated_at or task.created_at
            expired_by_deadline = task.expires_at is not None and task.expires_at < now
            expired_by_invariant_repair = (
                task.expires_at is None
                and terminal_at is not None
                and terminal_at < retention_cutoff
            )
            if task.status not in _TERMINAL_EXPIRABLE or not (
                expired_by_deadline or expired_by_invariant_repair
            ):
                await db.rollback()
                continue

            # Perform all fallible database-side snapshot checks before the
            # irreversible external file deletion. ``delete_snapshot`` only
            # stages a DB DELETE until the final commit, so a storage failure
            # can still roll the database changes back cleanly.
            snapshot_id = task.snapshot_id
            if snapshot_id:
                refs = await db.execute(
                    select(ExportTask.id)
                    .where(
                        ExportTask.snapshot_id == snapshot_id,
                        ExportTask.id != task.id,
                        ExportTask.status != ExportTaskStatus.EXPIRED,
                    )
                    .limit(1)
                )
                if refs.scalar_one_or_none() is None:
                    try:
                        snapshot_deleted = bool(await delete_snapshot(db, snapshot_id))
                    except Exception:
                        snapshot_op_failed = True
                        stats["snapshots_delete_failed"] += 1
                        raise

            had_file = bool(task.file_key)
            if task.file_key:
                try:
                    file_deleted = bool(await storage.delete(task.file_key))
                except Exception as exc:
                    logger.warning(
                        "export_cleanup_file_delete_raised task=%d error=%s",
                        task.id,
                        exc,
                    )
                    file_deleted = False
                if not file_deleted:
                    stats["files_delete_failed"] += 1
                    await db.rollback()
                    continue
            else:
                file_deleted = True

            # Detach storage metadata so an expired row cannot accidentally be
            # served, and future orphan checks do not see this row as a live
            # snapshot reference.
            task.status = ExportTaskStatus.EXPIRED
            task.file_key = None
            task.file_size = None
            task.snapshot_id = None
            task.processing_started_at = None
            task.heartbeat_at = None
            await db.commit()

            stats["tasks_expired"] += 1
            if had_file and file_deleted:
                stats["files_deleted"] += 1
            if snapshot_deleted:
                stats["snapshots_deleted"] += 1

            try:
                await db.refresh(task)
                await _publish_expired_event(task)
            except Exception:
                logger.debug(
                    "Failed to publish expired event for task %d",
                    task_id,
                    exc_info=True,
                )
        except Exception as exc:
            if not snapshot_op_failed:
                stats["db_failures"] += 1
            try:
                await db.rollback()
            except Exception:
                pass
            logger.warning(
                "export_cleanup_task_failed task=%d snapshot=%s file_deleted=%s error=%s",
                task_id,
                snapshot_id,
                file_deleted,
                exc,
                exc_info=True,
            )

    if stats["candidates"]:
        logger.info(
            "export_cleanup_completed",
            extra={
                "candidates": stats["candidates"],
                "tasks_expired": stats["tasks_expired"],
                "files_deleted": stats["files_deleted"],
                "files_delete_failed": stats["files_delete_failed"],
                "snapshots_deleted": stats["snapshots_deleted"],
                "snapshots_delete_failed": stats["snapshots_delete_failed"],
                "db_failures": stats["db_failures"],
                "limit_reached": stats["limit_reached"],
            },
        )

    return stats


async def _publish_expired_event(task: ExportTask) -> None:
    """Publish an expired status event using the processor's event channel."""
    try:
        from app.services.export.processor import _publish_task_event

        await _publish_task_event(task.id, task)
    except Exception:
        logger.debug("Failed to publish expired event for task %d", task.id)
