"""Authenticated export download metadata and file streaming."""

from __future__ import annotations


async def download_export(task_id, db, current_user, *, ports):
    """Get download info for a completed export file.

    For local storage: streams the file directly.
    For COS: returns a short-lived signed URL.
    """
    task = await ports("_get_user_task")(db, task_id, current_user.id)
    if not task.file_key:
        ports("raise_export_error")(
            400, ports("ExportErrorCode").FILE_NOT_READY, "文件尚未生成或已过期"
        )
    previewable_statuses = {
        ports("ExportTaskStatus").COMPLETED,
        ports("ExportTaskStatus").PENDING,
        ports("ExportTaskStatus").PROCESSING,
        ports("ExportTaskStatus").FAILED,
    }
    if task.status not in previewable_statuses:
        ports("raise_export_error")(
            400, ports("ExportErrorCode").FILE_NOT_READY, "文件尚未生成或已过期"
        )
    if task.expires_at and task.expires_at < ports("utcnow")():
        ports("raise_export_error")(
            400, ports("ExportErrorCode").FILE_EXPIRED, "文件已过期"
        )
    storage = ports("get_export_storage")()
    if ports("isinstance")(storage, ports("LocalFileStorage")):
        return local_download_info(task, ports=ports)
    else:
        return await remote_download_info(task, storage, ports=ports)


async def stream_export_file(task_id, db, current_user, *, ports):
    """Stream the export PDF file directly (for local storage)."""
    task = await ports("_get_user_task")(db, task_id, current_user.id)
    if not task.file_key:
        ports("raise_export_error")(
            400, ports("ExportErrorCode").FILE_NOT_READY, "文件尚未生成"
        )
    previewable_statuses = {
        ports("ExportTaskStatus").COMPLETED,
        ports("ExportTaskStatus").PENDING,
        ports("ExportTaskStatus").PROCESSING,
        ports("ExportTaskStatus").FAILED,
    }
    if task.status not in previewable_statuses:
        ports("raise_export_error")(
            400, ports("ExportErrorCode").FILE_NOT_READY, "文件尚未生成"
        )
    if task.expires_at and task.expires_at < ports("utcnow")():
        ports("raise_export_error")(
            400, ports("ExportErrorCode").FILE_EXPIRED, "文件已过期"
        )
    file_path = ports("_resolve_local_path")(task.file_key or "")
    if not file_path or not ports("os").path.exists(file_path):
        ports("logger").error(
            "export_file_missing: task %d key %s", task.id, task.file_key
        )
        ports("raise_export_error")(
            500, ports("ExportErrorCode").FILE_NOT_FOUND, "文件不存在"
        )
    encoded_name = ports("_url_encode_filename")(task.file_name)
    return ports("FileResponse")(
        path=file_path,
        media_type=ports("_mime_for_format")(task.file_format),
        filename=task.file_name,
        headers={
            "Content-Disposition": f'inline; filename="{encoded_name}"',
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


def _resolve_local_path(file_key, *, ports):
    """Resolve a storage key to a local file path with path traversal protection.

    Uses the same ``get_export_storage_root()`` as the storage backend for
    consistent path resolution.
    """
    from app.services.storage_backend import get_export_storage_root

    export_root = get_export_storage_root()
    resolved = ports("os").path.realpath(ports("os").path.join(export_root, file_key))
    if not resolved.startswith(
        ports("os").path.realpath(export_root) + ports("os").sep
    ):
        ports("logger").warning(
            "Path traversal attempt blocked: %s -> %s", file_key, resolved
        )
        return None
    return resolved


def _url_encode_filename(name, *, ports):
    """Encode filename for Content-Disposition header."""
    from urllib.parse import quote

    return quote(name, safe="")


def _mime_for_format(file_format, *, ports):
    return ports("_FORMAT_MIME").get(file_format, "application/octet-stream")


def local_download_info(task, *, ports):
    file_path = ports("_resolve_local_path")(task.file_key)
    if not file_path or not ports("os").path.exists(file_path):
        ports("logger").error(
            "export_file_missing: task %d key %s", task.id, task.file_key
        )
        ports("raise_export_error")(
            500, ports("ExportErrorCode").FILE_NOT_FOUND, "文件不存在，请重新导出"
        )
    return ports("DownloadInfoResponse")(
        url=None,
        method="stream",
        file_name=task.file_name,
        file_size=task.file_size or ports("os").path.getsize(file_path),
        content_type=ports("_mime_for_format")(task.file_format),
    )


async def remote_download_info(task, storage, *, ports):
    signed_url = await storage.get_download_url(task.file_key, expiry_sec=3600)
    if not signed_url and ports("settings").COS_ALLOW_LOCAL_FALLBACK:
        file_path = ports("_resolve_local_path")(task.file_key)
        if file_path and ports("os").path.exists(file_path):
            return ports("DownloadInfoResponse")(
                url=None,
                method="stream",
                file_name=task.file_name,
                file_size=task.file_size or ports("os").path.getsize(file_path),
                content_type=ports("_mime_for_format")(task.file_format),
            )
    if not signed_url:
        ports("raise_export_error")(
            500, ports("ExportErrorCode").STORAGE_FAILED, "无法生成下载地址"
        )
    return ports("DownloadInfoResponse")(
        url=signed_url,
        method="signed_url",
        file_name=task.file_name,
        file_size=task.file_size or 0,
        content_type=ports("_mime_for_format")(task.file_format),
    )
