"""Retry and same-record export regeneration."""

from __future__ import annotations


async def retry_export(task_id, db, current_user, *, ports):
    """Retry a failed export task — creates a new task from the original config."""
    task = await ports("_get_user_task")(db, task_id, current_user.id, for_update=True)
    if task.status != ports("ExportTaskStatus").FAILED:
        ports("raise_export_error")(
            400, ports("ExportErrorCode").ACCESS_DENIED, "只有失败的任务可以重试"
        )
    if task.file_format == "docx":
        ports("ensure_format_allowed")("docx")
    config = ports("_task_to_config")(task)
    range_type = ports("ExportRangeType")(config["range_type"])
    count = await ports("_preview_count")(
        db,
        current_user.id,
        range_type,
        config.get("filters"),
        config.get("selected_ids"),
    )
    ports("validate_export_range")(
        config["range_type"], config.get("selected_ids"), count
    )
    from app.services.export.processor import _MAX_PER_USER, get_user_pending_count

    pending_count = await get_user_pending_count(db, current_user.id)
    if pending_count >= _MAX_PER_USER:
        ports("raise_export_error")(
            429,
            ports("ExportErrorCode").TOO_MANY_CONCURRENT,
            f"同时最多只能有 {_MAX_PER_USER} 个未完成的任务，请等待当前任务完成",
        )
    return await create_retry_task(db, current_user, task, count, ports=ports)


async def re_export(task_id, db, current_user, *, ports):
    """Regenerate an earlier export in place.

    The existing database row and stable storage key are reused. During
    generation the previous complete file remains readable; after generation,
    LocalFileStorage atomically replaces it. No new export-task directory is
    created and the records page continues to show a single card.
    """
    task = await ports("_get_user_task")(db, task_id, current_user.id, for_update=True)
    if task.file_format == "docx":
        ports("ensure_format_allowed")("docx")
    if task.status in (
        ports("ExportTaskStatus").PENDING,
        ports("ExportTaskStatus").PROCESSING,
    ):
        ports("raise_export_error")(
            400, ports("ExportErrorCode").ACCESS_DENIED, "该文件正在导出，请稍候"
        )
    from app.services.export.processor import _MAX_PER_USER, get_user_pending_count

    pending_count = await get_user_pending_count(db, current_user.id)
    if pending_count >= _MAX_PER_USER:
        ports("raise_export_error")(
            429,
            ports("ExportErrorCode").TOO_MANY_CONCURRENT,
            f"同时最多只能有 {_MAX_PER_USER} 个未完成的任务，请等待当前任务完成",
        )
    reusable_snapshot_id = await validate_reexport_snapshot(
        db, current_user, task, ports=ports
    )
    reset_reexport_state(task, ports=ports)
    await db.commit()
    await db.refresh(task)
    ports("_wake_local_export_processor")()
    ports("logger").info(
        "export_task_reexported_in_place",
        extra={
            "task_id": task.id,
            "user_id": current_user.id,
            "snapshot_reused": reusable_snapshot_id is not None,
            "kept_previous_file": ports("bool")(task.file_key),
        },
    )
    return ports("_task_to_response")(task)


async def create_retry_task(db, current_user, task, count, *, ports):
    # Re-read after the capacity check; awaited work may have changed the task.
    config = ports("_task_to_config")(task)
    new_task = await ports("_create_export_task")(db, current_user.id, config)
    new_task.source_task_id = task.id
    new_task.retry_count = (task.retry_count or 0) + 1
    new_task.total_count = count
    await db.commit()
    await db.refresh(new_task)
    ports("_wake_local_export_processor")()
    ports("logger").info(
        "export_task_retried",
        extra={
            "task_id": new_task.id,
            "source_task_id": task.id,
            "user_id": current_user.id,
        },
    )
    return ports("_task_to_response")(new_task)


async def validate_reexport_snapshot(db, current_user, task, *, ports):
    config = ports("_task_to_config")(task)
    reusable_snapshot_id: str | None = None
    if task.snapshot_id:
        snapshot_data = await ports("load_snapshot")(
            db, task.snapshot_id, current_user.id
        )
        if snapshot_data is not None:
            reusable_snapshot_id = task.snapshot_id
        else:
            ports("logger").warning(
                "Re-export source snapshot missing: task=%d snapshot=%s; rebuilding from config",
                task.id,
                task.snapshot_id,
            )
    if reusable_snapshot_id is None:
        range_type = ports("ExportRangeType")(config["range_type"])
        count = await ports("_preview_count")(
            db,
            current_user.id,
            range_type,
            config.get("filters"),
            config.get("selected_ids"),
        )
        ports("validate_export_range")(
            config["range_type"], config.get("selected_ids"), count
        )
        task.snapshot_id = None
    return reusable_snapshot_id


def reset_reexport_state(task, *, ports):
    now = ports("utcnow")()
    has_valid_previous_file = ports("bool")(
        task.file_key
        and task.completed_at
        and (task.expires_at is None or task.expires_at > now)
    )
    if not has_valid_previous_file:
        task.file_key = None
        task.file_size = None
        task.completed_at = None
        task.expires_at = None
    task.status = ports("ExportTaskStatus").PENDING
    task.error_message = None
    task.error_code = (
        ports("REEXPORTING_ERROR_CODE") if has_valid_previous_file else None
    )
    task.processing_started_at = None
    task.started_at = None
    task.heartbeat_at = None
    task.retry_count = (task.retry_count or 0) + 1
    task.version = (task.version or 0) + 1
    task.idempotency_key = None
    task.generator_version = ports("settings").GENERATOR_VERSION
