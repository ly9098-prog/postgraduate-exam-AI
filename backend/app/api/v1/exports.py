"""Export task API routes — create, list, download, delete, retry, re-export."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token, get_current_user
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
    ensure_export_allowed,
    ensure_format_allowed,
    is_user_allowed,
    raise_export_error,
)
from app.services.export.service import (
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


# ── Whitelist / access control ──
# Helpers are in app.services.export.capability:
#   is_user_allowed, ensure_export_allowed, ensure_format_allowed,
#   build_capability, raise_export_error


@router.get("/capabilities", response_model=ExportCapabilityResponse)
async def export_capabilities(
    current_user: User = Depends(get_current_user),
):
    """Return export capabilities for the current user.

    Used by the mini-program to decide whether to show the export entry
    point and which options to enable.  Does NOT leak internal config or
    the whitelist contents.
    """
    return build_capability(current_user)


@router.post("/preview-count", response_model=PreviewCountResponse)
async def preview_export_count(
    req: PreviewCountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Preview how many questions match the given export range + filters."""
    ensure_export_allowed(current_user.id)
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
    # Feature flag check
    ensure_export_allowed(current_user.id)

    if req.file_format == "docx":
        ensure_format_allowed("docx")

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

    task = await _create_export_task(db, current_user.id, {
        **req.model_dump(),
        "_idempotency_key": idempotency_key,
    })
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

    if task.status != ExportTaskStatus.COMPLETED:
        raise_export_error(400, ExportErrorCode.FILE_NOT_READY, "文件尚未生成或已过期")

    if task.expires_at and task.expires_at < datetime.now(UTC):
        raise_export_error(400, ExportErrorCode.FILE_EXPIRED, "文件已过期")

    if not task.file_key:
        raise_export_error(500, ExportErrorCode.FILE_NOT_FOUND, "文件记录不存在")

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

    if task.status != ExportTaskStatus.COMPLETED:
        raise_export_error(400, ExportErrorCode.FILE_NOT_READY, "文件尚未生成")

    if task.expires_at and task.expires_at < datetime.now(UTC):
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

    # Delete stored file
    if task.file_key:
        try:
            storage = get_export_storage()
            await storage.delete(task.file_key)
        except Exception as e:
            logger.warning("File delete failed for task %d: %s", task.id, e)

    # Delete snapshot
    if task.snapshot_id:
        try:
            await delete_snapshot(db, task.snapshot_id)
        except Exception as e:
            logger.warning("Snapshot delete failed for task %d: %s", task.id, e)

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

    # Feature flag check
    ensure_export_allowed(current_user.id)

    if task.file_format == "docx":
        ensure_format_allowed("docx")

    # Per-user concurrency limit
    from app.services.export.processor import _MAX_PER_USER, get_user_pending_count

    pending_count = await get_user_pending_count(db, current_user.id)
    if pending_count >= _MAX_PER_USER:
        raise_export_error(429, ExportErrorCode.TOO_MANY_CONCURRENT, f"同时最多只能有 {_MAX_PER_USER} 个未完成的任务，请等待当前任务完成")

    # Rebuild config from existing task
    config = _task_to_config(task)

    new_task = await _create_export_task(db, current_user.id, config)
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
    """Re-export using the original snapshot and config.

    Creates a new task. Does NOT override the original task.
    """
    task = await _get_user_task(db, task_id, current_user.id)

    if not task.snapshot_id:
        raise_export_error(400, ExportErrorCode.FILE_NOT_FOUND, "原任务没有快照，无法重新导出")

    # Feature flag check
    ensure_export_allowed(current_user.id)

    if task.file_format == "docx":
        ensure_format_allowed("docx")

    # Per-user concurrency limit
    from app.services.export.processor import _MAX_PER_USER, get_user_pending_count

    pending_count = await get_user_pending_count(db, current_user.id)
    if pending_count >= _MAX_PER_USER:
        raise_export_error(429, ExportErrorCode.TOO_MANY_CONCURRENT, f"同时最多只能有 {_MAX_PER_USER} 个未完成的任务，请等待当前任务完成")

    # Load snapshot for config
    snapshot_data = await load_snapshot(db, task.snapshot_id, current_user.id)
    if snapshot_data is None:
        raise_export_error(400, ExportErrorCode.FILE_NOT_FOUND, "原快照不存在或已过期")

    _snapshot_config = snapshot_data.get("config", {})

    config = {
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
        "_source_task_id": task.id,
        "_snapshot_id": task.snapshot_id,
    }

    new_task = await _create_export_task(db, current_user.id, config)
    # Copy snapshot reference for immediate reuse
    new_task.snapshot_id = task.snapshot_id
    new_task.source_task_id = task.id
    new_task.total_count = task.total_count

    await db.commit()
    await db.refresh(new_task)
    logger.info("export_task_reexported", extra={
        "task_id": new_task.id,
        "source_task_id": task.id,
        "user_id": current_user.id,
    })
    return _task_to_response(new_task)


# ── Health check ──


@router.get("/health")
async def export_health():
    """Lightweight export subsystem health check.

    Returns processor state and recent task counts.
    Note: ``_in_flight`` and ``_draining`` are process-local.
    In split-role deployments (web ≠ scheduler) the web process
    always reports 0 in_flight — this endpoint is most useful
    when the processor runs in the same process (development or
    ``PROCESS_ROLE=all``).
    """
    from app.services.export.processor import _draining, _in_flight

    return {
        "status": "ok" if not _draining else "draining",
        "in_flight": len(_in_flight),
        "draining": _draining,
    }


# ── WebSocket: real-time export status push ──


@router.websocket("/ws")
async def export_status_ws(ws: WebSocket):
    """WebSocket endpoint for real-time export task status.

    Authentication: pass JWT token as ``token`` query parameter.
    The user will receive export task status events for their own tasks.

    Protocol:
    - Client sends ``{"type": "ping"}`` → server responds ``{"type": "pong"}``
    - Server sends ``{"type": "export_status", "task_id": ..., ...}``
    - Server sends ``{"type": "ping"}`` periodically (heartbeat)
    """
    # Feature flag
    from app.core.config import settings

    # Check global feature flag before auth

    if not settings.EXPORT_FEATURE_ENABLED:
        await ws.close(code=4001, reason="导出功能已关闭")
        return
    if not settings.EXPORT_WEBSOCKET_ENABLED:
        await ws.close(code=4001, reason="实时推送功能已关闭")
        return

    # Authenticate via query param
    token = ws.query_params.get("token", "")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return

    try:
        user_id = decode_token(token)
    except Exception:
        await ws.close(code=4001, reason="Invalid token")
        return

    # Whitelist check (after auth, so we know who the user is)
    if not is_user_allowed(user_id):
        logger.info("export_websocket_failed", extra={
            "user_id": user_id,
            "reason": "user_not_allowed",
        })
        await ws.close(code=4001, reason="导出功能未开放")
        return

    logger.info("export_websocket_connected", extra={"user_id": user_id})

    from app.services.export.push_service import handle_export_ws

    await handle_export_ws(ws, user_id)


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
    return ExportTaskResponse(
        id=task.id,
        status=task.status,
        file_format=task.file_format,
        file_name=task.file_name,
        file_size=task.file_size,
        title=task.title,
        range_type=task.range_type,
        sort_by=task.sort_by,
        group_by=task.group_by,
        total_count=task.total_count,
        success_count=task.success_count,
        skip_count=task.skip_count,
        error_message=task.error_message,
        created_at=task.created_at,
        completed_at=task.completed_at,
        expires_at=task.expires_at,
        source_task_id=task.source_task_id,
        retry_count=task.retry_count,
        generator_version=task.generator_version,
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

    cutoff = datetime.now(UTC) - timedelta(seconds=_IDEMPOTENCY_WINDOW_SEC)
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

    Resolution goes through ``settings.EXPORT_DIR``, not ``backend_root + static/exports/``,
    to match the export storage backend's prefix.
    """
    import os

    from app.core.config import settings

    export_root = os.path.realpath(
        os.path.join(os.path.dirname(__file__), "..", "..", settings.EXPORT_DIR)
    )
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
