from datetime import datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.question import Question
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.wrong_question import WrongQuestion
from app.services.wrong_question_service import update_quality


async def get_due_reviews(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """获取今日待复习列表（基于 ReviewSchedule 主数据源）。"""
    now = utcnow()
    conditions = [
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.mastered == False,
        ReviewSchedule.next_review_at <= now,
    ]

    if subject:
        count_q = (
            select(func.count(ReviewSchedule.id))
            .join(Question, ReviewSchedule.question_id == Question.id)
            .where(and_(*conditions, Question.subject == subject))
        )
        total = (await db.execute(count_q)).scalar()

        q = (
            select(ReviewSchedule)
            .join(Question, ReviewSchedule.question_id == Question.id)
            .where(and_(*conditions, Question.subject == subject))
            .order_by(ReviewSchedule.next_review_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    else:
        count_q = select(func.count(ReviewSchedule.id)).where(and_(*conditions))
        total = (await db.execute(count_q)).scalar()

        q = (
            select(ReviewSchedule)
            .where(and_(*conditions))
            .order_by(ReviewSchedule.next_review_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    result = await db.execute(q)
    schedules = list(result.scalars().all())

    question_ids = [s.question_id for s in schedules]

    wq_map = {}
    if question_ids:
        wq_result = await db.execute(
            select(WrongQuestion).where(
                WrongQuestion.user_id == user_id,
                WrongQuestion.question_id.in_(question_ids),
            )
        )
        wq_map = {wq.question_id: wq for wq in wq_result.scalars().all()}

    questions_map = {}
    if question_ids:
        q_result = await db.execute(
            select(Question).where(Question.id.in_(question_ids))
        )
        questions_map = {q.id: q for q in q_result.scalars().all()}

    items = []
    for s in schedules:
        wq = wq_map.get(s.question_id)
        q = questions_map.get(s.question_id)
        items.append({
            "id": wq.id if wq else s.id,
            "question_id": s.question_id,
            "wrong_answer": wq.wrong_answer if wq else None,
            "error_type": wq.error_type if wq else "other",
            "review_count": wq.review_count if wq else 0,
            "last_review_at": wq.last_review_at if wq else None,
            "efactor": s.ease_factor,
            "interval": s.interval,
            "repetitions": s.repetitions,
            "next_review_date": s.next_review_at.date() if s.next_review_at else None,
            "quality": wq.quality if wq else None,
            "subject": q.subject if q else None,
            "content": q.content if q else None,
            "options": q.options if q else None,
            "answer": q.answer if q else None,
            "analysis": q.analysis if q else None,
            "knowledge_points": q.knowledge_points if q else None,
        })

    return items, total


async def submit_review(
    db: AsyncSession, user_id: int, wq_id: int, quality: int
) -> dict | None:
    """单题复习提交"""
    wq = await update_quality(db, user_id, wq_id, quality)
    if not wq:
        return None
    return {
        "wrong_question_id": wq.id,
        "quality": quality,
        "sm2": {
            "efactor": wq.efactor,
            "interval": wq.interval,
            "repetitions": wq.repetitions,
            "next_review_date": wq.next_review_date,
        },
    }


async def submit_batch_review(
    db: AsyncSession, user_id: int, items: list[dict]
) -> list[dict]:
    """批量复习提交"""
    results = []
    for item in items:
        r = await submit_review(db, user_id, item["wrong_question_id"], item["quality"])
        if r:
            results.append(r)
    return results


async def get_review_stats(db: AsyncSession, user_id: int) -> dict:
    """复习统计数据（基于 ReviewSchedule / ReviewRecord 主数据源）。"""
    today = utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    week_start = datetime.combine(
        today - timedelta(days=today.weekday()), datetime.min.time()
    )

    # 总错题数（RS 中每个 question_id 一条记录）
    total_q = select(func.count(ReviewSchedule.id)).where(
        ReviewSchedule.user_id == user_id
    )
    total_wrong = (await db.execute(total_q)).scalar()

    # 今日待复习
    due_q = select(func.count(ReviewSchedule.id)).where(
        and_(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.mastered == False,
            ReviewSchedule.next_review_at <= utcnow(),
        )
    )
    due_today = (await db.execute(due_q)).scalar()

    # 今日已复习（去重题目数）
    reviewed_today_q = select(
        func.count(func.distinct(ReviewRecord.question_id))
    ).where(
        ReviewRecord.user_id == user_id,
        ReviewRecord.reviewed_at >= today_start,
    )
    reviewed_today = (await db.execute(reviewed_today_q)).scalar()

    # 本周已复习（去重题目数）
    reviewed_week_q = select(
        func.count(func.distinct(ReviewRecord.question_id))
    ).where(
        ReviewRecord.user_id == user_id,
        ReviewRecord.reviewed_at >= week_start,
    )
    reviewed_this_week = (await db.execute(reviewed_week_q)).scalar()

    # 已掌握
    mastered_q = select(func.count(ReviewSchedule.id)).where(
        and_(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.mastered == True,
        )
    )
    mastered = (await db.execute(mastered_q)).scalar()

    # 平均 ease_factor
    avg_ef_q = select(func.avg(ReviewSchedule.ease_factor)).where(
        ReviewSchedule.user_id == user_id
    )
    avg_ef = (await db.execute(avg_ef_q)).scalar()

    # 按科目统计
    subject_q = await db.execute(
        select(
            ReviewSchedule.subject,
            func.count(ReviewSchedule.id).label("cnt"),
        )
        .where(ReviewSchedule.user_id == user_id)
        .group_by(ReviewSchedule.subject)
    )
    by_subject = [{"subject": r[0], "count": r[1]} for r in subject_q.all()]

    return {
        "total_wrong": total_wrong,
        "due_today": due_today,
        "reviewed_today": reviewed_today,
        "reviewed_this_week": reviewed_this_week,
        "mastered": mastered,
        "average_efactor": round(avg_ef, 4) if avg_ef else 2.5,
        "by_subject": by_subject,
    }
