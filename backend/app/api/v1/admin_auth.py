import hashlib
import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import (
    REFRESH_COOKIE_KEY,
    AdminPrincipal,
    PasswordPolicyError,
    blacklist_admin_token,
    consume_admin_refresh_token,
    decode_admin_refresh_token,
    delete_refresh_cookie,
    get_current_admin,
    set_refresh_cookie,
)
from app.core.cache import CacheUnavailableError, cache
from app.core.config import settings
from app.core.database import get_db
from app.core.time_utils import utcnow
from app.schemas.admin_auth import (
    AdminChangePasswordRequest,
    AdminLoginRequest,
    AdminMeResponse,
    AdminTokenResponse,
)
from app.services.admin_audit_service import write_admin_audit
from app.services.admin_auth_service import (
    authenticate_admin,
    build_admin_login_response,
    change_admin_password,
    get_admin_me_response,
)
from app.core.runtime_paths import API_ADMIN_V1_PREFIX

logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{API_ADMIN_V1_PREFIX}/auth", tags=["admin-auth"])


def _normalized_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}:{port}"


def _enforce_trusted_browser_origin(request: Request) -> None:
    """Block cross-site browser requests to cookie-bearing auth endpoints."""
    origin = request.headers.get("origin")
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if not origin:
        if fetch_site == "cross-site":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Invalid request origin"
            )
        return
    allowed = {
        normalized
        for value in [*settings.CORS_ORIGINS, settings.PUBLIC_BASE_URL]
        if (normalized := _normalized_origin(value)) is not None
    }
    if _normalized_origin(origin) not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid request origin"
        )


def _login_rate_key(request: Request, username: str) -> str:
    client_ip = request.client.host if request.client else "unknown"
    identity = f"{client_ip}|{username.strip().lower()}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"admin:login:fail:{digest}"


def _account_fail_key(username: str) -> str:
    """Account-level consecutive-failure counter (independent of client IP)."""
    return f"admin:login:account_fail:{username.strip().lower()}"


def _account_lock_key(username: str) -> str:
    """Temporary lock flag for an account that exceeded the failure threshold."""
    return f"admin:login:account_lock:{username.strip().lower()}"


async def _read_fail_count(rate_key: str) -> int:
    try:
        return int(await cache.get_strict(rate_key) or 0)
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc


async def _increment_fail_count(rate_key: str) -> int:
    try:
        return await cache.increment_strict(
            rate_key, ttl=settings.ADMIN_LOGIN_WINDOW_SEC
        )
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc


async def _clear_fail_count(rate_key: str) -> None:
    try:
        await cache.delete_strict(rate_key)
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc


@router.post("/login", response_model=AdminTokenResponse)
async def login(
    data: AdminLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    _enforce_trusted_browser_origin(request)
    rate_key = _login_rate_key(request, data.username)
    account_fail_key = _account_fail_key(data.username)
    account_lock_key = _account_lock_key(data.username)

    # Per-IP + per-username rate limit (existing).
    if await _read_fail_count(rate_key) >= settings.ADMIN_LOGIN_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过于频繁，请稍后重试",
            headers={"Retry-After": str(settings.ADMIN_LOGIN_WINDOW_SEC)},
        )
    # A locked account is rejected before any credential comparison so the lock
    # actually throttles guessing; the window is bounded by ADMIN_LOGIN_WINDOW_SEC.
    account_locked = await _read_fail_count(account_lock_key) > 0
    if account_locked:
        logger.warning("Admin login rejected: account locked")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="该账号登录失败次数过多，请稍后重试",
            headers={"Retry-After": str(settings.ADMIN_LOGIN_WINDOW_SEC)},
        )

    try:
        admin_user = await authenticate_admin(db, data)
    except ValueError as exc:
        await _increment_fail_count(rate_key)
        account_fails = await _increment_fail_count(account_fail_key)
        if account_fails >= settings.ADMIN_LOGIN_MAX_FAILURES:
            await cache.set_strict(
                account_lock_key, 1, ttl=settings.ADMIN_LOGIN_WINDOW_SEC
            )
            account_locked = True
        msg = str(exc)
        if "72字节" in msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        if account_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="该账号登录失败次数过多，请稍后重试",
                headers={"Retry-After": str(settings.ADMIN_LOGIN_WINDOW_SEC)},
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)

    await _clear_fail_count(rate_key)
    await _clear_fail_count(account_fail_key)
    await _clear_fail_count(account_lock_key)

    token, refresh_token, user, role, permissions = await build_admin_login_response(
        db, admin_user
    )
    admin_user.last_login_at = utcnow()
    admin_user.last_login_ip = request.client.host if request.client else None
    await write_admin_audit(
        db,
        AdminPrincipal(admin_user, {}),
        "system.login",
        "admin_user",
        admin_user.id,
        severity="low",
        request=request,
    )
    await db.commit()
    set_refresh_cookie(response, refresh_token, request=request)
    return AdminTokenResponse(
        access_token=token, user=user, role=role, permissions=permissions
    )


@router.post("/refresh", response_model=AdminTokenResponse)
async def refresh(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    _enforce_trusted_browser_origin(request)
    refresh_token = request.cookies.get(REFRESH_COOKIE_KEY)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )
    payload = decode_admin_refresh_token(refresh_token)
    admin_user = await consume_admin_refresh_token(payload, db)
    (
        token,
        new_refresh_token,
        user,
        role,
        permissions,
    ) = await build_admin_login_response(db, admin_user)
    set_refresh_cookie(response, new_refresh_token, request=request)
    return AdminTokenResponse(
        access_token=token, user=user, role=role, permissions=permissions
    )


@router.post("/logout")
async def logout(
    request: Request, response: Response, current_admin=Depends(get_current_admin)
):
    _enforce_trusted_browser_origin(request)
    payload = current_admin.token_payload
    await blacklist_admin_token(payload["jti"], int(payload["exp"]))

    refresh_token = request.cookies.get(REFRESH_COOKIE_KEY)
    if refresh_token:
        try:
            refresh_payload = decode_admin_refresh_token(refresh_token)
            await blacklist_admin_token(
                refresh_payload["jti"], int(refresh_payload["exp"])
            )
        except HTTPException:
            pass

    delete_refresh_cookie(response, request=request)
    return {"status": "ok"}


@router.get("/me", response_model=AdminMeResponse)
async def me(
    current_admin=Depends(get_current_admin), db: AsyncSession = Depends(get_db)
):
    return await get_admin_me_response(db, current_admin.user)


@router.post("/change-password")
async def update_password(
    data: AdminChangePasswordRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    _enforce_trusted_browser_origin(request)
    try:
        await change_admin_password(
            db,
            current_admin.user,
            data,
            operator=current_admin,
            request=request,
        )
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        msg = str(exc)
        if "72字节" in msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)
    delete_refresh_cookie(response, request=request)
    return {"status": "ok"}
