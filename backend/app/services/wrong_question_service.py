from datetime import datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.models.review_scheduler import ReviewSchedule
from app.models.wrong_question import WrongQuestion
from app.core.time_utils import utcnow


async def record_wrong(
    db: AsyncSession, user_id: int, question_id: int, wrong_answer: str
) -> WrongQuestion:
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.question_id == question_id,
        )
    )
    wq = result.scalars().first()

    if wq:
        wq.wrong_answer = wrong_answer
        wq.review_count = (wq.review_count or 0) + 1
        wq.last_review_at = utcnow()
        wq.mastered = False
    else:
        wq = WrongQuestion(
            user_id=user_id,
            question_id=question_id,
            wrong_answer=wrong_answer,
            review_count=1,
            last_review_at=utcnow(),
        )
        db.add(wq)

    # 错题自动进入复习调度（SM-2 由 ReviewSchedule 管理）
    # auto_schedule 内部会 commit，WQ 变更也会随之 flush
    from app.services import review_scheduler
    await review_scheduler.auto_schedule_wrong_question(db, user_id, question_id)

    await db.refresh(wq)
    return wq


async def list_wrong(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    error_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[WrongQuestion], int]:
    conditions = [WrongQuestion.user_id == user_id]
    if error_type:
        conditions.append(WrongQuestion.error_type == error_type)

    # 如果指定了学科，需要 join Question 表
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
            .order_by(WrongQuestion.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    else:
        count_q = select(func.count(WrongQuestion.id)).where(and_(*conditions))
        total = (await db.execute(count_q)).scalar()

        q = (
            select(WrongQuestion)
            .where(and_(*conditions))
            .order_by(WrongQuestion.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    result = await db.execute(q)
    return list(result.scalars().all()), total


async def get_by_id(db: AsyncSession, user_id: int, wq_id: int) -> WrongQuestion | None:
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id == wq_id, WrongQuestion.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def update_wrong(
    db: AsyncSession, user_id: int, wq_id: int, error_type: str | None
) -> WrongQuestion | None:
    wq = await get_by_id(db, user_id, wq_id)
    if not wq:
        return None
    if error_type is not None:
        wq.error_type = error_type
    await db.commit()
    await db.refresh(wq)
    return wq


async def get_stats(db: AsyncSession, user_id: int) -> dict:
    conditions = [WrongQuestion.user_id == user_id]
    total_q = select(func.count(WrongQuestion.id)).where(and_(*conditions))
    total = (await db.execute(total_q)).scalar()

    type_result = await db.execute(
        select(WrongQuestion.error_type, func.count(WrongQuestion.id).label("cnt"))
        .where(and_(*conditions))
        .group_by(WrongQuestion.error_type)
    )
    by_error_type = [{"type": r[0], "count": r[1]} for r in type_result.all()]

    # Count by subject from joined questions
    result3 = await db.execute(
        select(Question.subject, func.count(WrongQuestion.id).label("cnt"))
        .join(Question, WrongQuestion.question_id == Question.id)
        .where(and_(*conditions))
        .group_by(Question.subject)
    )

    by_subject = [{"subject": r[0], "count": r[1]} for r in result3.all()]

    unmastered_q = select(func.count(WrongQuestion.id)).where(
        WrongQuestion.user_id == user_id,
        WrongQuestion.mastered == False,
    )
    unmastered = (await db.execute(unmastered_q)).scalar() or 0

    return {
        "total": total,
        "unmastered": unmastered,
        "by_subject": by_subject,
        "by_error_type": by_error_type,
    }


async def update_quality(
    db: AsyncSession, user_id: int, wq_id: int, quality: int
) -> WrongQuestion | None:
    """评分错题并触发 SM-2 更新（路由到 ReviewSchedule，不在 WQ 上独立计算）"""
    wq = await get_by_id(db, user_id, wq_id)
    if not wq:
        return None

    from app.services import review_scheduler

    # 查或创建 ReviewSchedule
    result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.question_id == wq.question_id,
        )
    )
    schedule = result.scalar_one_or_none()

    if not schedule:
        schedule = await review_scheduler.auto_schedule_wrong_question(
            db, user_id, wq.question_id
        )

    # 通过 review_scheduler.submit_review 统一提交 SM-2 更新
    await review_scheduler.submit_review(
        db,
        user_id=user_id,
        schedule_id=schedule.id,
        question_id=wq.question_id,
        rating=quality,
    )

    await db.refresh(wq)
    return wq
