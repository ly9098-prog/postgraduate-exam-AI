from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.admin_security import AdminPrincipal, hash_admin_password, set_admin_user_nbf
from app.models.admin import AdminUser, Role
from app.schemas.admin_users import (
    AdminUserCreateRequest,
    AdminUserPatchRequest,
    AdminUserResetPasswordRequest,
)
from app.services.admin_audit_service import write_admin_audit


async def list_admin_users(
    db: AsyncSession,
    page: int,
    page_size: int,
    keyword: str | None = None,
    is_active: bool | None = None,
    role_id: int | None = None,
) -> tuple[list[AdminUser], int]:
    conditions = []
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            or_(
                AdminUser.username.ilike(pattern),
                AdminUser.display_name.ilike(pattern),
                AdminUser.email.ilike(pattern),
            )
        )
    if is_active is not None:
        conditions.append(AdminUser.is_active.is_(is_active))
    if role_id is not None:
        conditions.append(AdminUser.role_id == role_id)

    query = select(AdminUser).options(selectinload(AdminUser.role))
    count_query = select(func.count()).select_from(AdminUser)
    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = await db.scalar(count_query)
    result = await db.execute(
        query.order_by(AdminUser.created_at.desc(), AdminUser.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_admin_user_detail(db: AsyncSession, admin_user_id: int) -> AdminUser:
    result = await db.execute(
        select(AdminUser)
        .options(selectinload(AdminUser.role))
        .where(AdminUser.id == admin_user_id)
    )
    admin_user = result.scalar_one_or_none()
    if not admin_user:
        raise ValueError("管理员不存在")
    return admin_user


async def _get_role(db: AsyncSession, role_id: int) -> Role:
    role = await db.get(Role, role_id)
    if not role:
        raise ValueError("角色不存在")
    return role


async def _ensure_not_super_admin(db: AsyncSession, admin_user: AdminUser) -> None:
    role = admin_user.role or await _get_role(db, admin_user.role_id)
    if role.name == "super_admin":
        raise PermissionError("禁止操作超级管理员")


async def _ensure_assignable_role(db: AsyncSession, role_id: int) -> Role:
    role = await _get_role(db, role_id)
    if role.name == "super_admin":
        raise PermissionError("禁止分配超级管理员角色")
    return role


async def create_admin_user(
    db: AsyncSession,
    data: AdminUserCreateRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> AdminUser:
    await _ensure_assignable_role(db, data.role_id)
    admin_user = AdminUser(
        username=data.username,
        password_hash=hash_admin_password(data.password),
        display_name=data.display_name,
        email=data.email,
        role_id=data.role_id,
        is_active=data.is_active,
    )
    db.add(admin_user)
    await db.flush()
    await db.refresh(admin_user, ["role"])
    await write_admin_audit(
        db,
        operator,
        "admin_user.create",
        "admin_user",
        admin_user.id,
        severity="critical",
        detail={
            "after": {
                "username": admin_user.username,
                "display_name": admin_user.display_name,
                "email": admin_user.email,
                "role_id": admin_user.role_id,
                "is_active": admin_user.is_active,
            }
        },
        request=request,
    )
    return admin_user


async def update_admin_user(
    db: AsyncSession,
    admin_user_id: int,
    data: AdminUserPatchRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> AdminUser:
    admin_user = await get_admin_user_detail(db, admin_user_id)
    await _ensure_not_super_admin(db, admin_user)
    update_data = data.model_dump(exclude_unset=True)
    if "role_id" in update_data and update_data["role_id"] != admin_user.role_id:
        if admin_user.id == operator.id:
            raise ValueError("禁止修改自己的角色")
        await _ensure_assignable_role(db, update_data["role_id"])

    before = {
        "display_name": admin_user.display_name,
        "email": admin_user.email,
        "is_active": admin_user.is_active,
        "role_id": admin_user.role_id,
    }
    for field in ("display_name", "email", "is_active", "role_id"):
        if field in update_data:
            setattr(admin_user, field, update_data[field])
    after = {
        "display_name": admin_user.display_name,
        "email": admin_user.email,
        "is_active": admin_user.is_active,
        "role_id": admin_user.role_id,
    }

    if before["is_active"] and not after["is_active"]:
        await set_admin_user_nbf(admin_user.id)

    await db.flush()
    await db.refresh(admin_user, ["role"])
    await write_admin_audit(
        db,
        operator,
        "admin_user.update",
        "admin_user",
        admin_user.id,
        severity="critical",
        detail={"before": before, "after": after},
        request=request,
    )
    return admin_user


async def deactivate_admin_user(
    db: AsyncSession,
    admin_user_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> AdminUser:
    admin_user = await get_admin_user_detail(db, admin_user_id)
    if admin_user.id == operator.id:
        raise ValueError("禁止删除自己")
    await _ensure_not_super_admin(db, admin_user)
    before = {"is_active": admin_user.is_active}
    admin_user.is_active = False
    await set_admin_user_nbf(admin_user.id)
    await write_admin_audit(
        db,
        operator,
        "admin_user.delete",
        "admin_user",
        admin_user.id,
        severity="critical",
        detail={"before": before, "after": {"is_active": admin_user.is_active}},
        request=request,
    )
    return admin_user


async def force_logout_admin_user(
    db: AsyncSession,
    admin_user_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> None:
    admin_user = await get_admin_user_detail(db, admin_user_id)
    if admin_user.id == operator.id:
        raise ValueError("禁止强制登出自己")
    await _ensure_not_super_admin(db, admin_user)
    await set_admin_user_nbf(admin_user.id)
    await write_admin_audit(
        db,
        operator,
        "admin_user.force_logout",
        "admin_user",
        admin_user.id,
        severity="critical",
        detail={"username": admin_user.username},
        request=request,
    )


async def reset_admin_user_password(
    db: AsyncSession,
    admin_user_id: int,
    data: AdminUserResetPasswordRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> None:
    admin_user = await get_admin_user_detail(db, admin_user_id)
    if admin_user.id == operator.id:
        raise ValueError("禁止重置自己的密码")
    await _ensure_not_super_admin(db, admin_user)
    admin_user.password_hash = hash_admin_password(data.new_password)
    await set_admin_user_nbf(admin_user.id)
    await write_admin_audit(
        db,
        operator,
        "admin_user.reset_password",
        "admin_user",
        admin_user.id,
        severity="critical",
        detail={"username": admin_user.username},
        request=request,
    )
