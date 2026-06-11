from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.question import Question
from app.schemas.common import paginated_response
from app.schemas.review import (
    ReviewDueItem,
    ReviewStatsResponse,
    ReviewSubmitRequest,
    ReviewSubmitResponse,
    ReviewSubmitResult,
)
from app.schemas.review_scheduler import (
    BatchGradeRequest,
    BatchGradeResponse,
    BatchReviewRequest,
    BatchReviewResponse,
    GradeSubmit,
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
    return paginated_response(
        items=[ReviewDueItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


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

    await cache.delete(f"review:*:{current_user.id}*")
    await cache.delete(f"stats:*:{current_user.id}*")

    return ReviewSubmitResponse(
        results=[ReviewSubmitResult(**r) for r in results],
        processed=processed,
    )


@router.get("/stats", response_model=ReviewStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"review:stats:{current_user.id}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    stats = await svc.get_review_stats(db, current_user.id)
    result = ReviewStatsResponse(**stats)
    await cache.set(cache_key, result.model_dump(), ttl=300)
    return result


# ── Stage 12: SM-2 复习调度端点 ──


@router.get("/today", response_model=TodayReviewResponse)
async def get_today_review(
    subject: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取今日待复习题目（不含答案）。"""
    cache_key = f"review:today:{current_user.id}:{subject or 'all'}:{limit}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    result = await review_scheduler.get_today_review(
        db, current_user.id, subject=subject, limit=limit
    )
    await cache.set(cache_key, result, ttl=60)
    return result


@router.post("/schedule-submit", response_model=ScheduleSubmitResponse)
async def submit_schedule_review(
    data: ReviewSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交单题复习结果。"""
    try:
        result = await review_scheduler.submit_review(
            db,
            current_user.id,
            schedule_id=data.schedule_id,
            question_id=data.question_id,
            rating=data.rating,
        )
        await cache.delete(f"review:*:{current_user.id}*")
        await cache.delete(f"stats:*:{current_user.id}*")
        return result
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
        result = await review_scheduler.batch_submit_review(
            db, current_user.id, reviews
        )
        await cache.delete(f"review:*:{current_user.id}*")
        await cache.delete(f"stats:*:{current_user.id}*")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/grade-submit")
async def grade_submit(
    data: GradeSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """自动批改并提交复习结果。"""

    # 获取正确答案
    result = await db.execute(
        select(Question).where(Question.id == data.question_id)
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    # 判对错
    user_answer = (data.user_answer or "").strip().upper()
    correct_answer = (question.answer or "").strip().upper()
    is_correct = user_answer == correct_answer

    # 根据对错决定评分
    rating = 5 if is_correct else 0

    try:
        review_result = await review_scheduler.submit_review(
            db,
            current_user.id,
            schedule_id=data.schedule_id,
            question_id=data.question_id,
            rating=rating,
        )
        await cache.delete(f"review:*:{current_user.id}*")
        await cache.delete(f"stats:*:{current_user.id}*")

        return {
            "is_correct": is_correct,
            "correct_answer": correct_answer,
            "rating": rating,
            "schedule_id": review_result["schedule_id"],
            "interval_after": review_result["interval_after"],
            "ease_factor_after": review_result["ease_factor_after"],
            "next_review_at": review_result["next_review_at"],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    """批量自动批改并提交复习结果。"""
    if not data.reviews:
        raise HTTPException(status_code=400, detail="复习列表不能为空")

    results = []
    correct_count = 0
    wrong_count = 0

    for item in data.reviews:
        # 获取正确答案
        result = await db.execute(
            select(Question).where(Question.id == item.question_id)
        )
        question = result.scalar_one_or_none()
        if not question:
            results.append({
                "schedule_id": item.schedule_id,
                "question_id": item.question_id,
                "is_correct": False,
                "correct_answer": "",
                "rating": 0,
                "interval_after": 0,
                "ease_factor_after": 0.0,
                "next_review_at": None,
            })
            wrong_count += 1
            continue

        # 判对错
        user_answer = (item.user_answer or "").strip().upper()
        correct_answer = (question.answer or "").strip().upper()
        is_correct = user_answer == correct_answer

        # 根据对错决定评分
        rating = 5 if is_correct else 0

        try:
            review_result = await review_scheduler.submit_review(
                db,
                current_user.id,
                schedule_id=item.schedule_id,
                question_id=item.question_id,
                rating=rating,
            )
            results.append({
                "schedule_id": review_result["schedule_id"],
                "question_id": item.question_id,
                "is_correct": is_correct,
                "correct_answer": correct_answer,
                "rating": rating,
                "interval_after": review_result["interval_after"],
                "ease_factor_after": review_result["ease_factor_after"],
                "next_review_at": review_result["next_review_at"],
            })
            if is_correct:
                correct_count += 1
            else:
                wrong_count += 1
        except ValueError:
            results.append({
                "schedule_id": item.schedule_id,
                "question_id": item.question_id,
                "is_correct": False,
                "correct_answer": "",
                "rating": 0,
                "interval_after": 0,
                "ease_factor_after": 0.0,
                "next_review_at": None,
            })
            wrong_count += 1
            continue

    await cache.delete(f"review:*:{current_user.id}*")
    await cache.delete(f"stats:*:{current_user.id}*")

    return {
        "results": results,
        "total": len(results),
        "correct_count": correct_count,
        "wrong_count": wrong_count,
    }


@router.post("/{schedule_id}/master")
async def mark_mastered(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """标记题目为已掌握。"""
    schedule = await review_scheduler.mark_mastered(db, current_user.id, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="复习记录不存在")
    await cache.delete(f"review:*:{current_user.id}*")
    return {"schedule_id": schedule_id, "mastered": True}


@router.post("/{schedule_id}/unmaster")
async def unmark_mastered(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消已掌握标记。"""
    schedule = await review_scheduler.unmark_mastered(db, current_user.id, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="复习记录不存在")
    await cache.delete(f"review:*:{current_user.id}*")
    return {"schedule_id": schedule_id, "mastered": False}
