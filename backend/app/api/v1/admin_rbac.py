from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions, require_roles
from app.core.database import get_db
from app.models.admin import Permission, Role, RolePermission
from app.services.admin_auth_service import update_role_permissions

router = APIRouter(prefix="/api/admin/v1", tags=["admin-rbac"])


class RolePermissionsUpdateRequest(BaseModel):
    permission_ids: list[int] = Field(min_length=0)


def _serialize_permission(permission: Permission) -> dict:
    return {
        "id": permission.id,
        "name": permission.name,
        "resource": permission.resource,
        "action": permission.action,
        "category": permission.category,
        "description": permission.description,
    }


async def _ordered_permissions(db: AsyncSession) -> list[Permission]:
    result = await db.execute(
        select(Permission).order_by(
            Permission.category.asc(),
            Permission.resource.asc(),
            Permission.id.asc(),
        )
    )
    return list(result.scalars().all())


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
                "permission_ids": sorted(permission_map.get(role.id, [])),
            }
            for role in roles
        ]
    }


@router.get("/permissions")
async def list_permissions(
    _=Depends(require_permissions("permission:read")),
    db: AsyncSession = Depends(get_db),
):
    permissions = await _ordered_permissions(db)
    return {"items": [_serialize_permission(permission) for permission in permissions]}


@router.get("/permissions/by-category")
async def list_permissions_by_category(
    _=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return permissions grouped by category for the RBAC matrix UI."""
    permissions = await _ordered_permissions(db)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for permission in permissions:
        grouped[permission.category].append(_serialize_permission(permission))
    return {
        "items": dict(grouped),
        "total": len(permissions),
        "categories": len(grouped),
    }


@router.put("/roles/{role_id}/permissions")
async def replace_role_permissions(
    role_id: int,
    data: RolePermissionsUpdateRequest,
    request: Request,
    current_admin=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        role = await update_role_permissions(
            db,
            role_id,
            data.permission_ids,
            operator=current_admin,
            operator_id=current_admin.id,
            request=request,
        )
        await db.commit()
        await db.refresh(role)
        return {"status": "ok", "permission_ids": sorted(set(data.permission_ids))}
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
