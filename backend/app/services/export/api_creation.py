"""Export creation, capacity locking and integrity-conflict recovery."""

from __future__ import annotations


async def create_export(req, db, current_user, *, ports):
    """Create a new export task. The PDF is generated asynchronously.

    Idempotency: repeated submissions with the same config within
    ``_IDEMPOTENCY_WINDOW_SEC`` return the existing pending/processing task.
    Re-export and retry create new tasks (call those endpoints instead).
    """
    if req.file_format == "docx":
        ports("ensure_format_allowed")("docx")
    range_type = ports("ExportRangeType")(req.range_type)
    count = await ports("_preview_count")(
        db, current_user.id, range_type, req.filters, req.selected_ids
    )
    ports("validate_export_range")(req.range_type, req.selected_ids, count)
    idempotency_key = ports("_build_idempotency_key")(current_user.id, req)
    if idempotency_key:
        existing = await ports("_find_existing_task")(
            db, current_user.id, idempotency_key
        )
        if existing is not None:
            ports("_wake_local_export_processor")()
            return ports("_task_to_response")(existing)
    await check_creation_capacity(db, current_user, ports=ports)
    # Rollback expires ORM state; conflict recovery must use this captured ID.
    _user_id = current_user.id
    return await create_and_commit_task(
        db, current_user, req, count, idempotency_key, _user_id, ports=ports
    )


async def check_creation_capacity(db, current_user, *, ports):
    from app.services.export.processor import _MAX_PER_USER, get_user_pending_count

    await db.execute(
        ports("select")(ports("ExportTask").id)
        .where(
            ports("ExportTask").user_id == current_user.id,
            ports("ExportTask").status.in_(
                [
                    ports("ExportTaskStatus").PENDING,
                    ports("ExportTaskStatus").PROCESSING,
                ]
            ),
        )
        .limit(_MAX_PER_USER)
        .with_for_update()
    )
    pending_count = await get_user_pending_count(db, current_user.id)
    if pending_count >= _MAX_PER_USER:
        ports("raise_export_error")(
            429,
            ports("ExportErrorCode").TOO_MANY_CONCURRENT,
            f"同时最多只能有 {_MAX_PER_USER} 个未完成的任务，请等待当前任务完成",
        )


async def create_and_commit_task(
    db, current_user, req, count, idempotency_key, _user_id, *, ports
):
    from sqlalchemy.exc import IntegrityError

    try:
        task = await ports("_create_export_task")(
            db, _user_id, {**req.model_dump(), "_idempotency_key": idempotency_key}
        )
        task.total_count = count
    except IntegrityError:
        await db.rollback()
        if idempotency_key:
            existing = await ports("_find_existing_task")(db, _user_id, idempotency_key)
            if existing is not None:
                return ports("_task_to_response")(existing)
        from app.services.export.service import find_task_by_idempotency_key

        existing = await find_task_by_idempotency_key(db, _user_id, idempotency_key)
        if existing is not None:
            return ports("_task_to_response")(existing)
        ports("raise_export_error")(
            409,
            ports("ExportErrorCode").TASK_ALREADY_EXISTS,
            "相同配置的导出任务已存在",
        )
    await db.commit()
    await db.refresh(task)
    ports("_wake_local_export_processor")()
    ports("logger").info(
        "export_task_created",
        extra={
            "task_id": task.id,
            "user_id": current_user.id,
            "format": task.file_format,
            "range_type": task.range_type,
            "question_count": task.total_count,
        },
    )
    return ports("_task_to_response")(task)
