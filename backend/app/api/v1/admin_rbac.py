from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.models.admin import Permission, Role

router = APIRouter(prefix="/api/admin/v1", tags=["admin-rbac"])


@router.get("/roles")
async def list_roles(
    _=Depends(require_permissions("role:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Role).order_by(Role.id.asc()))
    roles = result.scalars().all()
    return {"items": [{"id": role.id, "name": role.name, "display_name": role.display_name, "description": role.description, "is_system": role.is_system} for role in roles]}


@router.get("/permissions")
async def list_permissions(
    _=Depends(require_permissions("permission:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Permission).order_by(Permission.category.asc(), Permission.id.asc()))
    permissions = result.scalars().all()
    return {"items": [{"id": permission.id, "name": permission.name, "resource": permission.resource, "action": permission.action, "category": permission.category, "description": permission.description} for permission in permissions]}


@router.get("/permissions/by-category")
async def list_permissions_by_category(
    _=Depends(require_permissions("permission:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Permission).order_by(Permission.category.asc(), Permission.name.asc()))
    grouped: dict[str, list[dict]] = {}
    for permission in result.scalars().all():
        grouped.setdefault(permission.category, []).append({"id": permission.id, "name": permission.name, "resource": permission.resource, "action": permission.action, "description": permission.description})
    return {"items": grouped}
