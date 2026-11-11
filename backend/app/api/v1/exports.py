"""Export task API routes — create, list, download, delete, retry, re-export."""

from __future__ import annotations

import builtins as _export_builtins
import logging
import os  # noqa: F401 -- live route dependency port

from fastapi import (  # noqa: F401 -- live route dependency port
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
)
from fastapi.responses import FileResponse  # noqa: F401 -- live route dependency port
from sqlalchemy import select  # noqa: F401 -- live route dependency port
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings  # noqa: F401 -- live route dependency port
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.time_utils import utcnow  # noqa: F401 -- live route dependency port
from app.models.export_task import ExportTask
from app.models.user import User
from app.schemas.common import (  # noqa: F401 -- live route dependency port
    RawPaginatedResponse,
    paginated_response,
)
from app.schemas.export_task import (
    CreateExportTaskRequest,
    DownloadInfoResponse,
    ExportCapabilityResponse,
    ExportErrorCode,  # noqa: F401 -- live route dependency port
    ExportRangeType,  # noqa: F401 -- live route dependency port
    ExportTaskResponse,
    ExportTaskStatus,  # noqa: F401 -- live route dependency port
    PreviewCountRequest,
    PreviewCountResponse,
)
from app.services.export import api_creation as _export_api_creation
from app.services.export import api_deletion as _export_api_deletion
from app.services.export import api_downloads as _export_api_downloads
from app.services.export import api_projection as _export_api_projection
from app.services.export import api_queries as _export_api_queries
from app.services.export import api_regeneration as _export_api_regeneration
from app.services.export import api_websocket as _export_api_websocket
from app.services.export.capability import (
    build_capability,
    ensure_format_allowed,  # noqa: F401 -- live route dependency port
    raise_export_error,  # noqa: F401 -- live route dependency port
    validate_export_range,  # noqa: F401 -- live route dependency port
)
from app.services.export.service import (
    REEXPORT_FAILED_ERROR_CODE,  # noqa: F401 -- live route dependency port
    REEXPORTING_ERROR_CODE,  # noqa: F401 -- live route dependency port
)
from app.services.export.service import (
    create_export_task as _create_export_task,  # noqa: F401 -- live route dependency port
)
from app.services.export.service import (
    preview_count as _preview_count,  # noqa: F401 -- live route dependency port
)
from app.services.export.snapshot_service import (  # noqa: F401 -- live route dependency port
    delete_snapshot,
    load_snapshot,
)
from app.services.storage_backend import (  # noqa: F401 -- live route dependency port
    LocalFileStorage,
    get_export_storage,
)
from app.core.runtime_paths import API_V1_PREFIX


def _export_api_port(name):
    """Read original route dependencies where the operation uses them."""
    if name in globals():
        return globals()[name]
    return getattr(_export_builtins, name)


logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{API_V1_PREFIX}/exports")

# ── Idempotency window (seconds) ──
_IDEMPOTENCY_WINDOW_SEC = 60

# ── MIME types per format ──
_FORMAT_MIME: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _mime_for_format(file_format: str) -> str:
    return _export_api_downloads._mime_for_format(file_format, ports=_export_api_port)


def _wake_local_export_processor() -> None:
    """Best-effort low-latency wakeup for a processor in this process.

    Split web/scheduler deployments still rely on the processor's periodic DB
    scan, so this helper intentionally has no cross-process side effects.
    """
    try:
        from app.services.export.processor import wake_export_processor

        wake_export_processor()
    except Exception:
        logger.debug("Local export processor wakeup failed", exc_info=True)


# ── Health check ──


@router.get("/health")
async def export_health():
    """Minimal public probe; detailed diagnostics live under admin APIs."""
    return {"status": "ok"}


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
    return await _export_api_queries.preview_export_count(
        req, db, current_user, ports=_export_api_port
    )


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
    return await _export_api_creation.create_export(
        req, db, current_user, ports=_export_api_port
    )


@router.get("", response_model=RawPaginatedResponse)
async def list_exports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the current user's export tasks (newest first)."""
    # Count
    return await _export_api_queries.list_exports(
        page, page_size, db, current_user, ports=_export_api_port
    )


@router.get("/{task_id}", response_model=ExportTaskResponse)
async def get_export(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single export task's details."""
    return await _export_api_queries.get_export(
        task_id, db, current_user, ports=_export_api_port
    )


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
    return await _export_api_downloads.download_export(
        task_id, db, current_user, ports=_export_api_port
    )


@router.get("/{task_id}/file")
async def stream_export_file(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream the export PDF file directly (for local storage)."""
    return await _export_api_downloads.stream_export_file(
        task_id, db, current_user, ports=_export_api_port
    )


@router.delete("/{task_id}")
async def delete_export(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an export task, its file, and its snapshot."""
    return await _export_api_deletion.delete_export(
        task_id, db, current_user, ports=_export_api_port
    )


@router.post("/{task_id}/retry", response_model=ExportTaskResponse)
async def retry_export(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retry a failed export task — creates a new task from the original config."""
    return await _export_api_regeneration.retry_export(
        task_id, db, current_user, ports=_export_api_port
    )


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
    return await _export_api_regeneration.re_export(
        task_id, db, current_user, ports=_export_api_port
    )


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
    return await _export_api_websocket.export_status_ws(ws, ports=_export_api_port)


# ── Internal helpers ──


async def _get_user_task(
    db: AsyncSession,
    task_id: int,
    user_id: int,
    *,
    for_update: bool = False,
) -> ExportTask:
    """Get a task and verify ownership, optionally serialising mutations."""
    return await _export_api_queries._get_user_task(
        db, task_id, user_id, for_update=for_update, ports=_export_api_port
    )


def _task_to_response(task: ExportTask) -> ExportTaskResponse:
    # Determine status_reason for pending tasks
    return _export_api_projection._task_to_response(task, ports=_export_api_port)


def _task_to_config(task: ExportTask) -> dict:
    return _export_api_queries._task_to_config(task, ports=_export_api_port)


def _build_idempotency_key(user_id: int, req: CreateExportTaskRequest) -> str:
    """Build a stable idempotency key from the request — generated BEFORE snapshot."""
    return _export_api_queries._build_idempotency_key(
        user_id, req, ports=_export_api_port
    )


async def _find_existing_task(
    db: AsyncSession,
    user_id: int,
    idempotency_key: str,
) -> ExportTask | None:
    """Find an existing task with the same idempotency key in non-terminal state."""
    return await _export_api_queries._find_existing_task(
        db, user_id, idempotency_key, ports=_export_api_port
    )


def _resolve_local_path(file_key: str) -> str | None:
    """Resolve a storage key to a local file path with path traversal protection.

    Uses the same ``get_export_storage_root()`` as the storage backend for
    consistent path resolution.
    """
    return _export_api_downloads._resolve_local_path(file_key, ports=_export_api_port)


def _sort_dict(d: dict) -> dict:
    """Recursively sort a dict for stable hashing."""
    return _export_api_queries._sort_dict(d, ports=_export_api_port)


def _url_encode_filename(name: str) -> str:
    """Encode filename for Content-Disposition header."""
    return _export_api_downloads._url_encode_filename(name, ports=_export_api_port)
