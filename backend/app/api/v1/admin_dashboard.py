from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.admin_ai_settings import AdminAIStatsResponse
from app.schemas.admin_dashboard import (
    AdminDashboardDailyPoint,
    AdminDashboardOverview,
    AdminDashboardQuestionStats,
)
from app.services.admin_ai_settings_service import get_ai_stats
from app.services.admin_dashboard_service import (
    get_dashboard_daily,
    get_dashboard_overview,
    get_dashboard_question_stats,
)

router = APIRouter(prefix="/api/admin/v1/dashboard", tags=["admin-dashboard"])


@router.get("/overview", response_model=AdminDashboardOverview)
async def overview(
    _=Depends(require_permissions("dashboard:read")),
    db: AsyncSession = Depends(get_db),
):
    return await get_dashboard_overview(db)


@router.get("/daily", response_model=list[AdminDashboardDailyPoint])
async def daily(
    created_from: date | None = Query(default=None, alias="from"),
    created_to: date | None = Query(default=None, alias="to"),
    _=Depends(require_permissions("dashboard:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_dashboard_daily(db, created_from, created_to)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )


@router.get("/questions-stats", response_model=AdminDashboardQuestionStats)
async def questions_stats(
    _=Depends(require_permissions("dashboard:read")),
    db: AsyncSession = Depends(get_db),
):
    return await get_dashboard_question_stats(db)


@router.get("/ai-stats", response_model=AdminAIStatsResponse)
async def ai_stats(
    days: int = Query(default=7, ge=1, le=90),
    _=Depends(require_permissions("dashboard:read")),
    db: AsyncSession = Depends(get_db),
):
    return await get_ai_stats(db, days, summary_days=days)
