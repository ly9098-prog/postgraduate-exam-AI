from datetime import datetime, timedelta

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.wrong_question import WrongQuestion
from app.services.sm2_service import calc_sm2
from app.core.time_utils import utcnow


async def _sync_schedule_to_wq(
    db: AsyncSession, schedule: ReviewSchedule
) -> None:
    """同步 ReviewSchedule 的 SM-2 字段到 WrongQuestion 兼容字段。

    WrongQuestion 的 efactor/interval/repetitions/next_review_date/mastered
    仅为兼容/历史字段，主调度来源为 ReviewSchedule。
    每次更新 ReviewSchedule 后调用本函数确保两表一致。
    """
    wq_result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.user_id == schedule.user_id,
            WrongQuestion.question_id == schedule.question_id,
        )
    )
    wq = wq_result.scalar_one_or_none()
    if wq:
        wq.last_review_at = schedule.last_reviewed_at
        await db.commit()


async def get_today_review(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    limit: int = 20,
) -> dict:
    now = utcnow()
    conditions = [
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.next_review_at <= now,
        ReviewSchedule.mastered == False,
    ]

    if subject:
        # subject 筛选在 SQL 层完成，避免 limit 后过滤漏题
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
            .limit(limit)
        )
    else:
        count_q = select(func.count(ReviewSchedule.id)).where(and_(*conditions))
        total = (await db.execute(count_q)).scalar()

        q = (
            select(ReviewSchedule)
            .where(and_(*conditions))
            .order_by(ReviewSchedule.next_review_at.asc())
            .limit(limit)
        )

    result = await db.execute(q)
    schedules = list(result.scalars().all())

    question_ids = [s.question_id for s in schedules]
    questions_map = {}
    if question_ids:
        q_result = await db.execute(
            select(Question).where(Question.id.in_(question_ids))
        )
        questions_map = {q.id: q for q in q_result.scalars().all()}

    questions = []
    for s in schedules:
        q = questions_map.get(s.question_id)
        if not q:
            continue
        stem = ""
        if isinstance(q.content, dict):
            stem = q.content.get("text", "")
        elif isinstance(q.content, str):
            stem = q.content
        questions.append({
            "schedule_id": s.id,
            "question_id": s.question_id,
            "subject": q.subject,
            "question_type": q.question_type,
            "stem": stem,
            "options": q.options or {},
            "content": q.content,
            "interval": s.interval,
            "repetitions": s.repetitions,
            "ease_factor": s.ease_factor,
        })

    return {
        "total_today": total,
        "questions": questions,
    }


async def submit_review(
    db: AsyncSession,
    user_id: int,
    schedule_id: int,
    question_id: int,
    rating: int,
) -> dict:
    if rating < 0 or rating > 5:
        raise ValueError(f"评分必须在 0-5 之间，收到: {rating}")

    result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.id == schedule_id,
            ReviewSchedule.user_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise ValueError(f"复习记录不存在: {schedule_id}")
    if schedule.question_id != question_id:
        raise ValueError(f"题目与复习记录不匹配")

    sm2_result = calc_sm2(
        quality=rating,
        efactor=schedule.ease_factor,
        interval=schedule.interval,
        repetitions=schedule.repetitions,
        review_date=utcnow().date(),
    )

    interval_before = schedule.interval
    ef_before = schedule.ease_factor

    schedule.ease_factor = sm2_result["efactor"]
    schedule.interval = sm2_result["interval"]
    schedule.repetitions = sm2_result["repetitions"]
    schedule.next_review_at = datetime.combine(
        sm2_result["next_review_date"], datetime.min.time()
    )
    schedule.last_reviewed_at = utcnow()

    await _sync_schedule_to_wq(db, schedule)

    record = ReviewRecord(
        user_id=user_id,
        question_id=question_id,
        schedule_id=schedule_id,
        rating=rating,
        interval_before=interval_before,
        interval_after=sm2_result["interval"],
        ease_factor_before=ef_before,
        ease_factor_after=sm2_result["efactor"],
        reviewed_at=utcnow(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(schedule)

    return {
        "schedule_id": schedule.id,
        "question_id": question_id,
        "rating": rating,
        "interval_after": sm2_result["interval"],
        "ease_factor_after": sm2_result["efactor"],
        "next_review_at": schedule.next_review_at,
        "is_correct": rating >= 3,
    }


async def batch_submit_review(
    db: AsyncSession,
    user_id: int,
    reviews: list[dict],
) -> dict:
    results = []
    for item in reviews:
        r = await submit_review(
            db=db,
            user_id=user_id,
            schedule_id=item["schedule_id"],
            question_id=item["question_id"],
            rating=item["rating"],
        )
        results.append({
            "schedule_id": r["schedule_id"],
            "question_id": r["question_id"],
            "next_review_at": r["next_review_at"],
            "is_correct": r["is_correct"],
        })
    return {"results": results, "total": len(results)}


async def get_review_stats(
    db: AsyncSession,
    user_id: int,
    days: int = 7,
) -> dict:
    now = utcnow()
    today_start = datetime.combine(now.date(), datetime.min.time())
    since = today_start - timedelta(days=days - 1)

    # Total scheduled
    total_q = select(func.count(ReviewSchedule.id)).where(
        ReviewSchedule.user_id == user_id
    )
    total_scheduled = (await db.execute(total_q)).scalar()

    # Reviewed today
    reviewed_today_q = select(func.count(ReviewRecord.id)).where(
        ReviewRecord.user_id == user_id,
        ReviewRecord.reviewed_at >= today_start,
    )
    total_reviewed_today = (await db.execute(reviewed_today_q)).scalar()

    # Remaining today (exclude mastered)
    remaining_q = select(func.count(ReviewSchedule.id)).where(
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.next_review_at <= now,
        ReviewSchedule.mastered == False,
    )
    remaining_today = (await db.execute(remaining_q)).scalar()

    # Overdue (next_review_at < now, not reviewed today, exclude mastered)
    overdue_q = select(func.count(ReviewSchedule.id)).where(
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.next_review_at < now,
        ReviewSchedule.mastered == False,
    )
    overdue = (await db.execute(overdue_q)).scalar()

    # Accuracy last N days (rating >= 3 = correct)
    accuracy_q = await db.execute(
        select(
            func.count(ReviewRecord.id),
            func.sum(
                case((ReviewRecord.rating >= 3, 1), else_=0)
            ),
        ).where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.reviewed_at >= since,
        )
    )
    acc_row = accuracy_q.one()
    total_reviews = acc_row[0] or 0
    correct_reviews = acc_row[1] or 0
    accuracy = round(correct_reviews / total_reviews, 4) if total_reviews > 0 else 0.0

    # By subject
    subject_result = await db.execute(
        select(
            ReviewSchedule.subject,
            func.count(ReviewSchedule.id).label("scheduled"),
            func.sum(
                case(
                    (and_(ReviewSchedule.next_review_at <= now, ReviewSchedule.mastered == False), 1), else_=0
                )
            ).label("remaining"),
        )
        .where(ReviewSchedule.user_id == user_id)
        .group_by(ReviewSchedule.subject)
    )

    # Reviewed by subject today
    subject_reviewed_result = await db.execute(
        select(
            ReviewSchedule.subject,
            func.count(func.distinct(ReviewRecord.question_id)).label("reviewed"),
        )
        .join(ReviewRecord, ReviewRecord.schedule_id == ReviewSchedule.id)
        .where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.reviewed_at >= today_start,
        )
        .group_by(ReviewSchedule.subject)
    )
    reviewed_by_subject = {
        r[0]: r[1] for r in subject_reviewed_result.all() if r[0]
    }

    by_subject = {}
    for row in subject_result.all():
        subj = row[0] or "unknown"
        sched = row[1] or 0
        rem = row[2] or 0
        rev = reviewed_by_subject.get(subj, 0)
        by_subject[subj] = {
            "scheduled": sched,
            "reviewed": rev,
            "remaining": rem,
        }

    return {
        "total_scheduled": total_scheduled,
        "total_reviewed_today": total_reviewed_today,
        "remaining_today": remaining_today,
        "overdue": overdue,
        "accuracy_last_7d": accuracy,
        "by_subject": by_subject,
    }


async def get_review_history(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    count_q = select(func.count(ReviewRecord.id)).where(
        ReviewRecord.user_id == user_id
    )
    total = (await db.execute(count_q)).scalar()

    result = await db.execute(
        select(ReviewRecord)
        .where(ReviewRecord.user_id == user_id)
        .order_by(ReviewRecord.reviewed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    records = list(result.scalars().all())

    items = [
        {
            "question_id": r.question_id,
            "rating": r.rating,
            "interval_after": r.interval_after or 0,
            "reviewed_at": r.reviewed_at,
        }
        for r in records
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def auto_schedule_wrong_question(
    db: AsyncSession,
    user_id: int,
    question_id: int,
) -> ReviewSchedule | None:
    """错题自动进入复习调度。已存在则更新，不存在则创建。"""
    result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.question_id == question_id,
        )
    )
    schedule = result.scalar_one_or_none()

    if schedule:
        # 已有 schedule → 使用 SM-2 算法处理做错，保留已有 ease_factor
        # 以 quality=0（完全不会）调用 calc_sm2，使用当前调度参数作为输入
        sm2_result = calc_sm2(
            quality=0,
            efactor=schedule.ease_factor or 2.5,
            interval=schedule.interval or 1,
            repetitions=schedule.repetitions or 0,
            review_date=utcnow().date(),
        )
        schedule.interval = sm2_result["interval"]
        schedule.ease_factor = sm2_result["efactor"]
        schedule.repetitions = sm2_result["repetitions"]
        schedule.next_review_at = utcnow()
        schedule.last_reviewed_at = None
        schedule.mastered = False
    else:
        # 获取题目科目
        q_result = await db.execute(
            select(Question).where(Question.id == question_id)
        )
        question = q_result.scalar_one_or_none()
        subject = question.subject if question else None

        schedule = ReviewSchedule(
            user_id=user_id,
            question_id=question_id,
            subject=subject,
            interval=1,
            ease_factor=2.5,
            repetitions=0,
            next_review_at=utcnow(),
        )
        db.add(schedule)

    await db.commit()
    await db.refresh(schedule)

    await _sync_schedule_to_wq(db, schedule)

    return schedule


async def mark_mastered(
    db: AsyncSession, user_id: int, schedule_id: int
) -> ReviewSchedule | None:
    """标记复习题目为已掌握，从复习池移除。"""
    result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.id == schedule_id,
            ReviewSchedule.user_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        return None
    schedule.mastered = True
    await db.commit()
    await db.refresh(schedule)
    await _sync_schedule_to_wq(db, schedule)
    return schedule


async def unmark_mastered(
    db: AsyncSession, user_id: int, schedule_id: int
) -> ReviewSchedule | None:
    """取消已掌握标记，恢复到复习池。"""
    result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.id == schedule_id,
            ReviewSchedule.user_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        return None
    schedule.mastered = False
    await db.commit()
    await db.refresh(schedule)
    await _sync_schedule_to_wq(db, schedule)
    return schedule
