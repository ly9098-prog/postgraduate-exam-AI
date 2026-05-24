from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.stats import (
    BehaviorStats,
    DashboardResponse,
    ForgettingTrend,
    OverviewStats,
    SubjectStats,
    TrendPoint,
)
from app.services import stats_service as svc

router = APIRouter(prefix="/api/v1/stats")


@router.get("/overview", response_model=OverviewStats)
async def get_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_overview(db, current_user.id)
    return OverviewStats(**data)


@router.get("/subjects", response_model=list[SubjectStats])
async def get_subject_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_subject_stats(db, current_user.id)
    return [SubjectStats(**d) for d in data]


@router.get("/trends", response_model=list[TrendPoint])
async def get_trends(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_trends(db, current_user.id, days)
    return [TrendPoint(**d) for d in data]


@router.get("/behavior", response_model=BehaviorStats)
async def get_behavior(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_behavior_stats(db, current_user.id)
    return BehaviorStats(**data)


@router.get("/forgetting", response_model=ForgettingTrend)
async def get_forgetting(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_forgetting_trends(db, current_user.id)
    return ForgettingTrend(**data)


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    overview = await svc.get_overview(db, current_user.id)
    subjects = await svc.get_subject_stats(db, current_user.id)
    trends = await svc.get_trends(db, current_user.id, 7)
    behavior = await svc.get_behavior_stats(db, current_user.id)
    forgetting = await svc.get_forgetting_trends(db, current_user.id)
    return DashboardResponse(
        overview=OverviewStats(**overview),
        subject_stats=[SubjectStats(**s) for s in subjects],
        recent_trend=[TrendPoint(**t) for t in trends],
        behavior=BehaviorStats(**behavior),
        forgetting=ForgettingTrend(**forgetting),
    )
