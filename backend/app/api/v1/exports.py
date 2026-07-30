"""Export task API routes — create, list, download, delete, retry, re-export."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.time_utils import utcnow
from app.models.export_task import ExportTask
from app.models.user import User
from app.schemas.common import RawPaginatedResponse, paginated_response
from app.schemas.export_task import (
    CreateExportTaskRequest,
    DownloadInfoResponse,
    ExportCapabilityResponse,
    ExportErrorCode,
    ExportRangeType,
    ExportTaskResponse,
    ExportTaskStatus,
    PreviewCountRequest,
    PreviewCountResponse,
)
from app.services.export.capability import (
    build_capability,
    ensure_format_allowed,
    raise_export_error,
    validate_export_range,
)
from app.services.export.service import (
    REEXPORTING_ERROR_CODE,
    REEXPORT_FAILED_ERROR_CODE,
    create_export_task as _create_export_task,
)
from app.services.export.service import (
    preview_count as _preview_count,
)
from app.services.export.snapshot_service import delete_snapshot, load_snapshot
from app.services.storage_backend import LocalFileStorage, get_export_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/exports")

# ── Idempotency window (seconds) ──
_IDEMPOTENCY_WINDOW_SEC = 60

# ── MIME types per format ──
_FORMAT_MIME: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _mime_for_format(file_format: str) -> str:
    return _FORMAT_MIME.get(file_format, "application/octet-stream")


@router.get("/capabilities", response_model=ExportCapabilityResponse)
async def export_capabilities(
    current_user: User = Depends(get_current_user),
):
    """Return global export formats and operational limits."""
    return build_capability(current_user)


@router.post("/preview-count", response_model=PreviewCountResponse)
async def preview_export_count(
    req: PreviewCountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Preview how many questions match the given export range + filters."""
    try:
        count = await _preview_count(
            db, current_user.id,
            ExportRangeType(req.range_type),
            req.filters,
            req.selected_ids,
        )
        logger.info("export_preview_count", extra={
            "user_id": current_user.id,
            "range_type": req.range_type,
            "count": count,
        })
        return PreviewCountResponse(count=count, range_type=req.range_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("", response_model=ExportTaskResponse)
async def create_export(
    req: CreateExportTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new export task. The PDF is generated asynchronously.

    Idempotency: repeated submissions with the same config within
    ``_IDEMPOTENCY_WINDOW_SEC`` return the existing pending/processing task.
    Re-export and retry create new tasks (call those endpoints instead).
    """
    if req.file_format == "docx":
        ensure_format_allowed("docx")

    # Validate range and count before creating
    range_type = ExportRangeType(req.range_type)
    count = await _preview_count(
        db, current_user.id,
        range_type,
        req.filters,
        req.selected_ids,
    )
    validate_export_range(req.range_type, req.selected_ids, count)

    # Check idempotency
    idempotency_key = _build_idempotency_key(current_user.id, req)
    if idempotency_key:
        existing = await _find_existing_task(db, current_user.id, idempotency_key)
        if existing is not None:
            return _task_to_response(existing)

    # Per-user concurrency limit
    from app.services.export.processor import _MAX_PER_USER, get_user_pending_count

    # Serialize concurrent creation per user by locking existing pending/processing tasks
    # PostgreSQL: FOR UPDATE blocks until competing xact commits
    # SQLite: FOR UPDATE is parsed but ignored — race bound ≤1 extra task
    await db.execute(
        select(ExportTask.id)
        .where(
            ExportTask.user_id == current_user.id,
            ExportTask.status.in_([ExportTaskStatus.PENDING, ExportTaskStatus.PROCESSING]),
        )
        .limit(_MAX_PER_USER)
        .with_for_update()
    )
    pending_count = await get_user_pending_count(db, current_user.id)
    if pending_count >= _MAX_PER_USER:
        raise_export_error(429, ExportErrorCode.TOO_MANY_CONCURRENT, f"同时最多只能有 {_MAX_PER_USER} 个未完成的任务，请等待当前任务完成")

    # Capture user_id before any DB mutation — needed in the IntegrityError
    # recovery path after db.rollback() (which expires all ORM objects).
    _user_id = current_user.id

    # Validation + idempotency + per-user limit all passed.
    # Catch idempotency_key UNIQUE constraint violations from the database layer.
    # This handles cases where the migration to drop the UNIQUE constraint hasn't
    # been applied (SQLite) or a race condition between idempotency check and INSERT.
    from sqlalchemy.exc import IntegrityError
    try:
        task = await _create_export_task(db, _user_id, {
            **req.model_dump(),
            "_idempotency_key": idempotency_key,
        })
        task.total_count = count
    except IntegrityError:
        await db.rollback()
        # Another task with the same config was created concurrently, or the
        # idempotency_key UNIQUE constraint still exists. Use the local
        # _user_id captured before the try block (ORM objects are expired
        # after rollback — accessing current_user.id would trigger MissingGreenlet).
        if idempotency_key:
            existing = await _find_existing_task(db, _user_id, idempotency_key)
            if existing is not None:
                return _task_to_response(existing)
        # If we still can't find it, try to return any task with this key
        from app.services.export.service import find_task_by_idempotency_key
        existing = await find_task_by_idempotency_key(db, _user_id, idempotency_key)
        if existing is not None:
            return _task_to_response(existing)
        # Last resort: re-raise as a structured error
        raise_export_error(409, ExportErrorCode.TASK_ALREADY_EXISTS, "相同配置的导出任务已存在")
    await db.commit()
    await db.refresh(task)
    logger.info("export_task_created", extra={
        "task_id": task.id,
        "user_id": current_user.id,
        "format": task.file_format,
        "range_type": task.range_type,
        "question_count": task.total_count,
    })
    return _task_to_response(task)


@router.get("", response_model=RawPaginatedResponse)
async def list_exports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the current user's export tasks (newest first)."""
    # Count
    count_result = await db.execute(
        select(ExportTask.id)
        .where(ExportTask.user_id == current_user.id)
    )
    total = len(count_result.fetchall())

    # Items
    result = await db.execute(
        select(ExportTask)
        .where(ExportTask.user_id == current_user.id)
        .order_by(ExportTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    tasks = result.scalars().all()

    items = [_task_to_response(t).model_dump() for t in tasks]
    return paginated_response(items=items, total=total, page=page, page_size=page_size)


@router.get("/{task_id}", response_model=ExportTaskResponse)
async def get_export(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single export task's details."""
    task = await _get_user_task(db, task_id, current_user.id)
    return _task_to_response(task)


@router.get("/{task_id}/download", response_model=DownloadInfoResponse)
async def download_export(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get download info for a completed export file.

    For local storage: streams the file directly.
    For COS: returns a short-lived signed URL.
    """
    task = await _get_user_task(db, task_id, current_user.id)

    if not task.file_key:
        raise_export_error(400, ExportErrorCode.FILE_NOT_READY, "文件尚未生成或已过期")

    # A same-record re-export keeps the previous complete file available while
    # the replacement is pending/processing. The file is never regenerated by
    # this read-only endpoint.
    previewable_statuses = {
        ExportTaskStatus.COMPLETED,
        ExportTaskStatus.PENDING,
        ExportTaskStatus.PROCESSING,
        ExportTaskStatus.FAILED,
    }
    if task.status not in previewable_statuses:
        raise_export_error(400, ExportErrorCode.FILE_NOT_READY, "文件尚未生成或已过期")

    if task.expires_at and task.expires_at < utcnow():
        raise_export_error(400, ExportErrorCode.FILE_EXPIRED, "文件已过期")

    storage = get_export_storage()

    if isinstance(storage, LocalFileStorage):
        # Stream the file directly
        file_path = _resolve_local_path(task.file_key)
        if not file_path or not os.path.exists(file_path):
            logger.error("export_file_missing: task %d key %s", task.id, task.file_key)
            raise_export_error(500, ExportErrorCode.FILE_NOT_FOUND, "文件不存在，请重新导出")

        return DownloadInfoResponse(
            url=None,
            method="stream",
            file_name=task.file_name,
            file_size=task.file_size or os.path.getsize(file_path),
            content_type=_mime_for_format(task.file_format),
        )
    else:
        # COS — generate a short-lived signed URL (never return a permanent URL)
        signed_url = await storage.get_download_url(task.file_key, expiry_sec=3600)
        if not signed_url:
            raise_export_error(500, ExportErrorCode.STORAGE_FAILED, "无法生成下载地址")
        return DownloadInfoResponse(
            url=signed_url,
            method="signed_url",
            file_name=task.file_name,
            file_size=task.file_size or 0,
            content_type=_mime_for_format(task.file_format),
        )


@router.get("/{task_id}/file")
async def stream_export_file(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream the export PDF file directly (for local storage)."""
    task = await _get_user_task(db, task_id, current_user.id)

    if not task.file_key:
        raise_export_error(400, ExportErrorCode.FILE_NOT_READY, "文件尚未生成")

    previewable_statuses = {
        ExportTaskStatus.COMPLETED,
        ExportTaskStatus.PENDING,
        ExportTaskStatus.PROCESSING,
        ExportTaskStatus.FAILED,
    }
    if task.status not in previewable_statuses:
        raise_export_error(400, ExportErrorCode.FILE_NOT_READY, "文件尚未生成")

    if task.expires_at and task.expires_at < utcnow():
        raise_export_error(400, ExportErrorCode.FILE_EXPIRED, "文件已过期")

    file_path = _resolve_local_path(task.file_key or "")
    if not file_path or not os.path.exists(file_path):
        logger.error("export_file_missing: task %d key %s", task.id, task.file_key)
        raise_export_error(500, ExportErrorCode.FILE_NOT_FOUND, "文件不存在")

    encoded_name = _url_encode_filename(task.file_name)
    return FileResponse(
        path=file_path,
        media_type=_mime_for_format(task.file_format),
        filename=task.file_name,
        headers={
            "Content-Disposition": f'inline; filename="{encoded_name}"',
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.delete("/{task_id}")
async def delete_export(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an export task, its file, and its snapshot."""
    task = await _get_user_task(db, task_id, current_user.id)

    # Delete stored file — check return value
    if task.file_key:
        try:
            storage = get_export_storage()
            deleted = await storage.delete(task.file_key)
            if not deleted:
                logger.warning("File delete returned false for task %d, key %s — DB record still retained", task.id, task.file_key)
        except Exception as e:
            logger.warning("File delete failed for task %d: %s — DB record retained", task.id, e)

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
            else:
                logger.debug("Snapshot %s still referenced by other tasks — skipping delete", task.snapshot_id)
        except Exception as e:
            logger.warning("Snapshot delete check failed for task %d: %s", task.id, e)

    await db.delete(task)
    await db.commit()
    logger.info("export_task_deleted", extra={
        "task_id": task_id,
        "user_id": current_user.id,
        "format": task.file_format,
    })
    return {"success": True}


@router.post("/{task_id}/retry", response_model=ExportTaskResponse)
async def retry_export(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retry a failed export task — creates a new task from the original config."""
    task = await _get_user_task(db, task_id, current_user.id)

    if task.status != ExportTaskStatus.FAILED:
        raise_export_error(400, ExportErrorCode.ACCESS_DENIED, "只有失败的任务可以重试")

    if task.file_format == "docx":
        ensure_format_allowed("docx")

    # Rebuild config from existing task
    config = _task_to_config(task)

    # Validate range and count before creating
    range_type = ExportRangeType(config["range_type"])
    count = await _preview_count(
        db, current_user.id,
        range_type,
        config.get("filters"),
        config.get("selected_ids"),
    )
    validate_export_range(config["range_type"], config.get("selected_ids"), count)

    # Per-user concurrency limit
    from app.services.export.processor import _MAX_PER_USER, get_user_pending_count

    pending_count = await get_user_pending_count(db, current_user.id)
    if pending_count >= _MAX_PER_USER:
        raise_export_error(429, ExportErrorCode.TOO_MANY_CONCURRENT, f"同时最多只能有 {_MAX_PER_USER} 个未完成的任务，请等待当前任务完成")

    config = _task_to_config(task)

    new_task = await _create_export_task(db, current_user.id, config)
    new_task.source_task_id = task.id
    new_task.retry_count = (task.retry_count or 0) + 1
    new_task.total_count = count
    await db.commit()
    await db.refresh(new_task)
    logger.info("export_task_retried", extra={
        "task_id": new_task.id,
        "source_task_id": task.id,
        "user_id": current_user.id,
    })
    return _task_to_response(new_task)


@router.post("/{task_id}/re-export", response_model=ExportTaskResponse)
async def re_export(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Regenerate an earlier export in place.

    The existing database row and stable storage key are reused. During
    generation the previous complete file remains readable; after generation,
    LocalFileStorage atomically replaces it. No new export-task directory is
    created and the records page continues to show a single card.
    """
    task = await _get_user_task(db, task_id, current_user.id)

    if task.file_format == "docx":
        ensure_format_allowed("docx")

    if task.status in (ExportTaskStatus.PENDING, ExportTaskStatus.PROCESSING):
        raise_export_error(400, ExportErrorCode.ACCESS_DENIED, "该文件正在导出，请稍候")

    from app.services.export.processor import _MAX_PER_USER, get_user_pending_count

    pending_count = await get_user_pending_count(db, current_user.id)
    if pending_count >= _MAX_PER_USER:
        raise_export_error(
            429,
            ExportErrorCode.TOO_MANY_CONCURRENT,
            f"同时最多只能有 {_MAX_PER_USER} 个未完成的任务，请等待当前任务完成",
        )

    config = _task_to_config(task)
    reusable_snapshot_id: str | None = None
    if task.snapshot_id:
        snapshot_data = await load_snapshot(db, task.snapshot_id, current_user.id)
        if snapshot_data is not None:
            reusable_snapshot_id = task.snapshot_id
        else:
            logger.warning(
                "Re-export source snapshot missing: task=%d snapshot=%s; rebuilding from config",
                task.id,
                task.snapshot_id,
            )

    if reusable_snapshot_id is None:
        range_type = ExportRangeType(config["range_type"])
        count = await _preview_count(
            db,
            current_user.id,
            range_type,
            config.get("filters"),
            config.get("selected_ids"),
        )
        validate_export_range(
            config["range_type"],
            config.get("selected_ids"),
            count,
        )
        task.snapshot_id = None

    now = utcnow()
    has_valid_previous_file = bool(
        task.file_key
        and task.completed_at
        and (task.expires_at is None or task.expires_at > now)
    )
    if not has_valid_previous_file:
        task.file_key = None
        task.file_size = None
        task.completed_at = None
        task.expires_at = None

    task.status = ExportTaskStatus.PENDING
    task.error_message = None
    task.error_code = REEXPORTING_ERROR_CODE if has_valid_previous_file else None
    task.processing_started_at = None
    task.started_at = None
    task.heartbeat_at = None
    task.retry_count = (task.retry_count or 0) + 1
    task.version = (task.version or 0) + 1
    task.idempotency_key = None
    task.generator_version = settings.GENERATOR_VERSION

    await db.commit()
    await db.refresh(task)
    logger.info(
        "export_task_reexported_in_place",
        extra={
            "task_id": task.id,
            "user_id": current_user.id,
            "snapshot_reused": reusable_snapshot_id is not None,
            "kept_previous_file": bool(task.file_key),
        },
    )
    return _task_to_response(task)


# ── Health check ──


@router.get("/health")
async def export_health():
    """Minimal public probe; detailed diagnostics live under admin APIs."""
    return {"status": "ok"}


# ── WebSocket: real-time export status push ──


@router.websocket("/ws")
async def export_status_ws(ws: WebSocket):
    """WebSocket endpoint for real-time export task status.

    Authentication: pass ``["bearer", "<JWT>"]`` as WebSocket subprotocols.
    Query-string tokens are accepted only in local development or when the
    explicitly unsafe compatibility flag is enabled.
    The user will receive export task status events for their own tasks.

    Protocol:
    - Client sends ``{"type": "ping"}`` → server responds ``{"type": "pong"}``
    - Server sends ``{"type": "export_status", "task_id": ..., ...}``
    - Server sends ``{"type": "ping"}`` periodically (heartbeat)
    """
    from app.core.config import settings

    if not settings.EXPORT_WEBSOCKET_ENABLED:
        await ws.close(code=4001, reason="实时推送功能已关闭")
        return

    # Prefer WebSocket subprotocols so credentials do not appear in URLs,
    # reverse-proxy access logs, browser history or monitoring traces.
    offered_protocols = [
        item.strip()
        for item in ws.headers.get("sec-websocket-protocol", "").split(",")
        if item.strip()
    ]
    token = ""
    selected_subprotocol = None
    if "bearer" in offered_protocols:
        index = offered_protocols.index("bearer")
        if index + 1 < len(offered_protocols):
            token = offered_protocols[index + 1]
            selected_subprotocol = "bearer"

    local_env = settings.APP_ENV.lower() in {"development", "local", "test"}
    if not token and (
        local_env or settings.ALLOW_LEGACY_WEBSOCKET_QUERY_TOKEN
    ):
        token = ws.query_params.get("token", "")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return

    try:
        from app.core.database import async_session
        from app.core.security import authenticate_user_token

        async with async_session() as db:
            user, _payload = await authenticate_user_token(token, db)
        user_id = user.id
    except Exception:
        await ws.close(code=4001, reason="Invalid token")
        return

    logger.info("export_websocket_connected", extra={"user_id": user_id})

    from app.services.export.push_service import handle_export_ws

    await handle_export_ws(
        ws,
        user_id,
        auth_token=token,
        subprotocol=selected_subprotocol,
    )


# ── Internal helpers ──


async def _get_user_task(db: AsyncSession, task_id: int, user_id: int) -> ExportTask:
    """Get a task and verify ownership."""
    result = await db.execute(
        select(ExportTask).where(ExportTask.id == task_id, ExportTask.user_id == user_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise_export_error(404, ExportErrorCode.TASK_NOT_FOUND, "导出任务不存在")
    return task


def _task_to_response(task: ExportTask) -> ExportTaskResponse:
    # Determine status_reason for pending tasks
    status_reason = None
    status_message = None
    if task.status == ExportTaskStatus.PENDING:
        # Check if processor is locally available
        try:
            from app.services.export.processor import get_processor_health
            ph = get_processor_health()
            if not ph.get("running", False):
                status_reason = "processor_unavailable"
                status_message = "导出处理服务暂不可用，请稍后重试"
        except Exception:
            pass
        # Check pending duration
        from app.core.config import settings as _export_settings
        from app.core.time_utils import utcnow as _utcnow
        if task.created_at:
            pending_seconds = (_utcnow() - task.created_at).total_seconds()
            warning_seconds = getattr(_export_settings, "EXPORT_PENDING_WARNING_SECONDS", 30)
            if pending_seconds > warning_seconds:
                if status_reason is None:
                    status_reason = "pending_timeout"
                    status_message = "等待时间较长，导出处理服务可能未启动"
                else:
                    status_message = "导出处理服务暂不可用，请稍后重试或联系管理员"

    now = utcnow()
    has_file = bool(
        task.file_key
        and (task.expires_at is None or task.expires_at > now)
    )
    response_status = (
        ExportTaskStatus.EXPIRED
        if task.status == ExportTaskStatus.COMPLETED
        and task.expires_at is not None
        and task.expires_at <= now
        else task.status
    )
    is_reexporting = bool(
        task.error_code == REEXPORTING_ERROR_CODE
        and task.status in (ExportTaskStatus.PENDING, ExportTaskStatus.PROCESSING)
    )
    reexport_failed = task.error_code == REEXPORT_FAILED_ERROR_CODE and has_file

    return ExportTaskResponse(
        id=task.id,
        status=response_status,
        file_format=task.file_format,
        file_name=task.file_name,
        file_size=task.file_size,
        title=task.title,
        range_type=task.range_type,
        sort_by=task.sort_by,
        group_by=task.group_by,
        answer_position=task.answer_position,
        analysis_position=task.analysis_position,
        space_style=task.space_style,
        total_count=task.total_count,
        success_count=task.success_count,
        skip_count=task.skip_count,
        error_message=task.error_message,
        status_reason=status_reason,
        status_message=status_message,
        created_at=task.created_at,
        completed_at=task.completed_at,
        expires_at=task.expires_at,
        source_task_id=task.source_task_id,
        retry_count=task.retry_count,
        generator_version=task.generator_version,
        has_file=has_file,
        is_reexporting=is_reexporting,
        reexport_failed=reexport_failed,
    )


def _task_to_config(task: ExportTask) -> dict:
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


def _build_idempotency_key(user_id: int, req: CreateExportTaskRequest) -> str:
    """Build a stable idempotency key from the request — generated BEFORE snapshot."""
    import hashlib
    import json

    raw = {
        "user_id": user_id,
        "range_type": req.range_type,
        "filters": _sort_dict(req.filters) if req.filters else None,
        "selected_ids": sorted(req.selected_ids) if req.selected_ids else None,
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
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return f"export_{digest[:32]}"


async def _find_existing_task(
    db: AsyncSession,
    user_id: int,
    idempotency_key: str,
) -> ExportTask | None:
    """Find an existing task with the same idempotency key in non-terminal state."""
    from datetime import timedelta

    cutoff = utcnow() - timedelta(seconds=_IDEMPOTENCY_WINDOW_SEC)
    result = await db.execute(
        select(ExportTask).where(
            ExportTask.user_id == user_id,
            ExportTask.idempotency_key == idempotency_key,
            ExportTask.created_at >= cutoff,
            ExportTask.status.in_([
                ExportTaskStatus.PENDING,
                ExportTaskStatus.PROCESSING,
            ]),
        ).order_by(ExportTask.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


def _resolve_local_path(file_key: str) -> str | None:
    """Resolve a storage key to a local file path with path traversal protection.

    Uses the same ``get_export_storage_root()`` as the storage backend for
    consistent path resolution.
    """
    from app.services.storage_backend import get_export_storage_root

    export_root = get_export_storage_root()
    resolved = os.path.realpath(os.path.join(export_root, file_key))

    # Path traversal protection: resolved path must be under export_root
    if not resolved.startswith(os.path.realpath(export_root) + os.sep):
        logger.warning("Path traversal attempt blocked: %s -> %s", file_key, resolved)
        return None

    return resolved


def _sort_dict(d: dict) -> dict:
    """Recursively sort a dict for stable hashing."""
    return {k: _sort_dict(v) if isinstance(v, dict) else v for k, v in sorted(d.items())}


def _url_encode_filename(name: str) -> str:
    """Encode filename for Content-Disposition header."""
    from urllib.parse import quote
    return quote(name, safe="")
