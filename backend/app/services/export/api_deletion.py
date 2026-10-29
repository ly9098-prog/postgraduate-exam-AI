"""Export snapshot, external-file and record deletion ordering."""

from __future__ import annotations


async def delete_export(task_id, db, current_user, *, ports):
    """Delete an export task, its file, and its snapshot."""
    task = await ports("_get_user_task")(db, task_id, current_user.id, for_update=True)
    if task.status in (
        ports("ExportTaskStatus").PENDING,
        ports("ExportTaskStatus").PROCESSING,
    ):
        ports("raise_export_error")(
            400, ports("ExportErrorCode").ACCESS_DENIED, "导出任务仍在处理中，不能删除"
        )
    # Stage database cleanup first so a failed file removal can roll it back.
    await stage_snapshot_deletion(db, task, ports=ports)
    await delete_stored_file(db, task, ports=ports)
    await db.delete(task)
    await db.commit()
    ports("logger").info(
        "export_task_deleted",
        extra={
            "task_id": task_id,
            "user_id": current_user.id,
            "format": task.file_format,
        },
    )
    return {"success": True}


async def stage_snapshot_deletion(db, task, *, ports):
    if task.snapshot_id:
        try:
            other_refs = await db.execute(
                ports("select")(ports("ExportTask").id)
                .where(
                    ports("ExportTask").snapshot_id == task.snapshot_id,
                    ports("ExportTask").id != task.id,
                    ports("ExportTask").status != ports("ExportTaskStatus").EXPIRED,
                )
                .limit(1)
            )
            if other_refs.scalar_one_or_none() is None:
                await ports("delete_snapshot")(db, task.snapshot_id)
            else:
                ports("logger").debug(
                    "Snapshot %s still referenced by other tasks — skipping delete",
                    task.snapshot_id,
                )
        except ports("Exception") as exc:
            await db.rollback()
            ports("logger").warning(
                "Snapshot delete check failed for task %d: %s", task.id, exc
            )
            ports("raise_export_error")(
                503,
                ports("ExportErrorCode").SERVICE_UNAVAILABLE,
                "导出记录清理失败，请稍后重试",
            )


async def delete_stored_file(db, task, *, ports):
    if task.file_key:
        try:
            storage = ports("get_export_storage")()
            deleted = await storage.delete(task.file_key)
        except ports("Exception") as exc:
            await db.rollback()
            ports("logger").warning(
                "File delete failed for task %d: %s — DB record retained", task.id, exc
            )
            ports("raise_export_error")(
                503,
                ports("ExportErrorCode").STORAGE_FAILED,
                "导出文件删除失败，请稍后重试",
            )
        if not deleted:
            await db.rollback()
            ports("logger").warning(
                "File delete returned false for task %d, key %s — DB record retained",
                task.id,
                task.file_key,
            )
            ports("raise_export_error")(
                503,
                ports("ExportErrorCode").STORAGE_FAILED,
                "导出文件删除失败，请稍后重试",
            )
