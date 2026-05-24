from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.models.wrong_question import WrongQuestion
from app.services.wrong_question_service import update_quality


async def get_due_reviews(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """获取今日待复习错题列表"""
    today = date.today()
    conditions = [
        WrongQuestion.user_id == user_id,
        WrongQuestion.mastered == False,
        WrongQuestion.next_review_date <= today,
    ]

    if subject:
        count_q = (
            select(func.count(WrongQuestion.id))
            .join(Question, WrongQuestion.question_id == Question.id)
            .where(and_(*conditions, Question.subject == subject))
        )
        total = (await db.execute(count_q)).scalar()

        q = (
            select(WrongQuestion)
            .join(Question, WrongQuestion.question_id == Question.id)
            .where(and_(*conditions, Question.subject == subject))
            .order_by(WrongQuestion.next_review_date.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    else:
        count_q = select(func.count(WrongQuestion.id)).where(and_(*conditions))
        total = (await db.execute(count_q)).scalar()

        q = (
            select(WrongQuestion)
            .where(and_(*conditions))
            .order_by(WrongQuestion.next_review_date.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    result = await db.execute(q)
    wqs = list(result.scalars().all())

    question_ids = [w.question_id for w in wqs]
    questions_map = {}
    if question_ids:
        q_result = await db.execute(
            select(Question).where(Question.id.in_(question_ids))
        )
        questions_map = {q.id: q for q in q_result.scalars().all()}

    items = []
    for wq in wqs:
        q = questions_map.get(wq.question_id)
        items.append({
            "id": wq.id,
            "question_id": wq.question_id,
            "wrong_answer": wq.wrong_answer,
            "error_type": wq.error_type,
            "review_count": wq.review_count,
            "last_review_at": wq.last_review_at,
            "efactor": wq.efactor or 2.5,
            "interval": wq.interval or 0,
            "repetitions": wq.repetitions or 0,
            "next_review_date": wq.next_review_date,
            "quality": wq.quality,
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
    """复习统计数据"""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    base_conditions = [WrongQuestion.user_id == user_id]

    # 总错题数
    total_q = select(func.count(WrongQuestion.id)).where(and_(*base_conditions))
    total_wrong = (await db.execute(total_q)).scalar()

    # 今日待复习
    due_q = select(func.count(WrongQuestion.id)).where(
        and_(
            *base_conditions,
            WrongQuestion.mastered == False,
            WrongQuestion.next_review_date <= today,
        )
    )
    due_today = (await db.execute(due_q)).scalar()

    # 今日已复习
    reviewed_today_q = select(func.count(WrongQuestion.id)).where(
        and_(
            *base_conditions,
            WrongQuestion.last_review_at >= today,
        )
    )
    reviewed_today = (await db.execute(reviewed_today_q)).scalar()

    # 本周已复习
    reviewed_week_q = select(func.count(WrongQuestion.id)).where(
        and_(
            *base_conditions,
            WrongQuestion.last_review_at >= week_start,
        )
    )
    reviewed_this_week = (await db.execute(reviewed_week_q)).scalar()

    # 已掌握
    mastered_q = select(func.count(WrongQuestion.id)).where(
        and_(*base_conditions, WrongQuestion.mastered == True)
    )
    mastered = (await db.execute(mastered_q)).scalar()

    # 平均 efactor
    avg_ef_q = select(func.avg(WrongQuestion.efactor)).where(and_(*base_conditions))
    avg_ef = (await db.execute(avg_ef_q)).scalar()

    # 按科目统计（待复习 + 总计）
    subject_q = await db.execute(
        select(Question.subject, func.count(WrongQuestion.id).label("cnt"))
        .join(Question, WrongQuestion.question_id == Question.id)
        .where(and_(*base_conditions))
        .group_by(Question.subject)
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
