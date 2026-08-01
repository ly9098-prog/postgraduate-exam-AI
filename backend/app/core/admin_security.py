from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheUnavailableError, cache
from app.core.config import settings
from app.core.database import get_db
from app.core.time_utils import utcnow
from app.models.admin import AdminUser, Permission, Role, RolePermission

admin_security = HTTPBearer()
# bcrypt rounds=12/prefix=2b 与旧 passlib 默认一致，存量 $2b$ 哈希可直接验证
password_context = PasswordHash((BcryptHasher(),))

# ── Refresh Token Cookie Config ──

REFRESH_COOKIE_KEY = "admin_refresh_token"
_REFRESH_COOKIE_PATH = "/api/admin/v1/auth"


def _resolve_refresh_cookie_secure(request: Request | None = None) -> bool:
    """Determine whether the refresh cookie should carry the ``Secure`` flag.

    Priority:
        1. ``request.url.scheme == "https"`` (direct HTTPS connection).
        2. ``X-Forwarded-Proto: https`` header set by nginx reverse proxy.
        3. ``settings.APP_ENV == "production"`` — production always uses HTTPS.
    """
    # Production must never emit a non-Secure refresh cookie, even when a
    # reverse proxy forgets to forward the original scheme.
    if settings.APP_ENV.lower() == "production":
        return True
    if request is not None:
        if request.url.scheme == "https":
            return True
        forwarded = request.headers.get("x-forwarded-proto", "")
        return forwarded.lower() == "https"
    return False


def set_refresh_cookie(
    response: Response,
    value: str,
    request: Request | None = None,
    *,
    secure: bool | None = None,
) -> None:
    """Set the admin refresh token cookie with consistent attributes.

    All call sites (login, refresh, logout) must use this helper so
    every Set-Cookie carries the same ``HttpOnly`` / ``SameSite`` /
    ``Secure`` / ``Path`` values.
    """
    if secure is None:
        secure = _resolve_refresh_cookie_secure(request)
    response.set_cookie(
        key=REFRESH_COOKIE_KEY,
        value=value,
        httponly=True,
        samesite="none" if secure else "lax",
        secure=secure,
        path=_REFRESH_COOKIE_PATH,
        max_age=7 * 24 * 60 * 60,
    )


def delete_refresh_cookie(
    response: Response,
    request: Request | None = None,
    *,
    secure: bool | None = None,
) -> None:
    """Delete the admin refresh token cookie.

    Uses ``response.set_cookie`` with ``max_age=0`` instead of Starlette's
    ``delete_cookie`` to ensure the deletion cookie carries the same
    ``HttpOnly`` / ``SameSite`` / ``Secure`` flags as the original.
    """
    if secure is None:
        secure = _resolve_refresh_cookie_secure(request)
    response.set_cookie(
        key=REFRESH_COOKIE_KEY,
        value="",
        httponly=True,
        samesite="none" if secure else "lax",
        secure=secure,
        path=_REFRESH_COOKIE_PATH,
        max_age=0,
    )

# bcrypt 协议硬限制：超过 72 bytes 会抛异常或被截断
BCRYPT_MAX_BYTES = 72

# 管理员密码强度策略：长度 + 字符类别组合（轻量加固，无 2FA 依赖）
ADMIN_PASSWORD_MIN_LENGTH = 12


class PasswordPolicyError(ValueError):
    """Raised when an admin password does not meet the strength policy."""


def validate_admin_password_strength(password: str) -> None:
    """Enforce the admin password policy; raises ``PasswordPolicyError``."""
    if len(password) < ADMIN_PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(f"密码长度至少需要 {ADMIN_PASSWORD_MIN_LENGTH} 位")
    if not any(ch.isupper() for ch in password):
        raise PasswordPolicyError("密码需包含大写字母")
    if not any(ch.islower() for ch in password):
        raise PasswordPolicyError("密码需包含小写字母")
    if not any(ch.isdigit() for ch in password):
        raise PasswordPolicyError("密码需包含数字")


class AdminPrincipal:
    def __init__(self, user: AdminUser, token_payload: dict[str, Any]):
        self.user = user
        self.token_payload = token_payload

    @property
    def id(self) -> int:
        return self.user.id

    @property
    def role_id(self) -> int:
        return self.user.role_id

    @property
    def username(self) -> str:
        return self.user.username


def hash_admin_password(password: str) -> str:
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"密码长度不能超过 {BCRYPT_MAX_BYTES} 字节")
    return password_context.hash(password)


def verify_admin_password(password: str, password_hash: str) -> bool:
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"密码长度不能超过 {BCRYPT_MAX_BYTES} 字节")
    try:
        return password_context.verify(password, password_hash)
    except (UnknownHashError, ValueError):
        # 未知/畸形哈希：保持 passlib 时代"返回 False"的契约，不抛 500
        return False


async def blacklist_admin_token(jti: str, exp: int) -> None:
    ttl = max(exp - int(utcnow().timestamp()), 1)
    try:
        await cache.set_strict(f"admin:jwt:blacklist:{jti}", 1, ttl=ttl)
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc


async def set_admin_user_nbf(user_id: int, timestamp: int | None = None) -> None:
    try:
        await cache.set_strict(
            f"admin:user:nbf:{user_id}",
            timestamp or (int(utcnow().timestamp()) + 1),
            ttl=60 * 60 * 24 * 30,
        )
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc


def create_admin_token(admin_user: AdminUser, *, issued_at: int | None = None) -> str:
    current = int(datetime.now(UTC).timestamp())
    now = datetime.fromtimestamp(max(current, issued_at or current), tz=UTC)
    payload = {
        "sub": str(admin_user.id),
        "type": "admin",
        "iss": settings.JWT_ISSUER,
        "aud": settings.ADMIN_JWT_AUDIENCE,
        "roleId": admin_user.role_id,
        "jti": uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=2)).timestamp()),
    }
    return jwt.encode(payload, settings.APP_SECRET, algorithm="HS256")


def create_admin_refresh_token(admin_user: AdminUser, *, issued_at: int | None = None) -> str:
    current = int(datetime.now(UTC).timestamp())
    now = datetime.fromtimestamp(max(current, issued_at or current), tz=UTC)
    payload = {
        "sub": str(admin_user.id),
        "type": "admin_refresh",
        "iss": settings.JWT_ISSUER,
        "aud": settings.ADMIN_JWT_AUDIENCE,
        "roleId": admin_user.role_id,
        "jti": uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=7)).timestamp()),
    }
    return jwt.encode(payload, settings.APP_SECRET, algorithm="HS256")


def _decode_admin_jwt(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.APP_SECRET,
            algorithms=["HS256"],
            audience=settings.ADMIN_JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={"require": ["sub", "type", "iss", "aud", "jti", "iat", "exp"]},
            leeway=2,
        )
        if payload.get("type") != expected_type:
            raise jwt.InvalidTokenError("wrong token type")
        int(payload["sub"])
        int(payload["iat"])
        int(payload["exp"])
        return payload
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


async def get_admin_token_issued_at(user_id: int) -> int | None:
    """Return the minimum safe iat for newly issued admin tokens."""
    try:
        user_nbf = await cache.get_strict(f"admin:user:nbf:{user_id}")
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc
    return int(user_nbf) if user_nbf else None


def decode_admin_refresh_token(token: str) -> dict[str, Any]:
    return _decode_admin_jwt(token, "admin_refresh")


def decode_admin_token(token: str) -> dict[str, Any]:
    return _decode_admin_jwt(token, "admin")


async def consume_admin_refresh_token(
    payload: dict[str, Any],
    db: AsyncSession,
) -> AdminUser:
    """Validate and atomically consume a refresh token for one-time rotation."""
    user_id = int(payload["sub"])
    token_iat = int(payload["iat"])
    token_exp = int(payload["exp"])
    jti = str(payload["jti"])

    try:
        is_blacklisted = await cache.get_strict(f"admin:jwt:blacklist:{jti}")
        user_nbf = await cache.get_strict(f"admin:user:nbf:{user_id}")
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc
    if is_blacklisted:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    if user_nbf and token_iat < int(user_nbf):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    ttl = max(token_exp - int(utcnow().timestamp()), 1)
    try:
        consumed = await cache.acquire_lock_strict(
            f"admin:refresh:used:{jti}",
            uuid4().hex,
            ttl=ttl,
        )
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc
    if not consumed:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    result = await db.execute(
        select(AdminUser).where(AdminUser.id == user_id, AdminUser.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user


async def _get_permission_names(db: AsyncSession, role_id: int) -> set[str]:
    result = await db.execute(
        select(Permission.name)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
    )
    return set(result.scalars().all())


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(admin_security),
    db: AsyncSession = Depends(get_db),
) -> AdminPrincipal:
    payload = decode_admin_token(credentials.credentials)
    jti = payload.get("jti")
    user_id = int(payload["sub"])
    token_iat = int(payload.get("iat", 0))
    try:
        is_blacklisted = bool(
            jti and await cache.get_strict(f"admin:jwt:blacklist:{jti}")
        )
        user_nbf = await cache.get_strict(f"admin:user:nbf:{user_id}")
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc
    if is_blacklisted:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if user_nbf and token_iat < int(user_nbf):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    # Bind admin identity to log context for trace correlation
    try:
        from app.core.log_context import bind_log_context
        bind_log_context(admin_id=str(user.id))
    except Exception:
        pass

    return AdminPrincipal(user, payload)


def require_roles(*role_names: str):
    async def dependency(
        current_admin: AdminPrincipal = Depends(get_current_admin),
        db: AsyncSession = Depends(get_db),
    ) -> AdminPrincipal:
        result = await db.execute(select(Role.name).where(Role.id == current_admin.role_id))
        role_name = result.scalar_one_or_none()
        if role_name not in role_names:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return current_admin

    return dependency


def require_permissions(*permission_names: str):
    async def dependency(
        current_admin: AdminPrincipal = Depends(get_current_admin),
        db: AsyncSession = Depends(get_db),
    ) -> AdminPrincipal:
        granted = await _get_permission_names(db, current_admin.role_id)
        if not set(permission_names).issubset(granted):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return current_admin

    return dependency
