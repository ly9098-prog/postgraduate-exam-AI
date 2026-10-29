"""User-scoped export reads, configuration and idempotency queries."""

from __future__ import annotations


async def preview_export_count(req, db, current_user, *, ports):
    """Preview how many questions match the given export range + filters."""
    try:
        count = await ports("_preview_count")(
            db,
            current_user.id,
            ports("ExportRangeType")(req.range_type),
            req.filters,
            req.selected_ids,
        )
        ports("logger").info(
            "export_preview_count",
            extra={
                "user_id": current_user.id,
                "range_type": req.range_type,
                "count": count,
            },
        )
        return ports("PreviewCountResponse")(count=count, range_type=req.range_type)
    except ports("ValueError") as e:
        raise ports("HTTPException")(status_code=400, detail=ports("str")(e))


async def list_exports(page, page_size, db, current_user, *, ports):
    """List the current user's export tasks (newest first)."""
    count_result = await db.execute(
        ports("select")(ports("ExportTask").id).where(
            ports("ExportTask").user_id == current_user.id
        )
    )
    total = ports("len")(count_result.fetchall())
    result = await db.execute(
        ports("select")(ports("ExportTask"))
        .where(ports("ExportTask").user_id == current_user.id)
        .order_by(ports("ExportTask").created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    tasks = result.scalars().all()
    items = [ports("_task_to_response")(t).model_dump() for t in tasks]
    return ports("paginated_response")(
        items=items, total=total, page=page, page_size=page_size
    )


async def get_export(task_id, db, current_user, *, ports):
    """Get a single export task's details."""
    task = await ports("_get_user_task")(db, task_id, current_user.id)
    return ports("_task_to_response")(task)


async def _get_user_task(db, task_id, user_id, *, for_update=False, ports):
    """Get a task and verify ownership, optionally serialising mutations."""
    stmt = ports("select")(ports("ExportTask")).where(
        ports("ExportTask").id == task_id, ports("ExportTask").user_id == user_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        ports("raise_export_error")(
            404, ports("ExportErrorCode").TASK_NOT_FOUND, "导出任务不存在"
        )
    return task


def _task_to_config(task, *, ports):
    return {
        "range_type": task.range_type,
        "filters": task.filters,
        "selected_ids": task.selected_ids,
        "title": task.title,
        "show_date": task.show_date,
        "export_date": task.export_date,
        "sort_by": task.sort_by,
        "group_by": task.group_by,
        "answer_position": task.answer_position,
        "analysis_position": task.analysis_position,
        "space_style": task.space_style,
        "file_format": task.file_format,
    }


def _build_idempotency_key(user_id, req, *, ports):
    """Build a stable idempotency key from the request — generated BEFORE snapshot."""
    import hashlib
    import json

    raw = {
        "user_id": user_id,
        "range_type": req.range_type,
        "filters": ports("_sort_dict")(req.filters) if req.filters else None,
        "selected_ids": ports("sorted")(req.selected_ids) if req.selected_ids else None,
        "title": req.title.strip(),
        "show_date": req.show_date,
        "export_date": req.export_date.strip(),
        "sort_by": req.sort_by,
        "group_by": req.group_by,
        "answer_position": req.answer_position,
        "analysis_position": req.analysis_position,
        "space_style": req.space_style,
        "file_format": req.file_format,
    }
    digest = hashlib.sha256(
        json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return f"export_{digest[:32]}"


async def _find_existing_task(db, user_id, idempotency_key, *, ports):
    """Find an existing task with the same idempotency key in non-terminal state."""
    from datetime import timedelta

    cutoff = ports("utcnow")() - timedelta(seconds=ports("_IDEMPOTENCY_WINDOW_SEC"))
    result = await db.execute(
        ports("select")(ports("ExportTask"))
        .where(
            ports("ExportTask").user_id == user_id,
            ports("ExportTask").idempotency_key == idempotency_key,
            ports("ExportTask").created_at >= cutoff,
            ports("ExportTask").status.in_(
                [
                    ports("ExportTaskStatus").PENDING,
                    ports("ExportTaskStatus").PROCESSING,
                ]
            ),
        )
        .order_by(ports("ExportTask").created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _sort_dict(d, *, ports):
    """Recursively sort a dict for stable hashing."""
    return {
        k: ports("_sort_dict")(v) if ports("isinstance")(v, ports("dict")) else v
        for k, v in ports("sorted")(d.items())
    }
