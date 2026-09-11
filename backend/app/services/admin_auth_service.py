from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import (
    AdminPrincipal,
    create_admin_refresh_token,
    create_admin_token,
    get_admin_token_issued_at,
    hash_admin_password,
    set_admin_user_nbf,
    validate_admin_password_strength,
    verify_admin_password,
)
from app.models.admin import AdminUser, Permission, Role, RolePermission
from app.schemas.admin_auth import AdminChangePasswordRequest, AdminLoginRequest
from app.services.admin_audit_service import write_admin_audit


async def authenticate_admin(db: AsyncSession, data: AdminLoginRequest) -> AdminUser:
    result = await db.execute(
        select(AdminUser)
        .where(AdminUser.username == data.username)
        .where(AdminUser.is_active.is_(True))
    )
    admin_user = result.scalar_one_or_none()
    if not admin_user:
        raise ValueError("用户名或密码错误")
    try:
        password_ok = verify_admin_password(data.password, admin_user.password_hash)
    except ValueError:
        raise ValueError("密码长度不能超过72字节")
    if not password_ok:
        raise ValueError("用户名或密码错误")
    return admin_user


async def build_admin_login_response(db: AsyncSession, admin_user: AdminUser):
    result = await db.execute(select(Role).where(Role.id == admin_user.role_id))
    role = result.scalar_one()
    permissions = await get_admin_permission_names(db, admin_user.role_id)
    issued_at = await get_admin_token_issued_at(admin_user.id)
    token = create_admin_token(admin_user, issued_at=issued_at)
    refresh_token = create_admin_refresh_token(admin_user, issued_at=issued_at)
    return token, refresh_token, admin_user, role, permissions


async def get_admin_permission_names(db: AsyncSession, role_id: int) -> list[str]:
    result = await db.execute(
        select(Permission.name)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.name.asc())
    )
    return list(result.scalars().all())


async def get_admin_me_response(db: AsyncSession, admin_user: AdminUser) -> dict:
    result = await db.execute(select(Role).where(Role.id == admin_user.role_id))
    role = result.scalar_one()
    permissions = await get_admin_permission_names(db, admin_user.role_id)
    return {
        "user": admin_user,
        "role": role,
        "permissions": permissions,
    }


async def refresh_admin_access_token(
    db: AsyncSession, user_id: int
) -> tuple[str, AdminUser, Role, list[str]]:
    result = await db.execute(
        select(AdminUser).where(AdminUser.id == user_id, AdminUser.is_active.is_(True))
    )
    admin_user = result.scalar_one_or_none()
    if not admin_user:
        raise ValueError("Invalid or expired token")
    role_result = await db.execute(select(Role).where(Role.id == admin_user.role_id))
    role = role_result.scalar_one()
    permissions = await get_admin_permission_names(db, admin_user.role_id)
    return create_admin_token(admin_user), admin_user, role, permissions


async def update_role_permissions(
    db: AsyncSession,
    role_id: int,
    permission_ids: list[int],
    operator: AdminPrincipal | None = None,
    operator_id: int | None = None,
    request: Request | None = None,
) -> Role:
    role = await db.get(Role, role_id)
    if not role:
        raise ValueError("角色不存在")
    if role.name == "super_admin":
        raise PermissionError("不能修改 super_admin 权限")

    existing_permissions = await db.execute(
        select(Permission.id).where(Permission.id.in_(permission_ids))
    )
    valid_ids = set(existing_permissions.scalars().all())
    if len(valid_ids) != len(set(permission_ids)):
        raise ValueError("权限不存在")

    # Fetch old permission names for audit detail
    old_perms = await db.execute(
        select(Permission.name)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
    )
    old_permission_names = sorted(old_perms.scalars().all())

    new_perms = await db.execute(
        select(Permission.name).where(Permission.id.in_(sorted(valid_ids)))
    )
    new_permission_names = sorted(new_perms.scalars().all())

    await db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    for permission_id in sorted(valid_ids):
        db.add(
            RolePermission(
                role_id=role_id, permission_id=permission_id, granted_by=operator_id
            )
        )
    await db.flush()

    await write_admin_audit(
        db,
        operator,
        "role.update_permissions",
        "role",
        role_id,
        severity="critical",
        detail={
            "role_name": role.name,
            "role_display_name": role.display_name,
            "old_permissions": old_permission_names,
            "new_permissions": new_permission_names,
        },
        request=request,
    )
    return role


async def change_admin_password(
    db: AsyncSession,
    admin_user: AdminUser,
    data: AdminChangePasswordRequest,
    operator: AdminPrincipal | None = None,
    request: Request | None = None,
) -> None:
    try:
        old_ok = verify_admin_password(data.old_password, admin_user.password_hash)
    except ValueError:
        raise ValueError("密码长度不能超过72字节")
    if not old_ok:
        raise ValueError("用户名或密码错误")
    validate_admin_password_strength(data.new_password)
    # hash_admin_password 内部已有字节长度校验，超长会抛 ValueError
    admin_user.password_hash = hash_admin_password(data.new_password)
    invalid_after = None
    if operator is not None:
        invalid_after = int(operator.token_payload.get("iat", 0)) + 1
    await set_admin_user_nbf(admin_user.id, invalid_after)
    await write_admin_audit(
        db,
        operator,
        "admin_user.change_password",
        "admin_user",
        admin_user.id,
        severity="critical",
        detail={"username": admin_user.username},
        request=request,
    )
    await db.commit()
