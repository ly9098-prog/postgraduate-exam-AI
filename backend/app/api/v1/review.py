from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.review import (
    ReviewDueItem,
    ReviewStatsResponse,
    ReviewSubmitRequest,
    ReviewSubmitResponse,
    ReviewSubmitResult,
)
from app.schemas.review_scheduler import (
    BatchReviewRequest,
    BatchReviewResponse,
    ReviewHistoryResponse,
    ReviewStatsResponse as ScheduleStatsResponse,
    ReviewSubmit,
    ReviewSubmitResponse as ScheduleSubmitResponse,
    TodayReviewResponse,
)
from app.services import review_scheduler, review_service as svc

router = APIRouter(prefix="/api/v1/review")


@router.get("/due")
async def list_due_reviews(
    subject: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = await svc.get_due_reviews(
        db, current_user.id, subject, page, page_size
    )
    return {
        "items": [ReviewDueItem(**item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.post("/submit", response_model=ReviewSubmitResponse)
async def submit_review(
    data: ReviewSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = [d.model_dump() for d in data.items]
    results = await svc.submit_batch_review(db, current_user.id, items)

    processed = len(results)
    if processed == 0:
        raise HTTPException(status_code=404, detail="没有找到有效的错题记录")

    return ReviewSubmitResponse(
        results=[ReviewSubmitResult(**r) for r in results],
        processed=processed,
    )


@router.get("/stats", response_model=ReviewStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stats = await svc.get_review_stats(db, current_user.id)
    return ReviewStatsResponse(**stats)


# ── Stage 12: SM-2 复习调度端点 ──


@router.get("/today", response_model=TodayReviewResponse)
async def get_today_review(
    subject: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取今日待复习题目（不含答案）。"""
    return await review_scheduler.get_today_review(
        db, current_user.id, subject=subject, limit=limit
    )


@router.post("/schedule-submit", response_model=ScheduleSubmitResponse)
async def submit_schedule_review(
    data: ReviewSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交单题复习结果。"""
    try:
        return await review_scheduler.submit_review(
            db,
            current_user.id,
            schedule_id=data.schedule_id,
            question_id=data.question_id,
            rating=data.rating,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/batch-submit", response_model=BatchReviewResponse)
async def batch_submit_review(
    data: BatchReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量提交复习结果。"""
    if not data.reviews:
        raise HTTPException(status_code=400, detail="复习列表不能为空")
    try:
        reviews = [r.model_dump() for r in data.reviews]
        return await review_scheduler.batch_submit_review(
            db, current_user.id, reviews
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/schedule-stats", response_model=ScheduleStatsResponse)
async def get_schedule_stats(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取复习调度统计。"""
    return await review_scheduler.get_review_stats(db, current_user.id, days=days)


@router.get("/history", response_model=ReviewHistoryResponse)
async def get_review_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取复习历史记录。"""
    return await review_scheduler.get_review_history(
        db, current_user.id, page=page, page_size=page_size
    )
