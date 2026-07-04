from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.models.admin import Permission, Role, RolePermission
from app.services.admin_auth_service import update_role_permissions

router = APIRouter(prefix="/api/admin/v1", tags=["admin-rbac"])


class RolePermissionsUpdateRequest(BaseModel):
    permission_ids: list[int] = Field(min_length=0)


@router.get("/roles")
async def list_roles(
    _=Depends(require_permissions("role:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Role).order_by(Role.id.asc()))
    roles = result.scalars().all()
    permission_result = await db.execute(select(RolePermission.role_id, RolePermission.permission_id))
    permission_map: dict[int, list[int]] = {}
    for role_id, permission_id in permission_result.all():
        permission_map.setdefault(role_id, []).append(permission_id)
    return {
        "items": [
            {
                "id": role.id,
                "name": role.name,
                "display_name": role.display_name,
                "description": role.description,
                "is_system": role.is_system,
                "permission_ids": permission_map.get(role.id, []),
            }
            for role in roles
        ]
    }


@router.get("/permissions")
async def list_permissions(
    _=Depends(require_permissions("permission:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Permission).order_by(Permission.category.asc(), Permission.id.asc()))
    permissions = result.scalars().all()
    return {"items": [{"id": permission.id, "name": permission.name, "resource": permission.resource, "action": permission.action, "category": permission.category, "description": permission.description} for permission in permissions]}


@router.put("/roles/{role_id}/permissions")
async def replace_role_permissions(
    role_id: int,
    data: RolePermissionsUpdateRequest,
    request: Request,
    current_admin=Depends(require_permissions("role:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        role = await update_role_permissions(db, role_id, data.permission_ids, operator=current_admin, operator_id=current_admin.id, request=request)
        await db.commit()
        await db.refresh(role)
        return {"status": "ok"}
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
