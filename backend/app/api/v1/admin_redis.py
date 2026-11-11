"""Admin Redis observability & governance endpoints.

- GET  /api/admin/v1/redis/online      — currently-online admins (admin:online:*)
- GET  /api/admin/v1/redis/ocr-tasks/{task_id} — OCR progress snapshot (admin:ocr:task:*)
- GET/POST/DELETE /api/admin/v1/redis/bypass-tokens — rate-limit exemption registry
  (admin:bypass:*; creation/removal are critical ops and write audit_log)

Read endpoints degrade gracefully when Redis is unavailable (empty snapshot);
bypass-token writes fail with 503 because they are security-relevant state.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_guards import admin_rate_limit
from app.core.admin_redis import (
    create_bypass_token,
    hash_bypass_token,
    online_presence,
)
from app.core.admin_security import AdminPrincipal, require_permissions
from app.core.cache import CacheUnavailableError, cache
from app.core.database import get_db
from app.models.ocr_job import OCRJob
from app.services.admin_audit_service import write_admin_audit
from app.core.runtime_paths import API_ADMIN_V1_PREFIX
logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{API_ADMIN_V1_PREFIX}/redis", tags=["admin-redis"])


class OnlineAdminItem(BaseModel):
    user_id: int
    last_active_at: float | None = None
    ip: str | None = None
    user_agent: str | None = None


class OnlineSnapshotResponse(BaseModel):
    items: list[OnlineAdminItem]
    count: int


@router.get("/online", response_model=OnlineSnapshotResponse)
async def list_online_admins(
    _=Depends(require_permissions("system:read")),
    __=Depends(admin_rate_limit),
):
    items = await online_presence.snapshot()
    return OnlineSnapshotResponse(
        items=[OnlineAdminItem(**item) for item in items],
        count=len(items),
    )


class OcrTaskSnapshotResponse(BaseModel):
    task_id: str
    status: str | None = None
    progress: int | None = None
    error: str | None = None
    error_code: str | None = None
    updated_at: str | None = None
    source: str = "cache"


@router.get("/ocr-tasks/{task_id}", response_model=OcrTaskSnapshotResponse)
async def get_ocr_task_snapshot(
    task_id: str,
    _=Depends(require_permissions("import:read")),
    db: AsyncSession = Depends(get_db),
):
    """Best-effort OCR progress snapshot, falling back to the authoritative DB."""
    if len(task_id) > 128 or not task_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid task id"
        )
    try:
        data = await cache.get(f"admin:ocr:task:{task_id}")
    except Exception:
        data = None
    source = "cache"
    if not isinstance(data, dict):
        job = await db.get(OCRJob, task_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
            )
        data = {
            "task_id": job.id,
            "status": job.status,
            "progress": 100 if job.status == "completed" else 0,
            "error": job.last_error_message,
            "error_code": job.last_error_code,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }
        source = "database"
    return OcrTaskSnapshotResponse(
        task_id=str(data.get("task_id", task_id)),
        status=data.get("status"),
        progress=data.get("progress"),
        error=data.get("error"),
        error_code=data.get("error_code"),
        updated_at=data.get("updated_at"),
        source=source,
    )


class BypassTokenCreateRequest(BaseModel):
    note: str | None = None
    type: str = "monitor"
    ttl_seconds: int | None = None


class BypassTokenCreateResponse(BaseModel):
    token: str
    token_hash: str
    type: str
    note: str | None


class BypassTokenDeleteResponse(BaseModel):
    deleted: bool


@router.post("/bypass-tokens", response_model=BypassTokenCreateResponse)
async def create_bypass(
    data: BypassTokenCreateRequest,
    request: Request,
    current_admin: AdminPrincipal = Depends(require_permissions("system:write")),
    db: AsyncSession = Depends(get_db),
):
    """Create a rate-limit exemption token. Raw token shown once — store it now."""
    if data.type not in {"monitor", "internal"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="type must be monitor or internal",
        )
    if data.ttl_seconds is not None and not (
        60 <= data.ttl_seconds <= 30 * 24 * 60 * 60
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="ttl_seconds out of range"
        )

    token = secrets.token_urlsafe(32)
    try:
        await create_bypass_token(
            token, type_=data.type, note=data.note, ttl=data.ttl_seconds
        )
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis unavailable — bypass registry requires it",
        ) from exc

    token_hash = hash_bypass_token(token)
    await write_admin_audit(
        db,
        current_admin,
        "redis.bypass.create",
        "redis_bypass_token",
        token_hash,
        severity="critical",
        detail={"type": data.type, "note": data.note, "token_hash": token_hash},
        request=request,
    )
    await db.commit()
    return BypassTokenCreateResponse(
        token=token, token_hash=token_hash, type=data.type, note=data.note
    )


@router.delete("/bypass-tokens/{token_hash}", response_model=BypassTokenDeleteResponse)
async def delete_bypass(
    token_hash: str,
    request: Request,
    current_admin: AdminPrincipal = Depends(require_permissions("system:write")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a bypass token by its SHA-256 hash (raw tokens are not stored)."""
    if len(token_hash) != 64 or not all(
        c in "0123456789abcdef" for c in token_hash.lower()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token hash"
        )
    deleted = await delete_bypass_token_by_hash(token_hash.lower())
    await write_admin_audit(
        db,
        current_admin,
        "redis.bypass.delete",
        "redis_bypass_token",
        token_hash,
        severity="critical",
        detail={"deleted": deleted},
        request=request,
    )
    await db.commit()
    return BypassTokenDeleteResponse(deleted=deleted)


async def delete_bypass_token_by_hash(token_hash: str) -> bool:
    from app.core.cache import cache as _cache

    try:
        return bool(await _cache.delete_strict(f"admin:bypass:{token_hash}"))
    except CacheUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis unavailable — bypass registry requires it",
        )
