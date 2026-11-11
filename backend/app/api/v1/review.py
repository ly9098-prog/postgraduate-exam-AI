from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.review_scheduler import (
    BatchGradeRequest,
    BatchGradeResponse,
    MasterUnmasterResponse,
    NextBatchRequest,
    NextBatchResponse,
    ReviewHistoryResponse,
    TodayReviewOverviewResponse,
    TodayReviewResponse,
    TodayReviewResultResponse,
)
from app.schemas.review_scheduler import (
    ReviewStatsResponse as ScheduleStatsResponse,
)
from app.services import review_scheduler
from app.core.runtime_paths import API_V1_PREFIX
router = APIRouter(prefix=f"{API_V1_PREFIX}/review")


# ── Stage 12: SM-2 复习调度端点 ──


@router.get("/today", response_model=TodayReviewResponse)
async def get_today_review(
    subject_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取今日待复习题目（不含答案）。"""
    # Question revisions can be corrected while a long-lived review schedule is
    # waiting in the queue. Do not cache actionable task payloads: issuance also
    # rebinds the schedule to the newest immutable revision/occurrence tuple.
    return await review_scheduler.get_today_review(
        db, current_user.id, subject_id=subject_id, limit=limit
    )


@router.get("/today/overview", response_model=TodayReviewOverviewResponse)
async def get_today_review_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取今日复习任务概览。"""
    cache_key = f"review:today_overview:{current_user.id}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    result = await review_scheduler.get_today_review_overview(db, current_user.id)
    await cache.set(cache_key, result, ttl=60)
    return result


@router.post("/today/next-batch", response_model=NextBatchResponse)
async def get_next_today_review_batch(
    data: NextBatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取今日下一组待复习题。"""
    result = await review_scheduler.get_next_today_review_batch(
        db,
        current_user.id,
        batch_size=data.batch_size,
    )
    return result


@router.get("/today/result", response_model=TodayReviewResultResponse)
async def get_today_review_result(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取今日复习最终结果。"""
    result = await review_scheduler.get_today_review_result(db, current_user.id)
    return result


@router.get("/schedule-stats", response_model=ScheduleStatsResponse)
async def get_schedule_stats(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取复习调度统计。"""
    cache_key = f"review:schedule_stats:{current_user.id}:{days}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    result = await review_scheduler.get_review_stats(db, current_user.id, days=days)
    await cache.set(cache_key, result, ttl=300)
    return result


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


@router.post("/grade-batch", response_model=BatchGradeResponse)
async def grade_batch(
    data: BatchGradeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量自动批改；所有判题均绑定 ReviewSchedule 的不可变题目版本。"""
    try:
        reviews = [item.model_dump() for item in data.reviews]
        result = await review_scheduler.grade_batch_review(
            db,
            current_user.id,
            reviews,
            session_meta=data.session.model_dump() if data.session else None,
        )
        await cache.delete(f"review:*:{current_user.id}*")
        await cache.delete(f"stats:*:{current_user.id}*")
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{schedule_id}/master", response_model=MasterUnmasterResponse)
async def master_review_question(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动标记当前复习任务为已掌握。"""
    schedule, changed = await review_scheduler.mark_mastered(
        db, current_user.id, schedule_id
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="复习记录不存在")
    await cache.delete(f"review:*:{current_user.id}*")
    await cache.delete(f"stats:*:{current_user.id}*")
    return MasterUnmasterResponse(
        schedule_id=schedule.id,
        mastered=True,
        occurrence_seq=int(schedule.occurrence_seq or 0),
        active=bool(schedule.is_active),
        changed=changed,
    )


@router.post("/{schedule_id}/unmaster", response_model=MasterUnmasterResponse)
async def unmaster_review_question(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """撤销手动掌握，并恢复当前题目的复习资格。"""
    try:
        schedule, changed = await review_scheduler.unmark_mastered(
            db, current_user.id, schedule_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if schedule is None:
        raise HTTPException(status_code=404, detail="复习记录不存在")
    await cache.delete(f"review:*:{current_user.id}*")
    await cache.delete(f"stats:*:{current_user.id}*")
    return MasterUnmasterResponse(
        schedule_id=schedule.id,
        mastered=False,
        occurrence_seq=int(schedule.occurrence_seq or 0),
        active=bool(schedule.is_active),
        changed=changed,
    )
