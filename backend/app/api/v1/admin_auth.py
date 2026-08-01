
import hashlib
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import (
    REFRESH_COOKIE_KEY,
    blacklist_admin_token,
    consume_admin_2fa_pending_token,
    consume_admin_refresh_token,
    create_admin_2fa_pending_token,
    decode_admin_2fa_pending_token,
    decode_admin_refresh_token,
    delete_refresh_cookie,
    get_admin_token_issued_at,
    get_current_admin,
    set_refresh_cookie,
)
from app.core.cache import CacheUnavailableError, cache
from app.core.config import settings
from app.core.database import get_db
from app.core.time_utils import utcnow
from app.models.admin import AdminUser
from app.schemas.admin_auth import (
    AdminChangePasswordRequest,
    AdminLoginRequest,
    AdminLoginResponse,
    AdminMeResponse,
    AdminTokenResponse,
    TwoFactorConfirmRequest,
    TwoFactorConfirmResponse,
    TwoFactorDisableRequest,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
)
from app.services.admin_audit_service import write_admin_audit
from app.services.admin_auth_service import (
    authenticate_admin,
    build_admin_login_response,
    change_admin_password,
    get_admin_me_response,
)
from app.services.totp_service import (
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_code,
    otpauth_uri,
    verify_backup_code,
    verify_totp,
)

router = APIRouter(prefix="/api/admin/v1/auth", tags=["admin-auth"])


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
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid request origin")
        return
    allowed = {
        normalized
        for value in [*settings.CORS_ORIGINS, settings.PUBLIC_BASE_URL]
        if (normalized := _normalized_origin(value)) is not None
    }
    if _normalized_origin(origin) not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid request origin")


def _login_rate_key(request: Request, username: str) -> str:
    client_ip = request.client.host if request.client else "unknown"
    identity = f"{client_ip}|{username.strip().lower()}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"admin:login:fail:{digest}"


def _2fa_rate_key(request: Request, user_id: int) -> str:
    client_ip = request.client.host if request.client else "unknown"
    identity = f"{user_id}|{client_ip}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"admin:2fa:fail:{digest}"


async def _read_fail_count(rate_key: str) -> int:
    try:
        return int(await cache.get_strict(rate_key) or 0)
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc


async def _increment_fail_count(rate_key: str) -> None:
    try:
        await cache.increment_strict(rate_key, ttl=settings.ADMIN_LOGIN_WINDOW_SEC)
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


@router.post("/login", response_model=AdminLoginResponse)
async def login(data: AdminLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    _enforce_trusted_browser_origin(request)
    rate_key = _login_rate_key(request, data.username)
    failures = await _read_fail_count(rate_key)
    if failures >= settings.ADMIN_LOGIN_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过于频繁，请稍后重试",
            headers={"Retry-After": str(settings.ADMIN_LOGIN_WINDOW_SEC)},
        )

    try:
        admin_user = await authenticate_admin(db, data)
    except ValueError as exc:
        await _increment_fail_count(rate_key)
        msg = str(exc)
        if "72字节" in msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)

    # Password accepted — reset the failure counter regardless of the 2FA step.
    await _clear_fail_count(rate_key)

    token, refresh_token, user, role, permissions = await build_admin_login_response(db, admin_user)

    if admin_user.totp_enabled:
        # Step 1 of 2 complete. Issue a short-lived pending token; the session
        # is established only after /2fa/verify succeeds.
        pending_token = create_admin_2fa_pending_token(admin_user)
        return AdminLoginResponse(
            user=user,
            role=role,
            permissions=permissions,
            two_factor_required=True,
            pending_token=pending_token,
        )

    admin_user.last_login_at = utcnow()
    admin_user.last_login_ip = request.client.host if request.client else None
    await db.commit()
    set_refresh_cookie(response, refresh_token, request=request)
    return AdminLoginResponse(access_token=token, user=user, role=role, permissions=permissions)


@router.post("/2fa/verify", response_model=AdminLoginResponse)
async def verify_2fa(data: TwoFactorVerifyRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Complete step 2 of login: validate a TOTP code or one-time backup code."""
    _enforce_trusted_browser_origin(request)
    payload = decode_admin_2fa_pending_token(data.pending_token)
    user_id = int(payload["sub"])
    token_iat = int(payload["iat"])
    rate_key = _2fa_rate_key(request, user_id)

    if await _read_fail_count(rate_key) >= settings.ADMIN_LOGIN_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="验证尝试过于频繁，请稍后重试",
            headers={"Retry-After": str(settings.ADMIN_LOGIN_WINDOW_SEC)},
        )

    await consume_admin_2fa_pending_token(payload)

    # Re-fetch the user; account may have been disabled or 2FA revoked since step 1.
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id, AdminUser.is_active.is_(True)))
    admin_user = result.scalar_one_or_none()
    if not admin_user or not admin_user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    nbf = await get_admin_token_issued_at(admin_user.id)
    if nbf and token_iat < int(nbf):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    backup_codes: list[str] = []
    if admin_user.totp_backup_codes:
        try:
            backup_codes = json.loads(admin_user.totp_backup_codes)
        except (ValueError, TypeError):
            backup_codes = []

    matched = False
    remaining = list(backup_codes)
    if admin_user.totp_secret and verify_totp(admin_user.totp_secret, data.code):
        matched = True
    else:
        matched, remaining = verify_backup_code(data.code, backup_codes)

    if not matched:
        await _increment_fail_count(rate_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="验证码错误")

    # Consume a used backup code so it is single-use.
    if backup_codes and remaining != backup_codes:
        admin_user.totp_backup_codes = json.dumps(remaining) if remaining else None

    token, refresh_token, user, role, permissions = await build_admin_login_response(db, admin_user)
    admin_user.last_login_at = utcnow()
    admin_user.last_login_ip = request.client.host if request.client else None
    await db.commit()
    await _clear_fail_count(rate_key)
    set_refresh_cookie(response, refresh_token, request=request)
    return AdminLoginResponse(access_token=token, user=user, role=role, permissions=permissions)


@router.get("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(request: Request, db: AsyncSession = Depends(get_db), current_admin=Depends(get_current_admin)):
    """Generate a new TOTP secret for enrollment (not yet enabled)."""
    _enforce_trusted_browser_origin(request)
    user = await db.get(AdminUser, current_admin.id)
    if not user or user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="2FA 已启用，请先关闭后再重新绑定")
    secret = generate_totp_secret()
    user.totp_secret = secret
    await db.commit()
    return TwoFactorSetupResponse(
        secret=secret,
        otpauth_uri=otpauth_uri(secret, user.username),
        issuer="MemoGrad Admin",
        username=user.username,
        already_enabled=False,
    )


@router.post("/2fa/confirm", response_model=TwoFactorConfirmResponse)
async def confirm_2fa(
    data: TwoFactorConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    """Confirm enrollment with a code from the pending secret; enables 2FA."""
    _enforce_trusted_browser_origin(request)
    user = await db.get(AdminUser, current_admin.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="2FA 已启用")
    if not user.totp_secret:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请先初始化 2FA 绑定")
    if not verify_totp(user.totp_secret, data.code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="验证码错误")

    backup_codes = generate_backup_codes()
    user.totp_enabled = True
    user.totp_confirmed_at = utcnow()
    user.totp_backup_codes = json.dumps([hash_backup_code(c) for c in backup_codes])
    await write_admin_audit(
        db, current_admin, "admin_user.2fa_enable", "admin_user", user.id,
        severity="critical", detail={"username": user.username}, request=request,
    )
    await db.commit()
    return TwoFactorConfirmResponse(backup_codes=backup_codes)


@router.post("/2fa/disable")
async def disable_2fa(
    data: TwoFactorDisableRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    """Disable 2FA — requires a valid TOTP code or a backup code."""
    _enforce_trusted_browser_origin(request)
    user = await db.get(AdminUser, current_admin.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if not user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="2FA 未启用")

    backup_codes: list[str] = []
    if user.totp_backup_codes:
        try:
            backup_codes = json.loads(user.totp_backup_codes)
        except (ValueError, TypeError):
            backup_codes = []

    matched = False
    if user.totp_secret and verify_totp(user.totp_secret, data.code):
        matched = True
    else:
        matched, _ = verify_backup_code(data.code, backup_codes)
    if not matched:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="验证码错误")

    user.totp_enabled = False
    user.totp_secret = None
    user.totp_confirmed_at = None
    user.totp_backup_codes = None
    await write_admin_audit(
        db, current_admin, "admin_user.2fa_disable", "admin_user", user.id,
        severity="critical", detail={"username": user.username}, request=request,
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/refresh", response_model=AdminTokenResponse)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    _enforce_trusted_browser_origin(request)
    refresh_token = request.cookies.get(REFRESH_COOKIE_KEY)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    payload = decode_admin_refresh_token(refresh_token)
    admin_user = await consume_admin_refresh_token(payload, db)
    token, new_refresh_token, user, role, permissions = await build_admin_login_response(db, admin_user)
    set_refresh_cookie(response, new_refresh_token, request=request)
    return AdminTokenResponse(access_token=token, user=user, role=role, permissions=permissions)


@router.post("/logout")
async def logout(request: Request, response: Response, current_admin=Depends(get_current_admin)):
    _enforce_trusted_browser_origin(request)
    payload = current_admin.token_payload
    await blacklist_admin_token(payload["jti"], int(payload["exp"]))

    refresh_token = request.cookies.get(REFRESH_COOKIE_KEY)
    if refresh_token:
        try:
            refresh_payload = decode_admin_refresh_token(refresh_token)
            await blacklist_admin_token(refresh_payload["jti"], int(refresh_payload["exp"]))
        except HTTPException:
            pass

    delete_refresh_cookie(response, request=request)
    return {"status": "ok"}


@router.get("/me", response_model=AdminMeResponse)
async def me(current_admin=Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
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
            db, current_admin.user, data, operator=current_admin, request=request,
        )
    except ValueError as exc:
        msg = str(exc)
        if "72字节" in msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)
    delete_refresh_cookie(response, request=request)
    return {"status": "ok"}
