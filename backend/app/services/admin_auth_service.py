from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import create_admin_token, hash_admin_password, set_admin_user_nbf, verify_admin_password
from app.models.admin import AdminUser, Role
from app.schemas.admin_auth import AdminChangePasswordRequest, AdminLoginRequest


async def authenticate_admin(db: AsyncSession, data: AdminLoginRequest) -> AdminUser:
    result = await db.execute(
        select(AdminUser)
        .where(AdminUser.username == data.username)
        .where(AdminUser.is_active.is_(True))
    )
    admin_user = result.scalar_one_or_none()
    if not admin_user:
        raise ValueError("用户名或密码错误")
    if not verify_admin_password(data.password, admin_user.password_hash):
        raise ValueError("用户名或密码错误")
    return admin_user


async def build_admin_login_response(db: AsyncSession, admin_user: AdminUser):
    result = await db.execute(select(Role).where(Role.id == admin_user.role_id))
    role = result.scalar_one()
    token = create_admin_token(admin_user)
    return token, admin_user, role


async def change_admin_password(
    db: AsyncSession,
    admin_user: AdminUser,
    data: AdminChangePasswordRequest,
) -> None:
    if not verify_admin_password(data.old_password, admin_user.password_hash):
        raise ValueError("用户名或密码错误")
    admin_user.password_hash = hash_admin_password(data.new_password)
    await set_admin_user_nbf(admin_user.id)
    await db.commit()
