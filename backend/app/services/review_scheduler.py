from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.time_utils import shanghai_date_utc_range, shanghai_today, shanghai_today_boundaries, utcnow
from app.models.question import Question
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.wrong_question import WrongQuestion
from app.services.sm2_service import calc_sm2

# Asia/Shanghai = UTC+8, no DST
_SHANGHAI_TZ = timezone(timedelta(hours=8))


async def _sync_schedule_to_wq(
    db: AsyncSession,
    schedule: ReviewSchedule,
    latest_wrong_answer: str | None = None,
) -> None:
    """同步 ReviewSchedule → WrongQuestion，不单独 commit。

    ``latest_wrong_answer`` 仅在自动批改确认本次仍答错时传入，用于把错题详情
    中的“我的错题”刷新为本次选择；普通调度更新不会覆盖历史错题答案。
    """
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.user_id == schedule.user_id,
            WrongQuestion.question_id == schedule.question_id,
        )
    )
    wq = result.scalar_one_or_none()
    if wq:
        if schedule.last_reviewed_at is not None:
            wq.last_review_at = schedule.last_reviewed_at
        wq.mastered = schedule.mastered

        if latest_wrong_answer is not None:
            wq.wrong_answer = latest_wrong_answer
            wq.review_count = (wq.review_count or 0) + 1
            wq.mastered = False
            wq.mastered_at = None


async def set_mastered_state(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
    mastered: bool,
) -> bool:
    """统一设置题目掌握状态，同时收敛 WrongQuestion 和 ReviewSchedule。

    这是 route 层和 batch 操作的唯一内部入口，调用方负责事务（commit）。
    返回是否实际发生了变更（用于 batch 区分 updated / skipped）。
    """
    now = utcnow()
    changed = False

    # 加载 WrongQuestion（可能不存在）
    wq_result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.question_id == question_id,
        )
    )
    wq = wq_result.scalar_one_or_none()

    # 加载所有关联的 ReviewSchedule（不存在 UNIQUE 约束，全量更新）
    sch_result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.question_id == question_id,
        )
    )
    schedules = list(sch_result.scalars().all())

    if mastered:
        # ── 收敛到已掌握 ──
        if wq:
            if not wq.mastered or wq.mastered_at is None:
                wq.mastered = True
                wq.mastered_at = now
                changed = True
        for s in schedules:
            if not s.mastered:
                s.mastered = True
                changed = True
    else:
        # ── 收敛到未掌握 ──
        if wq:
            if wq.mastered or wq.mastered_at is not None:
                wq.mastered = False
                wq.mastered_at = None
                changed = True
        for s in schedules:
            if s.mastered:
                s.mastered = False
                changed = True

        # 有 WQ（且 active）但无 schedule → 创建 schedule 恢复调度资格
        if not schedules and wq and wq.is_active:
            q_result = await db.execute(
                select(Question)
                .options(selectinload(Question.subject_ref))
                .where(Question.id == question_id)
            )
            question = q_result.scalar_one_or_none()
            subject_id = question.subject_id if question else None
            schedule = ReviewSchedule(
                user_id=user_id,
                question_id=question_id,
                subject_id=subject_id,
                interval=1,
                ease_factor=2.5,
                repetitions=0,
                next_review_at=now,
            )
            db.add(schedule)
            changed = True

    await db.flush()
    return changed


async def get_today_review(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None = None,
    limit: int = 20,
) -> dict:
    _, today_end = shanghai_today_boundaries()
    conditions = [
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.next_review_at <= today_end,
        ~ReviewSchedule.mastered,
    ]
    if subject_id:
        conditions.append(ReviewSchedule.subject_id == subject_id)

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
            select(Question).options(selectinload(Question.subject_ref)).where(Question.id.in_(question_ids))
        )
        all_questions = list(q_result.scalars().all())
        questions_map = {q.id: q for q in all_questions}

    questions = []
    for s in schedules:
        q = questions_map.get(s.question_id)
        if not q:
            continue
        content = q.content
        if isinstance(content, str):
            content = {"text": content}
        elif not isinstance(content, dict):
            content = {}
        questions.append({
            "schedule_id": s.id,
            "question_id": s.question_id,
            "subject_id": s.subject_id,
            "subject_code": q.subject_ref.code if q.subject_ref else "",
            "subject_name": q.subject_ref.name if q.subject_ref else "",
            "question_type": q.question_type,
            "stem": content.get("text", "") if isinstance(content, dict) else "",
            "options": q.options or {},
            "content": content,
            "image_url": q.image_url,
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
    *,
    auto_commit: bool = True,
    latest_wrong_answer: str | None = None,
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
        raise ValueError("题目与复习记录不匹配")

    sm2_result = calc_sm2(
        quality=rating,
        efactor=schedule.ease_factor,
        interval=schedule.interval,
        repetitions=schedule.repetitions,
        review_date=shanghai_today(),
    )

    interval_before = schedule.interval
    ef_before = schedule.ease_factor

    schedule.ease_factor = sm2_result["efactor"]
    schedule.interval = sm2_result["interval"]
    schedule.repetitions = sm2_result["repetitions"]
    schedule.next_review_at = shanghai_date_utc_range(
        sm2_result["next_review_date"]
    )[0]
    schedule.last_reviewed_at = utcnow()

    # 同步复习状态；本次仍答错时，同时刷新错题详情中的“我的错题”。
    await _sync_schedule_to_wq(
        db,
        schedule,
        latest_wrong_answer=latest_wrong_answer if rating < 3 else None,
    )

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

    if auto_commit:
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
        try:
            r = await submit_review(
                db=db,
                user_id=user_id,
                schedule_id=item["schedule_id"],
                question_id=item["question_id"],
                rating=item["rating"],
                auto_commit=False,
            )
            results.append({
                "schedule_id": r["schedule_id"],
                "question_id": r["question_id"],
                "next_review_at": r["next_review_at"],
                "is_correct": r["is_correct"],
            })
        except ValueError as e:
            # 单题失败不影响其他题目，记录错误并继续
            results.append({
                "schedule_id": item.get("schedule_id"),
                "question_id": item.get("question_id"),
                "next_review_at": None,
                "is_correct": False,
                "error": str(e),
            })
    # 单事务批量提交
    await db.commit()
    return {"results": results, "total": len(results)}


async def get_review_stats(
    db: AsyncSession,
    user_id: int,
    days: int = 7,
) -> dict:
    today = shanghai_today()
    today_start, today_end = shanghai_today_boundaries()
    since = shanghai_date_utc_range(today - timedelta(days=days - 1))[0]

    # Total scheduled
    total_q = select(func.count(ReviewSchedule.id)).where(
        ReviewSchedule.user_id == user_id
    )
    total_scheduled = (await db.execute(total_q)).scalar()

    # Reviewed today
    reviewed_today_q = select(func.count(ReviewRecord.id)).where(
        ReviewRecord.user_id == user_id,
        ReviewRecord.reviewed_at >= today_start,
        ReviewRecord.reviewed_at <= today_end,
    )
    total_reviewed_today = (await db.execute(reviewed_today_q)).scalar()

    # Remaining today (exclude mastered)
    remaining_q = select(func.count(ReviewSchedule.id)).where(
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.next_review_at <= today_end,
        ~ReviewSchedule.mastered,
    )
    remaining_today = (await db.execute(remaining_q)).scalar()

    # Overdue (next_review_at < now, not reviewed today, exclude mastered)
    overdue_q = select(func.count(ReviewSchedule.id)).where(
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.next_review_at < today_start,
        ~ReviewSchedule.mastered,
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
    from app.models.admin import Subject
    subject_result = await db.execute(
        select(
            ReviewSchedule.subject_id,
            func.count(ReviewSchedule.id).label("scheduled"),
            func.sum(
                case(
                    (and_(ReviewSchedule.next_review_at <= today_end, ~ReviewSchedule.mastered), 1), else_=0
                )
            ).label("remaining"),
        )
        .where(ReviewSchedule.user_id == user_id)
        .group_by(ReviewSchedule.subject_id)
    )

    # Reviewed by subject today
    subject_reviewed_result = await db.execute(
        select(
            ReviewSchedule.subject_id,
            func.count(func.distinct(ReviewRecord.question_id)).label("reviewed"),
        )
        .join(ReviewRecord, ReviewRecord.schedule_id == ReviewSchedule.id)
        .where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.reviewed_at >= today_start,
            ReviewRecord.reviewed_at <= today_end,
        )
        .group_by(ReviewSchedule.subject_id)
    )
    reviewed_by_subject = {
        (r[0] if r[0] is not None else 0): r[1]
        for r in subject_reviewed_result.all()
    }

    subject_rows = subject_result.all()
    subject_ids = [row[0] for row in subject_rows if row[0] is not None]
    code_name = {}
    if subject_ids:
        subs = (await db.execute(
            select(Subject).where(Subject.id.in_(subject_ids))
        )).scalars().all()
        code_name = {s.id: (s.code, s.name) for s in subs}

    by_subject = []
    for row in subject_rows:
        sid = row[0] or 0
        sched = row[1] or 0
        rem = row[2] or 0
        rev = reviewed_by_subject.get(sid, 0)
        by_subject.append({
            "subject_id": sid,
            "subject_code": code_name.get(sid, ("", ""))[0],
            "subject_name": code_name.get(sid, ("", ""))[1],
            "scheduled": sched,
            "reviewed": rev,
            "remaining": rem,
        })

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
    *,
    commit: bool = True,
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
        # 已有 schedule → 重置为困难状态
        schedule.interval = 1
        schedule.ease_factor = 2.5
        schedule.repetitions = 0
        schedule.next_review_at = utcnow()
        schedule.last_reviewed_at = None
    else:
        # 获取题目科目
        q_result = await db.execute(
            select(Question)
            .options(selectinload(Question.subject_ref))
            .where(Question.id == question_id)
        )
        question = q_result.scalar_one_or_none()
        subject_id = question.subject_id if question else None

        schedule = ReviewSchedule(
            user_id=user_id,
            question_id=question_id,
            subject_id=subject_id,
            interval=1,
            ease_factor=2.5,
            repetitions=0,
            next_review_at=utcnow(),
        )
        db.add(schedule)

    await _sync_schedule_to_wq(db, schedule)
    if commit:
        await db.commit()
        await db.refresh(schedule)
    else:
        await db.flush()
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
    await set_mastered_state(
        db, user_id=user_id, question_id=schedule.question_id, mastered=True,
    )
    await db.commit()
    await db.refresh(schedule)
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
    await set_mastered_state(
        db, user_id=user_id, question_id=schedule.question_id, mastered=False,
    )
    await db.commit()
    await db.refresh(schedule)
    return schedule


# ── Today review task flow ──


async def get_today_review_overview(
    db: AsyncSession,
    user_id: int,
) -> dict:
    """获取今日复习任务概览（入口页数据）。"""
    today_start, today_end = shanghai_today_boundaries()

    # Fetch all due schedules first, then cross-check with existing questions
    all_schedules_q = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= today_end,
        ).order_by(ReviewSchedule.next_review_at.asc(), ReviewSchedule.id.asc())
    )
    all_schedules = list(all_schedules_q.scalars().all())

    # Filter out schedules pointing to non-existent questions
    schedule_question_ids = list(set(s.question_id for s in all_schedules))
    valid_question_ids = set()
    if schedule_question_ids:
        valid_q = await db.execute(
            select(Question.id).where(Question.id.in_(schedule_question_ids))
        )
        valid_question_ids = {r[0] for r in valid_q.all()}

    valid_schedules = [s for s in all_schedules if s.question_id in valid_question_ids]
    today_due_count = len(valid_schedules)

    # Completed today: distinct questions reviewed today, limited to the due set
    completed_q = await db.execute(
        select(func.count(func.distinct(ReviewRecord.question_id))).where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.reviewed_at >= today_start,
            ReviewRecord.reviewed_at <= today_end,
        )
    )
    completed_q.scalar() or 0

    # Only count completions for questions that are in the due set
    completed_set = set()
    if valid_question_ids:
        completed_q2 = await db.execute(
            select(func.distinct(ReviewRecord.question_id)).where(
                ReviewRecord.user_id == user_id,
                ReviewRecord.reviewed_at >= today_start,
                ReviewRecord.reviewed_at <= today_end,
                ReviewRecord.question_id.in_(valid_question_ids),
            )
        )
        completed_set = {r[0] for r in completed_q2.all()}
    today_completed_count = len(completed_set)

    today_remaining_count = max(0, today_due_count - today_completed_count)

    # overdue: schedules with next_review_at < today_start, among valid schedules
    today_overdue_count = sum(1 for s in valid_schedules if s.next_review_at < today_start)
    today_new_due_count = max(0, today_due_count - today_overdue_count)

    batch_size = 10
    total_batch_count = max(1, (today_due_count + batch_size - 1) // batch_size) if today_due_count > 0 else 1
    remaining_batch_count = max(1, (today_remaining_count + batch_size - 1) // batch_size) if today_remaining_count > 0 else 0
    estimated_minutes = min(120, max(1, (today_remaining_count + 1) // 2))

    # All valid schedule IDs
    all_ids = [s.id for s in valid_schedules]

    # Remaining question IDs (not yet completed today) — at schedule level
    remaining_question_ids = [s.id for s in valid_schedules if s.question_id not in completed_set]

    current_batch_no = 1
    if today_completed_count > 0:
        current_batch_no = (today_completed_count // batch_size) + 1
        if current_batch_no > total_batch_count:
            current_batch_no = total_batch_count

    return {
        "date": datetime.now(_SHANGHAI_TZ).strftime("%Y-%m-%d"),
        "today_due_count": today_due_count,
        "today_completed_count": today_completed_count,
        "today_remaining_count": today_remaining_count,
        "today_overdue_count": today_overdue_count,
        "today_new_due_count": today_new_due_count,
        "estimated_minutes": estimated_minutes,
        "batch_size": batch_size,
        "current_batch_no": current_batch_no,
        "total_batch_count": total_batch_count,
        "remaining_batch_count": remaining_batch_count,
        "all_question_ids": all_ids,
        "completed_question_ids": sorted(completed_set),
        "remaining_question_ids": remaining_question_ids,
        "has_due_review": today_due_count > 0,
        "is_completed": today_due_count > 0 and today_remaining_count == 0,
    }


async def get_next_today_review_batch(
    db: AsyncSession,
    user_id: int,
    batch_size: int = 10,
) -> dict:
    """获取今日下一组待复习题。"""
    today_start, today_end = shanghai_today_boundaries()

    # Query due schedules
    conditions = [
        ReviewSchedule.user_id == user_id,
        ~ReviewSchedule.mastered,
        ReviewSchedule.next_review_at <= today_end,
    ]

    q = (
        select(ReviewSchedule)
        .where(and_(*conditions))
        .order_by(ReviewSchedule.next_review_at.asc(), ReviewSchedule.id.asc())
    )
    result = await db.execute(q)
    all_schedules = list(result.scalars().all())

    # Cross-check with existing questions (filter out schedules pointing to deleted questions)
    schedule_question_ids = list(set(s.question_id for s in all_schedules))
    valid_question_ids = set()
    if schedule_question_ids:
        valid_q = await db.execute(
            select(Question.id).where(Question.id.in_(schedule_question_ids))
        )
        valid_question_ids = {r[0] for r in valid_q.all()}
    valid_schedules = [s for s in all_schedules if s.question_id in valid_question_ids]

    # Get questions already reviewed today (by question_id), scoped to due set
    done_q_result = await db.execute(
        select(func.distinct(ReviewRecord.question_id)).where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.reviewed_at >= today_start,
            ReviewRecord.reviewed_at <= today_end,
            ReviewRecord.question_id.in_(valid_question_ids) if valid_question_ids else True,
        )
    )
    done_question_ids = {r[0] for r in done_q_result.all()}

    # Filter out already-reviewed questions
    pending = [s for s in valid_schedules if s.question_id not in done_question_ids]
    batch = pending[:batch_size]

    # Build question data (same as get_today_review)
    question_ids = [s.question_id for s in batch]
    questions_map = {}
    if question_ids:
        q_result = await db.execute(
            select(Question).options(selectinload(Question.subject_ref)).where(Question.id.in_(question_ids))
        )
        questions_map = {q.id: q for q in q_result.scalars().all()}

    questions = []
    for s in batch:
        q = questions_map.get(s.question_id)
        if not q:
            continue
        content = q.content
        if isinstance(content, str):
            content = {"text": content}
        elif not isinstance(content, dict):
            content = {}
        questions.append({
            "schedule_id": s.id,
            "question_id": s.question_id,
            "subject_id": s.subject_id,
            "subject_code": q.subject_ref.code if q.subject_ref else "",
            "subject_name": q.subject_ref.name if q.subject_ref else "",
            "question_type": q.question_type,
            "stem": content.get("text", "") if isinstance(content, dict) else "",
            "options": q.options or {},
            "content": content,
            "image_url": q.image_url,
            "interval": s.interval,
            "repetitions": s.repetitions,
            "ease_factor": s.ease_factor,
        })

    due_count = len(valid_schedules)
    completed_count = len(done_question_ids)
    remaining_count = max(0, due_count - completed_count)
    total_batch_count = max(1, (due_count + batch_size - 1) // batch_size) if due_count > 0 else 1

    # Calculate current batch_no
    completed_before = len([s for s in valid_schedules if s.question_id in done_question_ids])
    batch_no = (completed_before // batch_size) + 1
    if batch_no > total_batch_count:
        batch_no = total_batch_count

    date_str = datetime.now(_SHANGHAI_TZ).strftime("%Y%m%d")
    session_id = f"review_{date_str}_{user_id}"
    group_id = f"{session_id}_batch_{batch_no}"

    return {
        "session_id": session_id,
        "group_id": group_id,
        "batch_no": batch_no,
        "total_batch_count": total_batch_count,
        "batch_size": len(questions),
        "today_due_count": due_count,
        "today_completed_count": completed_count,
        "today_remaining_count": remaining_count,
        "questions": questions,
    }


async def get_today_review_result(
    db: AsyncSession,
    user_id: int,
) -> dict:
    """获取今日复习最终结果。"""
    today_start, today_end = shanghai_today_boundaries()
    tomorrow_start = today_end + timedelta(microseconds=1)

    # All review records from today
    result = await db.execute(
        select(ReviewRecord).where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.reviewed_at >= today_start,
            ReviewRecord.reviewed_at <= today_end,
        )
    )
    records = list(result.scalars().all())

    # Deduplicate by question_id (same question shouldn't be double-counted)
    seen_q = set()
    unique = []
    for r in records:
        if r.question_id not in seen_q:
            seen_q.add(r.question_id)
            unique.append(r)

    correct_count = sum(1 for r in unique if r.rating >= 3)
    wrong_count = sum(1 for r in unique if r.rating < 3)
    skipped_count = 0  # backend doesn't explicitly record "skip"
    total_unique = len(unique)
    accuracy = round(correct_count / total_unique, 4) if total_unique > 0 else 0.0

    # Mastered count today
    mastered_q = await db.execute(
        select(func.count(ReviewSchedule.id)).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.mastered,
            ReviewSchedule.updated_at >= today_start,
        )
    )
    mastered_count = mastered_q.scalar() or 0

    # Subject stats
    from app.models.admin import Subject
    schedule_ids = [r.schedule_id for r in unique]
    subject_map: dict[int, dict] = {}
    if schedule_ids:
        sched_result = await db.execute(
            select(ReviewSchedule.id, ReviewSchedule.subject_id).where(
                ReviewSchedule.id.in_(schedule_ids),
                ReviewSchedule.user_id == user_id,
            )
        )
        schedule_subject = {sid: subj_id for sid, subj_id in sched_result.all()}
        subject_ids = [v for v in schedule_subject.values() if v is not None]
        code_name = {}
        if subject_ids:
            subs = (await db.execute(
                select(Subject).where(Subject.id.in_(subject_ids))
            )).scalars().all()
            code_name = {s.id: (s.code, s.name) for s in subs}
        for r in unique:
            subj_id = schedule_subject.get(r.schedule_id)
            if subj_id is None:
                subj_id = 0
            entry = subject_map.setdefault(
                subj_id, {"subject_id": subj_id,
                          "subject_code": code_name.get(subj_id, ("", ""))[0],
                          "subject_name": code_name.get(subj_id, ("", ""))[1],
                          "reviewed": 0, "correct": 0, "wrong": 0, "skipped": 0}
            )
            entry["reviewed"] += 1
            if r.rating >= 3:
                entry["correct"] += 1
            else:
                entry["wrong"] += 1

    subject_stats = [v for v in subject_map.values()]

    # Tomorrow's due count
    tomorrow_end = tomorrow_start + timedelta(days=1) - timedelta(microseconds=1)
    tomorrow_q = await db.execute(
        select(func.count(ReviewSchedule.id)).where(
            ReviewSchedule.user_id == user_id,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at >= tomorrow_start,
            ReviewSchedule.next_review_at <= tomorrow_end,
        )
    )
    tomorrow_due_count = tomorrow_q.scalar() or 0

    # today's counts
    due_q = await db.execute(
        select(func.count(ReviewSchedule.id)).where(
            ReviewSchedule.user_id == user_id,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= today_end,
        )
    )
    today_due_count = due_q.scalar() or 0

    today_completed_count = len(seen_q)
    completion_rate = round(today_completed_count / today_due_count, 4) if today_due_count > 0 else 0.0
    is_completed = today_due_count > 0 and today_completed_count >= today_due_count

    return {
        "date": datetime.now(_SHANGHAI_TZ).strftime("%Y-%m-%d"),
        "today_due_count": today_due_count,
        "today_completed_count": today_completed_count,
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "skipped_count": skipped_count,
        "mastered_count": mastered_count,
        "accuracy": accuracy,
        "completion_rate": completion_rate,
        "updated_schedule_count": today_completed_count,
        "tomorrow_due_count": tomorrow_due_count,
        "subject_stats": subject_stats,
        "is_completed": is_completed,
    }
