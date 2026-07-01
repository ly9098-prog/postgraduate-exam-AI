from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache, make_cache_key
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.ai_diagnosis import AiDiagnosis
from app.schemas.dashboard_insights import DashboardInsightsResponse
from app.schemas.dashboard_llm import DashboardLlmAnalysisRequest, DashboardLlmAnalysisResponse
from app.schemas.stats_v2 import DashboardV2Response
from app.schemas.growth import GrowthProfile
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
    cache_key = f"stats:overview:{current_user.id}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    data = await svc.get_overview(db, current_user.id)
    await cache.set(cache_key, data, ttl=300)
    return OverviewStats(**data)


@router.get("/subjects", response_model=list[SubjectStats])
async def get_subject_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"stats:subjects:{current_user.id}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    data = await svc.get_subject_stats(db, current_user.id)
    await cache.set(cache_key, data, ttl=300)
    return [SubjectStats(**d) for d in data]


@router.get("/trends", response_model=list[TrendPoint])
async def get_trends(
    days: int = Query(7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"stats:trends:{current_user.id}:{days}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    data = await svc.get_trends(db, current_user.id, days)
    await cache.set(cache_key, data, ttl=300)
    return [TrendPoint(**d) for d in data]


@router.get("/behavior", response_model=BehaviorStats)
async def get_behavior(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"stats:behavior:{current_user.id}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    data = await svc.get_behavior_stats(db, current_user.id)
    await cache.set(cache_key, data, ttl=600)
    return BehaviorStats(**data)


@router.get("/forgetting", response_model=ForgettingTrend)
async def get_forgetting(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"stats:forgetting:{current_user.id}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    data = await svc.get_forgetting_trends(db, current_user.id)
    await cache.set(cache_key, data, ttl=300)
    return ForgettingTrend(**data)


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"stats:dashboard:{current_user.id}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    overview = await svc.get_overview(db, current_user.id)
    subjects = await svc.get_subject_stats(db, current_user.id)
    trends = await svc.get_trends(db, current_user.id, 7)
    behavior = await svc.get_behavior_stats(db, current_user.id)
    forgetting = await svc.get_forgetting_trends(db, current_user.id)
    result = DashboardResponse(
        overview=OverviewStats(**overview),
        subject_stats=[SubjectStats(**s) for s in subjects],
        recent_trend=[TrendPoint(**t) for t in trends],
        behavior=BehaviorStats(**behavior),
        forgetting=ForgettingTrend(**forgetting),
    )
    await cache.set(cache_key, result.model_dump(), ttl=120)
    return result


@router.get("/growth", response_model=GrowthProfile)
async def get_growth(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"stats:growth:{current_user.id}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    data = await svc.get_growth_profile(db, current_user.id)
    await cache.set(cache_key, data, ttl=120)
    return GrowthProfile(**data)


@router.get("/dashboard-v2", response_model=DashboardV2Response)
async def get_dashboard_v2(
    trend_days: int = Query(7, ge=1, le=90),
    include_yearly_summary: bool = Query(True),
    include_growth: bool = Query(True),
    include_adaptive: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """聚合学习看板 V2 — 一次请求包含总览、推荐、趋势、学科、遗忘、成长、自适应、年度摘要。"""
    data = await svc.get_dashboard_v2(
        db, current_user.id,
        trend_days=trend_days,
        include_yearly_summary=include_yearly_summary,
        include_growth=include_growth,
        include_adaptive=include_adaptive,
    )
    return DashboardV2Response(**data)


@router.get("/ai-diagnosis", response_model=AiDiagnosis)
async def get_ai_diagnosis(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"stats:ai_diagnosis:{current_user.id}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    data = await svc.get_ai_diagnosis(db, current_user.id)
    await cache.set(cache_key, data, ttl=600)
    return AiDiagnosis(**data)


@router.post("/dashboard-llm-analysis", response_model=DashboardLlmAnalysisResponse)
async def post_dashboard_llm_analysis(
    body: DashboardLlmAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动触发 LLM 学习诊断 — 不自动调用，需用户点击按钮。"""
    data = await svc.get_dashboard_llm_analysis(
        db, current_user.id, trend_days=body.trend_days
    )
    return DashboardLlmAnalysisResponse(**data)


@router.get("/dashboard-insights", response_model=DashboardInsightsResponse)
async def get_dashboard_insights(
    days: int = Query(7, ge=1, le=90),
    include_subjects: bool = Query(True),
    include_topics: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """刷题诊断数据 — 今日学习质量、稳定性、薄弱知识点、错题复发等。"""

    from app.services.dashboard_insights_service import get_dashboard_insights as get_di

    data = await get_di(
        db,
        current_user.id,
        days=days,
        include_subjects=include_subjects,
        include_topics=include_topics,
    )
    return DashboardInsightsResponse(**data)
