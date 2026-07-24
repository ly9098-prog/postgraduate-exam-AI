from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions, require_roles
from app.core.database import get_db
from app.schemas.admin_app_users import (
    AdminAppUserBanRequest,
    AdminAppUserBindAdminRequest,
    AdminAppUserBindAdminResponse,
    AdminAppUserDetail,
    AdminAppUserListItem,
    AdminAppUserUpdateRequest,
)
from app.schemas.common import paginated_response
from app.services.admin_app_user_service import (
    ban_app_user,
    bind_app_user_admin,
    get_app_user_detail,
    list_app_users,
    unban_app_user,
    unbind_app_user_admin,
    update_app_user,
)

router = APIRouter(prefix="/api/admin/v1/app-users", tags=["admin-app-users"])


@router.get("")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    is_banned: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    _=Depends(require_permissions("app-user:read")),
    db: AsyncSession = Depends(get_db),
):
    users, total = await list_app_users(db, page, page_size, keyword, is_banned, created_from, created_to)
    return paginated_response([AdminAppUserListItem.model_validate(user) for user in users], total, page, page_size)


@router.get("/{user_id}", response_model=AdminAppUserDetail)
async def get_user(
    user_id: int,
    _=Depends(require_permissions("app-user:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_app_user_detail(db, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/{user_id}", response_model=AdminAppUserListItem)
async def patch_user(
    user_id: int,
    data: AdminAppUserUpdateRequest,
    request: Request,
    current_admin=Depends(require_permissions("app-user:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        user = await update_app_user(db, user_id, data, current_admin, request)
        await db.commit()
        await db.refresh(user)
        return user
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/{user_id}/admin-binding", response_model=AdminAppUserBindAdminResponse)
async def bind_admin(
    user_id: int,
    data: AdminAppUserBindAdminRequest,
    request: Request,
    current_admin=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        binding = await bind_app_user_admin(db, user_id, data.admin_user_id, current_admin, request)
        await db.commit()
        await db.refresh(binding)
        return binding
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.delete("/{user_id}/admin-binding")
async def unbind_admin(
    user_id: int,
    request: Request,
    current_admin=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await unbind_app_user_admin(db, user_id, current_admin, request)
        await db.commit()
        return {"status": "ok"}
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/{user_id}/ban", response_model=AdminAppUserListItem)
async def ban_user(
    user_id: int,
    data: AdminAppUserBanRequest,
    request: Request,
    current_admin=Depends(require_permissions("app-user:ban")),
    db: AsyncSession = Depends(get_db),
):
    try:
        user = await ban_app_user(db, user_id, data, current_admin, request)
        await db.commit()
        await db.refresh(user)
        return user
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/{user_id}/unban", response_model=AdminAppUserListItem)
async def unban_user(
    user_id: int,
    request: Request,
    current_admin=Depends(require_permissions("app-user:ban")),
    db: AsyncSession = Depends(get_db),
):
    try:
        user = await unban_app_user(db, user_id, current_admin, request)
        await db.commit()
        await db.refresh(user)
        return user
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
