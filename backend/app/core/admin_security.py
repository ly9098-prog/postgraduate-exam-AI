from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.core.database import get_db
from app.models.admin import AdminUser, Permission, Role, RolePermission

admin_security = HTTPBearer()
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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
    return password_context.hash(password)


def verify_admin_password(password: str, password_hash: str) -> bool:
    return password_context.verify(password, password_hash)


async def blacklist_admin_token(jti: str, exp: int) -> None:
    ttl = max(exp - int(datetime.utcnow().timestamp()), 1)
    await cache.set(f"admin:jwt:blacklist:{jti}", 1, ttl=ttl)


async def set_admin_user_nbf(user_id: int, timestamp: int | None = None) -> None:
    await cache.set(f"admin:user:nbf:{user_id}", timestamp or int(datetime.utcnow().timestamp()), ttl=60 * 60 * 24 * 30)


def create_admin_token(admin_user: AdminUser) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": str(admin_user.id),
        "type": "admin",
        "roleId": admin_user.role_id,
        "jti": uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=2)).timestamp()),
    }
    return jwt.encode(payload, settings.APP_SECRET, algorithm="HS256")


def create_admin_refresh_token(admin_user: AdminUser) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": str(admin_user.id),
        "type": "admin_refresh",
        "roleId": admin_user.role_id,
        "jti": uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=7)).timestamp()),
    }
    return jwt.encode(payload, settings.APP_SECRET, algorithm="HS256")


def decode_admin_refresh_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.APP_SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if payload.get("type") != "admin_refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return payload


def decode_admin_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.APP_SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if payload.get("type") != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return payload


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
    if jti and await cache.get(f"admin:jwt:blacklist:{jti}"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user_id = int(payload["sub"])
    token_iat = int(payload.get("iat", 0))
    user_nbf = await cache.get(f"admin:user:nbf:{user_id}")
    if user_nbf and token_iat < int(user_nbf):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
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
