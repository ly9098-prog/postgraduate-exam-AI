from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.admin_ai_settings import AdminAISettingsPatchRequest, AdminAISettingsResponse, AdminAIUsageMonthlyResponse
from app.services.admin_ai_settings_service import get_ai_settings, get_ai_usage, update_ai_settings

router = APIRouter(prefix="/api/admin/v1/ai-settings", tags=["admin-ai-settings"])


@router.get("", response_model=AdminAISettingsResponse)
async def read_ai_settings(
    _=Depends(require_permissions("ai_setting:read")),
    db: AsyncSession = Depends(get_db),
):
    return await get_ai_settings(db)


@router.patch("", response_model=AdminAISettingsResponse)
async def patch_ai_settings(
    data: AdminAISettingsPatchRequest,
    request: Request,
    current_admin=Depends(require_permissions("ai_setting:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await update_ai_settings(db, data, current_admin, request)
        await db.commit()
        return result
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/usage", response_model=AdminAIUsageMonthlyResponse)
async def read_ai_usage(
    year_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$", alias="yearMonth"),
    _=Depends(require_permissions("ai_setting:read")),
    db: AsyncSession = Depends(get_db),
):
    return await get_ai_usage(db, year_month)
