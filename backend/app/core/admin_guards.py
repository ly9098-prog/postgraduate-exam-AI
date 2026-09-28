"""Admin rate-limit and idempotency dependencies for critical writes."""

from __future__ import annotations

import hashlib

from fastapi import Depends, HTTPException, Request, status

from app.core.admin_redis import (
    IdempotencyClaim,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    check_admin_ratelimit,
    complete_idempotent_request,
    reserve_idempotent_request,
)
from app.core.admin_security import AdminPrincipal, get_current_admin
from app.core.cache import CacheUnavailableError

_IDEMPOTENCY_HEADER = "Idempotency-Key"
_BYPASS_HEADER = "X-Admin-Bypass-Token"


async def admin_rate_limit(
    request: Request,
    current_admin: AdminPrincipal = Depends(get_current_admin),
) -> None:
    role_name = getattr(current_admin.user, "role", None)
    is_super = (
        getattr(role_name, "name", None) == "super_admin"
        or current_admin.role_id == 1  # super_admin is the seeded role id 1
    )
    allowed = await check_admin_ratelimit(
        current_admin.id,
        request.url.path,
        is_super_admin=is_super,
        bypass_token=request.headers.get(_BYPASS_HEADER),
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后重试",
            headers={"Retry-After": "60"},
        )


async def require_idempotency(
    request: Request,
    current_admin: AdminPrincipal = Depends(get_current_admin),
) -> IdempotencyClaim:
    """Claim a user/key/request fingerprint before executing a critical write."""
    idem_key = request.headers.get(_IDEMPOTENCY_HEADER, "").strip()
    if not idem_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing {_IDEMPOTENCY_HEADER} header",
        )
    if len(idem_key) > 128 or any(c in idem_key for c in " \t\r\n"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Idempotency-Key",
        )
    body = await request.body()
    fingerprint = hashlib.sha256(
        b"\0".join(
            (
                request.method.encode(),
                request.url.path.encode(),
                request.url.query.encode(),
                body,
            )
        )
    ).hexdigest()
    try:
        return await reserve_idempotent_request(current_admin.id, idem_key, fingerprint)
    except IdempotencyInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
            headers={"Retry-After": "2"},
        ) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Idempotency store unavailable — retry later",
        ) from exc


async def finish_idempotency(claim: IdempotencyClaim, response: dict) -> None:
    """A failed completion must never be reported to the caller as success."""
    try:
        await complete_idempotent_request(claim, response)
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Idempotency result unavailable — retry later",
        ) from exc
