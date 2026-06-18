from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.admin import AdminUser, Permission, RolePermission
from app.models.app_user_admin_binding import AppUserAdminBinding

security = HTTPBearer()


def create_token(user_id: int) -> tuple[str, int]:
    expire_dt = datetime.utcnow() + timedelta(days=settings.JWT_EXPIRE_DAYS)
    return (
        jwt.encode(
            {"sub": str(user_id), "exp": expire_dt},
            settings.APP_SECRET,
            algorithm="HS256",
        ),
        int(expire_dt.timestamp()),
    )


def decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.APP_SECRET, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user import User

    user_id = decode_token(credentials.credentials)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


def _is_local_dev_user(user) -> bool:
    return settings.APP_ENV.lower() in {"development", "local", "test"} and str(getattr(user, "openid", "")).startswith("dev_")


def require_app_permission(permission_name: str):
    async def dependency(
        current_user=Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        if _is_local_dev_user(current_user):
            return current_user

        result = await db.execute(
            select(Permission.name)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(AdminUser, AdminUser.role_id == RolePermission.role_id)
            .join(AppUserAdminBinding, AppUserAdminBinding.admin_user_id == AdminUser.id)
            .where(AppUserAdminBinding.user_id == current_user.id)
            .where(AdminUser.is_active.is_(True))
            .where(Permission.name == permission_name)
        )
        if result.scalar_one_or_none() != permission_name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )
        return current_user

    return dependency
