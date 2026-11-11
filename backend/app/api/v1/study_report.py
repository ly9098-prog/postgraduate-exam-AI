"""V5 学习报告 API 路由"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.runtime_paths import API_V1_PREFIX
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.study_report import (
    KnowledgeMasteryResponse,
    LeitnerDistributionResponse,
    ReviewPlanResponse,
    StudyOverviewResponse,
    StudyTrendResponse,
    WrongQuestionSummaryResponse,
)
from app.services import study_report_service as svc

router = APIRouter(prefix=f"{API_V1_PREFIX}/study-report", tags=["study-report"])


@router.get("/overview", response_model=StudyOverviewResponse)
async def study_overview(
    subject_id: int | None = Query(None, description="学科 ID，为空则统计全部"),
    days: int = Query(7, ge=1, le=365, description="近期统计天数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_overview(db, current_user.id, subject_id=subject_id, days=days)
    return StudyOverviewResponse(**data)


@router.get("/review-plan", response_model=ReviewPlanResponse)
async def review_plan(
    subject_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_review_plan(
        db, current_user.id, subject_id=subject_id, limit=limit
    )
    return ReviewPlanResponse(**data)


@router.get("/leitner-distribution", response_model=LeitnerDistributionResponse)
async def leitner_distribution(
    subject_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_leitner_distribution(
        db, current_user.id, subject_id=subject_id
    )
    return LeitnerDistributionResponse(**data)


@router.get("/knowledge-mastery", response_model=KnowledgeMasteryResponse)
async def knowledge_mastery(
    subject_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    sort: str = Query(
        "weak_first",
        pattern="^(weak_first|mastered_first|confidence_low|recent_practiced)$",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_knowledge_mastery(
        db, current_user.id, subject_id=subject_id, limit=limit, sort=sort
    )
    return KnowledgeMasteryResponse(**data)


@router.get("/wrong-questions", response_model=WrongQuestionSummaryResponse)
async def wrong_questions(
    subject_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    min_wrong_count: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_wrong_questions_summary(
        db,
        current_user.id,
        subject_id=subject_id,
        limit=limit,
        min_wrong_count=min_wrong_count,
    )
    return WrongQuestionSummaryResponse(**data)


@router.get("/trend", response_model=StudyTrendResponse)
async def study_trend(
    subject_id: int | None = Query(None),
    days: int = Query(7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_study_trend(
        db, current_user.id, subject_id=subject_id, days=days
    )
    return StudyTrendResponse(**data)
