from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.admin_users import AdminUserCreateRequest, AdminUserDetail, AdminUserListItem, AdminUserPatchRequest, AdminUserResetPasswordRequest
from app.schemas.common import paginated_response
from app.services.admin_user_service import (
    create_admin_user,
    deactivate_admin_user,
    force_logout_admin_user,
    get_admin_user_detail,
    list_admin_users,
    reset_admin_user_password,
    update_admin_user,
)

router = APIRouter(prefix="/api/admin/v1/admin-users", tags=["admin-users"])


def _status_for_error(exc: Exception) -> int:
    if isinstance(exc, PermissionError):
        return status.HTTP_403_FORBIDDEN
    return status.HTTP_422_UNPROCESSABLE_ENTITY


@router.get("")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    is_active: bool | None = None,
    role_id: int | None = None,
    _=Depends(require_permissions("admin-user:read")),
    db: AsyncSession = Depends(get_db),
):
    users, total = await list_admin_users(db, page, page_size, keyword, is_active, role_id)
    return paginated_response([AdminUserListItem.model_validate(user) for user in users], total, page, page_size)


@router.get("/{admin_user_id}", response_model=AdminUserDetail)
async def get_user(
    admin_user_id: int,
    _=Depends(require_permissions("admin-user:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_admin_user_detail(db, admin_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("", response_model=AdminUserDetail, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: AdminUserCreateRequest,
    request: Request,
    current_admin=Depends(require_permissions("admin-user:create")),
    db: AsyncSession = Depends(get_db),
):
    try:
        admin_user = await create_admin_user(db, data, current_admin, request)
        await db.commit()
        await db.refresh(admin_user)
        return await get_admin_user_detail(db, admin_user.id)
    except (ValueError, PermissionError) as exc:
        await db.rollback()
        raise HTTPException(status_code=_status_for_error(exc), detail=str(exc))


@router.patch("/{admin_user_id}", response_model=AdminUserDetail)
async def patch_user(
    admin_user_id: int,
    data: AdminUserPatchRequest,
    request: Request,
    current_admin=Depends(require_permissions("admin-user:update")),
    db: AsyncSession = Depends(get_db),
):
    try:
        admin_user = await update_admin_user(db, admin_user_id, data, current_admin, request)
        await db.commit()
        return await get_admin_user_detail(db, admin_user.id)
    except ValueError as exc:
        await db.rollback()
        if str(exc) == "管理员不存在":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.delete("/{admin_user_id}")
async def delete_user(
    admin_user_id: int,
    request: Request,
    current_admin=Depends(require_permissions("admin-user:delete")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await deactivate_admin_user(db, admin_user_id, current_admin, request)
        await db.commit()
        return {"status": "ok"}
    except ValueError as exc:
        await db.rollback()
        if str(exc) == "管理员不存在":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/{admin_user_id}/force-logout")
async def force_logout_user(
    admin_user_id: int,
    request: Request,
    current_admin=Depends(require_permissions("admin-user:force-logout")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await force_logout_admin_user(db, admin_user_id, current_admin, request)
        await db.commit()
        return {"status": "ok"}
    except ValueError as exc:
        await db.rollback()
        if str(exc) == "管理员不存在":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/{admin_user_id}/reset-password")
async def reset_password(
    admin_user_id: int,
    data: AdminUserResetPasswordRequest,
    request: Request,
    current_admin=Depends(require_permissions("admin-user:reset-password")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await reset_admin_user_password(db, admin_user_id, data, current_admin, request)
        await db.commit()
        return {"status": "ok"}
    except ValueError as exc:
        await db.rollback()
        if str(exc) == "管理员不存在":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
