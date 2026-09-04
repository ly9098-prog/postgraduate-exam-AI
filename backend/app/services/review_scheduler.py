from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.time_utils import (
    shanghai_date_utc_range,
    shanghai_today,
    shanghai_today_boundaries,
    utcnow,
)
from app.models.question import Question
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.wrong_question import WrongQuestion
from app.services.sm2_service import calc_sm2

# Asia/Shanghai = UTC+8, no DST
_SHANGHAI_TZ = timezone(timedelta(hours=8))


async def lock_question_review_state(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
) -> None:
    """Serialize one user's state transitions for a question on PostgreSQL.

    ReviewSchedule/WrongQuestion historically have no database UNIQUE constraint on
    ``(user_id, question_id)``.  Every creation/update entrypoint therefore takes
    the same transaction-scoped advisory lock before checking or creating rows.
    This prevents new duplicates and also makes review submission idempotency work
    across historical duplicate schedule IDs.  SQLite is only a development
    fallback and has no PostgreSQL advisory-lock equivalent, so it is a no-op there.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Use PostgreSQL's two-int advisory-lock form so asyncpg never has to infer a
    # 64-bit bind parameter from a Python int.  Masking only affects unrealistically
    # large IDs; any collision merely serializes unrelated work and cannot corrupt
    # state.
    lock_user = int(user_id) & 0x7FFFFFFF
    lock_question = int(question_id) & 0x7FFFFFFF
    await db.execute(
        select(func.pg_advisory_xact_lock(lock_user, lock_question))
    )


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
    wrong_questions = list(result.scalars().all())
    for wq in wrong_questions:
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
    await lock_question_review_state(
        db, user_id=user_id, question_id=question_id
    )
    now = utcnow()
    changed = False

    # 加载 WrongQuestion（可能不存在）
    wq_result = await db.execute(
        select(WrongQuestion)
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.question_id == question_id,
        )
        .order_by(WrongQuestion.id.asc())
    )
    wrong_questions = list(wq_result.scalars().all())
    wq = wrong_questions[0] if wrong_questions else None

    # 加载所有关联的 ReviewSchedule（不存在 UNIQUE 约束，全量更新）
    sch_result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.question_id == question_id,
        )
    )
    schedules = list(sch_result.scalars().all())

    # mastered 是“是否继续进入正常复习”的状态；复习掌握度由
    # UserQuestionState 独立记录，只能由实际答题表现改变。手动标记/撤销掌握
    # 不应抬高或降低 box_level，否则百分比会被按钮操作伪造。
    if mastered:
        # ── 收敛到已掌握 ──
        for wrong_question in wrong_questions:
            if not wrong_question.mastered or wrong_question.mastered_at is None:
                wrong_question.mastered = True
                wrong_question.mastered_at = now
                changed = True
        for s in schedules:
            if not s.mastered:
                s.mastered = True
                changed = True
    else:
        # ── 收敛到未掌握 ──
        for wrong_question in wrong_questions:
            if wrong_question.mastered or wrong_question.mastered_at is not None:
                wrong_question.mastered = False
                wrong_question.mastered_at = None
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


async def sync_mastery_from_question_state(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
    is_correct: bool,
) -> dict:
    """按 UserQuestionState 收敛 WrongQuestion/ReviewSchedule 的掌握状态。

    答对达到 80% 自动掌握；任何一次答错都取消掌握。未达到阈值的答对
    不会强制撤销已有手动掌握状态。
    """
    from app.services import question_review_service

    mastery = await question_review_service.get_user_question_mastery(
        db, user_id, question_id
    )
    if not is_correct:
        await set_mastered_state(
            db, user_id=user_id, question_id=question_id, mastered=False
        )
        mastered = False
    elif mastery["auto_mastered"]:
        await set_mastered_state(
            db, user_id=user_id, question_id=question_id, mastered=True
        )
        mastered = True
    else:
        result = await db.execute(
            select(WrongQuestion.mastered).where(
                WrongQuestion.user_id == user_id,
                WrongQuestion.question_id == question_id,
            )
        )
        mastered = bool(result.scalars().first())

    return {**mastery, "mastered": mastered}


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

    count_q = select(func.count(func.distinct(ReviewSchedule.question_id))).where(
        and_(*conditions)
    )
    total = (await db.execute(count_q)).scalar() or 0

    # 旧数据可能同题存在多个 schedule。先按到期时间稳定排序，再按 question_id
    # 去重后应用 limit，避免重复记录挤占返回名额。
    q = (
        select(ReviewSchedule)
        .where(and_(*conditions))
        .order_by(ReviewSchedule.next_review_at.asc(), ReviewSchedule.id.asc())
    )
    result = await db.execute(q)
    schedules = []
    seen_question_ids: set[int] = set()
    for candidate in result.scalars().all():
        if candidate.question_id in seen_question_ids:
            continue
        seen_question_ids.add(candidate.question_id)
        schedules.append(candidate)
        if len(schedules) >= limit:
            break

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


async def _get_today_record_for_question(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
) -> ReviewRecord | None:
    """Return today's latest successful review record for this question.

    Idempotency is intentionally keyed by ``(user_id, question_id, local day)``
    rather than schedule_id because historical data may contain multiple schedules
    for the same question.  A stale client submitting another duplicate schedule ID
    must still resolve to the first real attempt instead of advancing mastery twice.
    """
    today_start, today_end = shanghai_today_boundaries()
    result = await db.execute(
        select(ReviewRecord)
        .where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.question_id == question_id,
            ReviewRecord.reviewed_at >= today_start,
            ReviewRecord.reviewed_at <= today_end,
        )
        .order_by(ReviewRecord.reviewed_at.desc(), ReviewRecord.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def _current_mastered_state(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
) -> bool:
    result = await db.execute(
        select(WrongQuestion.mastered).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.question_id == question_id,
        )
    )
    return bool(result.scalars().first())


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

    # 先按 user + question 获取 PostgreSQL 事务级 advisory lock，再锁当前
    # schedule。题目级锁可以把两个历史重复 schedule_id 的并发提交也串行化。
    await lock_question_review_state(
        db, user_id=user_id, question_id=question_id
    )
    result = await db.execute(
        select(ReviewSchedule)
        .where(
            ReviewSchedule.id == schedule_id,
            ReviewSchedule.user_id == user_id,
        )
        .with_for_update()
    )
    schedule = result.scalars().first()
    if not schedule:
        raise ValueError(f"复习记录不存在: {schedule_id}")
    if schedule.question_id != question_id:
        raise ValueError("题目与复习记录不匹配")

    existing_record = await _get_today_record_for_question(
        db,
        user_id=user_id,
        question_id=question_id,
    )
    if (
        existing_record is not None
        and schedule.next_review_at is not None
        and schedule.next_review_at > utcnow()
    ):
        # schedule 已被上一次提交推进到未来时，相同评分视为网络重试，直接返回
        # 第一次结果；不同评分则拒绝二次覆盖。若用户之后主动“重新加入复习”
        # 把 next_review_at 拉回当前时间，则允许同日再次真实作答。
        if existing_record.rating != rating:
            raise ValueError("该题本轮复习结果已提交，请勿重复评分")

        from app.services import question_review_service

        mastery = await question_review_service.get_user_question_mastery(
            db, user_id, question_id
        )
        return {
            "schedule_id": existing_record.schedule_id or schedule.id,
            "question_id": question_id,
            "rating": existing_record.rating,
            "interval_after": existing_record.interval_after or schedule.interval,
            "ease_factor_after": existing_record.ease_factor_after or schedule.ease_factor,
            "next_review_at": schedule.next_review_at,
            "is_correct": existing_record.rating >= 3,
            "mastery_percent": mastery["mastery_percent"],
            "mastered": await _current_mastered_state(
                db, user_id=user_id, question_id=question_id
            ),
            "already_submitted": True,
        }

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

    # 历史数据可能存在同题多个 ReviewSchedule。一次真实复习后同步它们的
    # SM-2 核心字段，防止未被选中的旧 schedule 仍停留在过去并于次日重复入队。
    duplicate_result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.question_id == question_id,
            ReviewSchedule.id != schedule.id,
        )
    )
    for duplicate in duplicate_result.scalars().all():
        duplicate.ease_factor = schedule.ease_factor
        duplicate.interval = schedule.interval
        duplicate.repetitions = schedule.repetitions
        duplicate.next_review_at = schedule.next_review_at
        duplicate.last_reviewed_at = schedule.last_reviewed_at

    # 复习作答必须和普通练习一样更新 UserQuestionState，否则错题掌握度会停滞。
    from app.services import question_review_service

    is_correct = rating >= 3
    await question_review_service.update_user_question_state_after_answer(
        db,
        user_id,
        question_id,
        is_correct,
        answered_at=schedule.last_reviewed_at,
    )
    mastery_state = await sync_mastery_from_question_state(
        db,
        user_id=user_id,
        question_id=question_id,
        is_correct=is_correct,
    )

    # 同步复习状态；本次仍答错时，同时刷新错题详情中的“我的错题”。
    await _sync_schedule_to_wq(
        db,
        schedule,
        latest_wrong_answer=latest_wrong_answer if not is_correct else None,
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
        "is_correct": is_correct,
        "mastery_percent": mastery_state["mastery_percent"],
        "mastered": mastery_state["mastered"],
        "already_submitted": False,
    }


async def batch_submit_review(
    db: AsyncSession,
    user_id: int,
    reviews: list[dict],
) -> dict:
    # auto_commit=False keeps one transaction open for the whole batch.  Acquire
    # per-question locks in a stable order to avoid advisory-lock deadlocks when
    # two clients submit overlapping batches concurrently, while preserving the
    # caller's result order.
    indexed_reviews = list(enumerate(reviews))
    ordered_reviews = sorted(
        indexed_reviews,
        key=lambda pair: (
            int(pair[1].get("question_id") or 0),
            int(pair[1].get("schedule_id") or 0),
            pair[0],
        ),
    )
    indexed_results: list[tuple[int, dict]] = []
    for original_index, item in ordered_reviews:
        try:
            r = await submit_review(
                db=db,
                user_id=user_id,
                schedule_id=item["schedule_id"],
                question_id=item["question_id"],
                rating=item["rating"],
                auto_commit=False,
            )
            payload = {
                "schedule_id": r["schedule_id"],
                "question_id": r["question_id"],
                "success": True,
                "error": None,
                "next_review_at": r["next_review_at"],
                "is_correct": r["is_correct"],
                "mastery_percent": r["mastery_percent"],
                "mastered": r["mastered"],
            }
        except ValueError as e:
            # 单题失败不影响其他题目，记录错误并继续
            payload = {
                "schedule_id": item.get("schedule_id"),
                "question_id": item.get("question_id"),
                "success": False,
                "error": str(e),
                "next_review_at": None,
                "is_correct": False,
            }
        indexed_results.append((original_index, payload))

    await db.commit()
    results = [payload for _, payload in sorted(indexed_results, key=lambda x: x[0])]
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
    total_q = select(func.count(func.distinct(ReviewSchedule.question_id))).where(
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
    remaining_q = select(func.count(func.distinct(ReviewSchedule.question_id))).where(
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.next_review_at <= today_end,
        ~ReviewSchedule.mastered,
    )
    remaining_today = (await db.execute(remaining_q)).scalar()

    # Overdue (next_review_at < now, not reviewed today, exclude mastered)
    overdue_q = select(func.count(func.distinct(ReviewSchedule.question_id))).where(
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
            func.count(func.distinct(ReviewSchedule.question_id)).label("scheduled"),
            func.count(
                func.distinct(
                    case(
                        (
                            and_(
                                ReviewSchedule.next_review_at <= today_end,
                                ~ReviewSchedule.mastered,
                            ),
                            ReviewSchedule.question_id,
                        ),
                        else_=None,
                    )
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
    """错题自动进入复习调度，首次复习从北京时间次日开始。

    ``utcnow()`` 仍用于记录真实发生时间；复习调度属于“日历日”业务，
    因此必须先按 Asia/Shanghai 确定次日，再转换成数据库使用的 naive UTC。
    这样当天新产生的错题只进入错题池，不会被当天的“今日复习”查询命中。
    """
    await lock_question_review_state(
        db, user_id=user_id, question_id=question_id
    )

    first_review_date = shanghai_today() + timedelta(days=1)
    first_review_at = shanghai_date_utc_range(first_review_date)[0]

    result = await db.execute(
        select(ReviewSchedule)
        .where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.question_id == question_id,
        )
        .order_by(ReviewSchedule.id.asc())
    )
    schedules = list(result.scalars().all())
    schedule = schedules[0] if schedules else None

    if schedule:
        # 历史数据可能存在重复 schedule。重新做错时应统一重置全部记录，
        # 不能用 scalar_one_or_none() 因重复数据直接抛 MultipleResultsFound。
        for existing_schedule in schedules:
            existing_schedule.interval = 1
            existing_schedule.ease_factor = 2.5
            existing_schedule.repetitions = 0
            existing_schedule.next_review_at = first_review_at
            existing_schedule.last_reviewed_at = None
            existing_schedule.mastered = False
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
            next_review_at=first_review_at,
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


async def _get_today_review_task_state(
    db: AsyncSession,
    user_id: int,
) -> dict:
    """构建稳定的“今日复习任务集合”。

    ``ReviewSchedule.next_review_at`` 会在提交后立即推进到未来。如果今日统计
    只实时查询 ``next_review_at <= today_end``，已完成题会从集合中消失，导致
    重新进入页面后总数、完成数和批次号缩水。

    因此将三类 schedule 合并：
    1. 当前仍到期且未掌握；
    2. 今天已经产生 ReviewRecord 的 schedule；
    3. 今天从到期状态被标记为掌握的 schedule。

    最终按 question_id 去重，兼容历史重复 schedule。该方案不需要新增表或
    数据库迁移，并让 overview / next-batch / result 使用同一套任务口径。
    """
    today_start, today_end = shanghai_today_boundaries()

    due_result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= today_end,
        )
    )
    due_schedules = list(due_result.scalars().all())

    reviewed_result = await db.execute(
        select(
            ReviewRecord.schedule_id,
            ReviewRecord.question_id,
        ).where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.reviewed_at >= today_start,
            ReviewRecord.reviewed_at <= today_end,
        )
    )
    reviewed_rows = list(reviewed_result.all())
    reviewed_schedule_ids = {
        schedule_id for schedule_id, _ in reviewed_rows if schedule_id is not None
    }
    reviewed_question_ids = {question_id for _, question_id in reviewed_rows}

    reviewed_schedules: list[ReviewSchedule] = []
    if reviewed_schedule_ids:
        reviewed_schedule_result = await db.execute(
            select(ReviewSchedule).where(
                ReviewSchedule.user_id == user_id,
                ReviewSchedule.id.in_(reviewed_schedule_ids),
            )
        )
        reviewed_schedules = list(reviewed_schedule_result.scalars().all())

    # 标记掌握不会产生 ReviewRecord，但该题仍属于今天原有任务，并应从剩余数
    # 中移除。master 操作不会改 next_review_at，因此仍可判断它原本是否今日到期。
    mastered_result = await db.execute(
        select(ReviewSchedule)
        .join(
            WrongQuestion,
            and_(
                WrongQuestion.user_id == ReviewSchedule.user_id,
                WrongQuestion.question_id == ReviewSchedule.question_id,
            ),
        )
        .where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= today_end,
            ReviewSchedule.updated_at >= today_start,
            ReviewSchedule.updated_at <= today_end,
            WrongQuestion.is_active,
            WrongQuestion.mastered,
        )
    )
    mastered_schedules = list(mastered_result.scalars().all())

    # 先按 schedule_id 合并，再按 question_id 去重，避免同一道题存在历史重复
    # schedule 时出现重复题、总数虚高、remaining 永远无法归零的问题。
    schedule_by_id: dict[int, ReviewSchedule] = {}
    for schedule in due_schedules + reviewed_schedules + mastered_schedules:
        schedule_by_id[schedule.id] = schedule

    candidate_schedules = list(schedule_by_id.values())
    candidate_question_ids = {s.question_id for s in candidate_schedules}

    # 删除题目留下的孤儿 schedule 不进入今日任务。
    valid_question_ids: set[int] = set()
    if candidate_question_ids:
        valid_q = await db.execute(
            select(Question.id).where(Question.id.in_(candidate_question_ids))
        )
        valid_question_ids = {row[0] for row in valid_q.all()}

    def _sort_key(schedule: ReviewSchedule):
        # 已完成题的 next_review_at 可能已推进到未来；这里只要求排序稳定。
        return (schedule.next_review_at or today_end, schedule.id)

    task_schedules: list[ReviewSchedule] = []
    seen_question_ids: set[int] = set()
    for schedule in sorted(candidate_schedules, key=_sort_key):
        if schedule.question_id not in valid_question_ids:
            continue
        if schedule.question_id in seen_question_ids:
            continue
        seen_question_ids.add(schedule.question_id)
        task_schedules.append(schedule)

    task_question_ids = {s.question_id for s in task_schedules}
    # 自动掌握发生在 submit_review 内：schedule 会先推进到未来，再同步 mastered=True。
    # 这类题虽然不会命中上面的“今日到期 mastered_schedules”查询，但会通过
    # ReviewRecord 进入 task_schedules，因此应直接按今日任务集合中的当前状态统计。
    # ReviewSchedule.mastered is also used internally to suppress inactive/removed
    # wrong questions from the queue, so it cannot by itself mean "user mastered".
    # Count mastery only when the active WrongQuestion carries the mastered state.
    mastered_question_ids: set[int] = set()
    if task_question_ids:
        mastered_wq_result = await db.execute(
            select(func.distinct(WrongQuestion.question_id)).where(
                WrongQuestion.user_id == user_id,
                WrongQuestion.question_id.in_(task_question_ids),
                WrongQuestion.is_active,
                WrongQuestion.mastered,
            )
        )
        mastered_question_ids = {row[0] for row in mastered_wq_result.all()}

    completed_question_ids = (
        reviewed_question_ids | mastered_question_ids
    ) & task_question_ids

    pending_schedules = [
        s
        for s in task_schedules
        if s.question_id not in completed_question_ids and not s.mastered
    ]

    return {
        "today_start": today_start,
        "today_end": today_end,
        "task_schedules": task_schedules,
        "pending_schedules": pending_schedules,
        "task_question_ids": task_question_ids,
        "completed_question_ids": completed_question_ids,
        "mastered_question_ids": mastered_question_ids,
    }


async def get_today_review_overview(
    db: AsyncSession,
    user_id: int,
) -> dict:
    """获取今日复习任务概览（入口页数据）。"""
    state = await _get_today_review_task_state(db, user_id)
    today_start = state["today_start"]
    task_schedules = state["task_schedules"]
    pending_schedules = state["pending_schedules"]
    completed_set = state["completed_question_ids"]

    today_due_count = len(task_schedules)
    today_remaining_count = len(pending_schedules)
    today_completed_count = max(0, today_due_count - today_remaining_count)

    # 逾期/今日新增描述“当前仍未完成”的任务，完成后不会继续制造入口页压力。
    today_overdue_count = sum(
        1
        for s in pending_schedules
        if s.next_review_at is not None and s.next_review_at < today_start
    )
    today_new_due_count = max(0, today_remaining_count - today_overdue_count)

    batch_size = 10
    total_batch_count = (
        max(1, (today_due_count + batch_size - 1) // batch_size)
        if today_due_count > 0
        else 1
    )
    remaining_batch_count = (
        max(1, (today_remaining_count + batch_size - 1) // batch_size)
        if today_remaining_count > 0
        else 0
    )
    estimated_minutes = (
        min(120, max(1, (today_remaining_count + 1) // 2))
        if today_remaining_count > 0
        else 0
    )

    current_batch_no = 1
    if today_completed_count > 0:
        current_batch_no = (today_completed_count // batch_size) + 1
        current_batch_no = min(current_batch_no, total_batch_count)

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
        # 保持已有接口兼容：all/remaining 继续返回 schedule_id；completed 返回 question_id。
        "all_question_ids": [s.id for s in task_schedules],
        "completed_question_ids": sorted(completed_set),
        "remaining_question_ids": [s.id for s in pending_schedules],
        "has_due_review": today_due_count > 0,
        "is_completed": today_due_count > 0 and today_remaining_count == 0,
    }


async def get_next_today_review_batch(
    db: AsyncSession,
    user_id: int,
    batch_size: int = 10,
) -> dict:
    """获取今日下一组待复习题。"""
    state = await _get_today_review_task_state(db, user_id)
    task_schedules = state["task_schedules"]
    pending = state["pending_schedules"]

    batch = pending[:batch_size]

    question_ids = [s.question_id for s in batch]
    questions_map = {}
    if question_ids:
        q_result = await db.execute(
            select(Question)
            .options(selectinload(Question.subject_ref))
            .where(Question.id.in_(question_ids))
        )
        questions_map = {q.id: q for q in q_result.scalars().all()}

    questions = []
    for schedule in batch:
        question = questions_map.get(schedule.question_id)
        if not question:
            continue
        content = question.content
        if isinstance(content, str):
            content = {"text": content}
        elif not isinstance(content, dict):
            content = {}
        questions.append({
            "schedule_id": schedule.id,
            "question_id": schedule.question_id,
            "subject_id": schedule.subject_id,
            "subject_code": question.subject_ref.code if question.subject_ref else "",
            "subject_name": question.subject_ref.name if question.subject_ref else "",
            "question_type": question.question_type,
            "stem": content.get("text", "") if isinstance(content, dict) else "",
            "options": question.options or {},
            "content": content,
            "image_url": question.image_url,
            "interval": schedule.interval,
            "repetitions": schedule.repetitions,
            "ease_factor": schedule.ease_factor,
        })

    due_count = len(task_schedules)
    remaining_count = len(pending)
    completed_count = max(0, due_count - remaining_count)
    total_batch_count = (
        max(1, (due_count + batch_size - 1) // batch_size)
        if due_count > 0
        else 1
    )

    batch_no = (completed_count // batch_size) + 1
    batch_no = min(batch_no, total_batch_count)

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
    state = await _get_today_review_task_state(db, user_id)
    today_start = state["today_start"]
    today_end = state["today_end"]
    task_question_ids = state["task_question_ids"]
    task_schedules = state["task_schedules"]
    pending_schedules = state["pending_schedules"]
    mastered_question_ids = state["mastered_question_ids"]
    tomorrow_start = today_end + timedelta(microseconds=1)

    # 只统计属于今日任务集合的复习记录，避免其他入口同日写入 ReviewRecord
    # 时污染“今日复习”的准确率与学科统计。若同题同日被重复提交，取最新一次。
    records: list[ReviewRecord] = []
    if task_question_ids:
        result = await db.execute(
            select(ReviewRecord)
            .where(
                ReviewRecord.user_id == user_id,
                ReviewRecord.reviewed_at >= today_start,
                ReviewRecord.reviewed_at <= today_end,
                ReviewRecord.question_id.in_(task_question_ids),
            )
            .order_by(ReviewRecord.reviewed_at.desc(), ReviewRecord.id.desc())
        )
        records = list(result.scalars().all())

    seen_q: set[int] = set()
    unique: list[ReviewRecord] = []
    for record in records:
        if record.question_id in seen_q:
            continue
        seen_q.add(record.question_id)
        unique.append(record)

    correct_count = sum(1 for record in unique if record.rating >= 3)
    wrong_count = sum(1 for record in unique if record.rating < 3)
    skipped_count = 0  # backend doesn't explicitly record "skip"
    total_unique = len(unique)
    accuracy = round(correct_count / total_unique, 4) if total_unique > 0 else 0.0
    mastered_count = len(mastered_question_ids)

    # Subject stats
    from app.models.admin import Subject

    schedule_ids = [
        record.schedule_id for record in unique if record.schedule_id is not None
    ]
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
            subs = (
                await db.execute(select(Subject).where(Subject.id.in_(subject_ids)))
            ).scalars().all()
            code_name = {subject.id: (subject.code, subject.name) for subject in subs}

        for record in unique:
            subj_id = schedule_subject.get(record.schedule_id)
            if subj_id is None:
                subj_id = 0
            entry = subject_map.setdefault(
                subj_id,
                {
                    "subject_id": subj_id,
                    "subject_code": code_name.get(subj_id, ("", ""))[0],
                    "subject_name": code_name.get(subj_id, ("", ""))[1],
                    "reviewed": 0,
                    "correct": 0,
                    "wrong": 0,
                    "skipped": 0,
                },
            )
            entry["reviewed"] += 1
            if record.rating >= 3:
                entry["correct"] += 1
            else:
                entry["wrong"] += 1

    subject_stats = list(subject_map.values())

    tomorrow_end = tomorrow_start + timedelta(days=1) - timedelta(microseconds=1)
    tomorrow_q = await db.execute(
        select(func.count(func.distinct(ReviewSchedule.question_id))).where(
            ReviewSchedule.user_id == user_id,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at >= tomorrow_start,
            ReviewSchedule.next_review_at <= tomorrow_end,
        )
    )
    tomorrow_due_count = tomorrow_q.scalar() or 0

    today_due_count = len(task_schedules)
    today_remaining_count = len(pending_schedules)
    today_completed_count = max(0, today_due_count - today_remaining_count)
    completion_rate = (
        round(today_completed_count / today_due_count, 4)
        if today_due_count > 0
        else 0.0
    )
    is_completed = today_due_count > 0 and today_remaining_count == 0

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
