from datetime import datetime, timedelta

from sqlalchemy import String, Float, and_, case, cast, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Subject
from app.models.question import Question
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.user_question_state import UserQuestionState
from app.models.wrong_question import WrongQuestion
from app.core.time_utils import shanghai_today_boundaries, utcnow
from app.services.admin_subject_service import resolve_subject_ids


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
        # If soft-deleted, reactivate
        if not wq.is_active:
            wq.is_active = True
            wq.removed_at = None
            wq.mastered = False
            wq.mastered_at = None
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
    from app.services import review_scheduler
    await review_scheduler.auto_schedule_wrong_question(db, user_id, question_id)

    await db.refresh(wq)
    return wq


async def list_wrong(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    error_type: str | None = None,
    topic: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[WrongQuestion], int]:
    conditions = [WrongQuestion.user_id == user_id, WrongQuestion.is_active == True]
    if error_type:
        conditions.append(WrongQuestion.error_type == error_type)

    # Determine whether we need to join Question table
    needs_join = bool(subject) or bool(topic)

    if needs_join:
        base_query = select(WrongQuestion).join(Question, WrongQuestion.question_id == Question.id)
        count_query = select(func.count(WrongQuestion.id)).join(Question, WrongQuestion.question_id == Question.id)
        if subject:
            subject_ids = await resolve_subject_ids(db, subject)
            base_query = base_query.where(Question.subject_id.in_(subject_ids))
            count_query = count_query.where(Question.subject_id.in_(subject_ids))
        if topic:
            topic_filter = cast(Question.knowledge_points, String).contains(topic)
            base_query = base_query.where(topic_filter)
            count_query = count_query.where(topic_filter)
        base_query = base_query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))
        total = (await db.execute(count_query)).scalar()
        q = base_query.order_by(WrongQuestion.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
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
            WrongQuestion.id == wq_id,
            WrongQuestion.user_id == user_id,
            WrongQuestion.is_active == True,
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
    conditions = [WrongQuestion.user_id == user_id, WrongQuestion.is_active == True]
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
        select(Subject.code.label("subject"), func.count(WrongQuestion.id).label("cnt"))
        .join(Question, WrongQuestion.question_id == Question.id)
        .join(Subject, Question.subject_id == Subject.id)
        .where(and_(*conditions))
        .group_by(Question.subject_id, Subject.code)
    )

    by_subject = [{"subject": r[0], "count": r[1]} for r in result3.all()]

    unmastered_q = select(func.count(WrongQuestion.id)).where(
        WrongQuestion.user_id == user_id,
        WrongQuestion.is_active == True,
        WrongQuestion.mastered == False,
    )
    unmastered = (await db.execute(unmastered_q)).scalar() or 0

    mastered_q = select(func.count(WrongQuestion.id)).where(
        WrongQuestion.user_id == user_id,
        WrongQuestion.is_active == True,
        WrongQuestion.mastered == True,
    )
    mastered = (await db.execute(mastered_q)).scalar() or 0

    hf_q = select(func.count(WrongQuestion.id)).where(
        WrongQuestion.user_id == user_id,
        WrongQuestion.is_active == True,
        WrongQuestion.mastered == False,
        WrongQuestion.review_count >= 3,
    )
    high_frequency_count = (await db.execute(hf_q)).scalar() or 0

    # today_due_count: same definition as get_today_review_overview
    _, today_end = shanghai_today_boundaries()
    today_due_q = await db.execute(
        select(func.count(func.distinct(ReviewSchedule.question_id))).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.mastered == False,
            ReviewSchedule.next_review_at <= today_end,
            ReviewSchedule.question_id.in_(
                select(WrongQuestion.question_id).where(
                    WrongQuestion.user_id == user_id,
                    WrongQuestion.is_active == True,
                )
            ),
        )
    )
    today_due_count = today_due_q.scalar() or 0

    return {
        "total": total,
        "unmastered": unmastered,
        "mastered": mastered,
        "high_frequency_count": high_frequency_count,
        "today_due_count": today_due_count,
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


# ── Enhanced list query with correlated subqueries ──


async def list_wrong_enriched(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    error_type: str | None = None,
    topic: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """Enhanced WQ list avoiding N+1 via correlated scalar subqueries."""

    conditions = [WrongQuestion.user_id == user_id, WrongQuestion.is_active == True]
    if error_type:
        conditions.append(WrongQuestion.error_type == error_type)

    # Correlated subqueries
    review_record_sub = (
        select(func.count(ReviewRecord.id))
        .where(ReviewRecord.question_id == WrongQuestion.question_id)
        .where(ReviewRecord.user_id == WrongQuestion.user_id)
        .correlate(WrongQuestion)
        .scalar_subquery()
    )

    next_review_sub = (
        select(ReviewSchedule.next_review_at)
        .where(ReviewSchedule.question_id == WrongQuestion.question_id)
        .where(ReviewSchedule.user_id == WrongQuestion.user_id)
        .where(ReviewSchedule.mastered == False)
        .correlate(WrongQuestion)
        .order_by(ReviewSchedule.next_review_at.asc().nulls_last())
        .limit(1)
        .scalar_subquery()
    )

    last_reviewed_sub = (
        select(ReviewSchedule.last_reviewed_at)
        .where(ReviewSchedule.question_id == WrongQuestion.question_id)
        .where(ReviewSchedule.user_id == WrongQuestion.user_id)
        .correlate(WrongQuestion)
        .order_by(ReviewSchedule.last_reviewed_at.desc().nulls_last())
        .limit(1)
        .scalar_subquery()
    )

    mastery_pct_sub = (
        select(
            case(
                (UserQuestionState.answer_count > 0,
                 func.cast(UserQuestionState.correct_count, Float) /
                 func.cast(UserQuestionState.answer_count, Float)),
                else_=0.0,
            )
        )
        .where(UserQuestionState.question_id == WrongQuestion.question_id)
        .where(UserQuestionState.user_id == WrongQuestion.user_id)
        .correlate(WrongQuestion)
        .scalar_subquery()
    )

    base_query = (
        select(
            WrongQuestion,
            Question,
            review_record_sub.label("review_record_count"),
            next_review_sub.label("next_review"),
            last_reviewed_sub.label("last_reviewed"),
            mastery_pct_sub.label("mastery_pct"),
        )
        .outerjoin(Question, WrongQuestion.question_id == Question.id)
        .where(and_(*conditions))
    )

    if subject:
        subject_ids = await resolve_subject_ids(db, subject)
        if subject_ids:
            base_query = base_query.where(Question.subject_id.in_(subject_ids))

    if topic:
        topic_filter = cast(Question.knowledge_points, String).contains(topic)
        base_query = base_query.where(topic_filter)

    base_query = base_query.order_by(WrongQuestion.updated_at.desc())

    # Count after filters
    total_q = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(total_q)).scalar() or 0

    # Paginate
    q = base_query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    rows = result.all()

    items = []
    for row in rows:
        wq = row[0]
        question = row[1]
        review_count_val = row[2]
        next_review_val = row[3]
        last_reviewed = row[4]
        mastery_pct = row[5]

        items.append({
            "id": wq.id,
            "question_id": wq.question_id,
            "wrong_answer": wq.wrong_answer,
            "error_type": wq.error_type,
            "review_count": wq.review_count or 0,
            "review_record_count": review_count_val or 0,
            "wrong_count": wq.review_count or 0,
            "mastery_percent": round(float(mastery_pct or 0), 4),
            "is_mastered": wq.mastered,
            "next_review_at": next_review_val,
            "last_reviewed_at": last_reviewed,
            "last_wrong_at": wq.last_review_at,
            "created_at": wq.created_at,
            "updated_at": wq.updated_at,
            "subject": question.subject_ref.code if question and question.subject_ref else None,
            "question_type": question.question_type if question else None,
            "content": question.content if question else None,
            "options": question.options if question else None,
            "answer": question.answer if question else None,
            "analysis": question.analysis if question else None,
            "knowledge_points": question.knowledge_points if question else None,
            "ai_analysis": wq.ai_analysis,
            "ai_analysis_status": "ready" if isinstance(wq.ai_analysis, dict) and wq.ai_analysis else "empty",
        })

    return items, total


# ── Batch operations ──


BATCH_ACTIONS = frozenset({"add_to_review", "mark_mastered", "unmark_mastered", "remove_from_book", "delete"})


async def batch_operate(
    db: AsyncSession,
    user_id: int,
    action: str,
    ids: list[int],
) -> dict:
    """Execute a batch operation on wrong questions — all in one transaction."""

    # Deduplicate while preserving order
    seen: set[int] = set()
    deduped_ids = [x for x in ids if not (x in seen or seen.add(x))]

    if not deduped_ids:
        return {
            "success": False,
            "action": action,
            "requested_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
            "skipped_ids": [],
        }

    # Fetch all WQs belonging to current user in one query
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id.in_(deduped_ids),
            WrongQuestion.user_id == user_id,
        )
    )
    wqs = {wq.id: wq for wq in result.scalars().all()}

    found_ids = set(wqs.keys())
    not_found_ids = [x for x in deduped_ids if x not in found_ids]

    updated_count = 0
    skipped_ids: list[int] = []

    if action == "add_to_review":
        for wq_id, wq in wqs.items():
            try:
                # Reactivate if soft-deleted
                if not wq.is_active:
                    wq.is_active = True
                    wq.removed_at = None
                sch_result = await db.execute(
                    select(ReviewSchedule).where(
                        ReviewSchedule.user_id == user_id,
                        ReviewSchedule.question_id == wq.question_id,
                    )
                )
                schedule = sch_result.scalar_one_or_none()
                if schedule:
                    if schedule.mastered:
                        schedule.mastered = False
                        schedule.next_review_at = utcnow()
                        updated_count += 1
                    elif schedule.next_review_at and schedule.next_review_at > utcnow():
                        schedule.next_review_at = utcnow()
                        updated_count += 1
                    else:
                        skipped_ids.append(wq_id)
                else:
                    from app.services import review_scheduler
                    await review_scheduler.auto_schedule_wrong_question(db, user_id, wq.question_id)
                    updated_count += 1
            except Exception:
                skipped_ids.append(wq_id)

    elif action in ("mark_mastered", "unmark_mastered"):
        from app.services import review_scheduler
        mastered = (action == "mark_mastered")
        for wq_id, wq in wqs.items():
            changed = await review_scheduler.set_mastered_state(
                db, user_id=user_id, question_id=wq.question_id, mastered=mastered,
            )
            if changed:
                updated_count += 1
            else:
                skipped_ids.append(wq_id)

    elif action == "remove_from_book":
        now = utcnow()
        for wq_id, wq in wqs.items():
            if not wq.is_active:
                skipped_ids.append(wq_id)
                continue
            wq.is_active = False
            wq.removed_at = now
            # Remove from review queue by marking mastered
            sch_result = await db.execute(
                select(ReviewSchedule).where(
                    ReviewSchedule.user_id == user_id,
                    ReviewSchedule.question_id == wq.question_id,
                )
            )
            schedule = sch_result.scalar_one_or_none()
            if schedule:
                schedule.mastered = True
            updated_count += 1

    elif action == "delete":
        for wq_id, wq in wqs.items():
            # Delete associated ReviewSchedule and ReviewRecords
            await db.execute(
                delete(ReviewSchedule).where(
                    ReviewSchedule.user_id == user_id,
                    ReviewSchedule.question_id == wq.question_id,
                )
            )
            await db.delete(wq)
            updated_count += 1

    skipped_ids.extend(not_found_ids)

    await db.commit()

    return {
        "success": True,
        "action": action,
        "requested_count": len(deduped_ids),
        "updated_count": updated_count,
        "skipped_count": len(skipped_ids),
        "skipped_ids": skipped_ids,
    }


# ── Task flow ──


async def get_task_flow(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    error_type: str | None = None,
    topic: str | None = None,
    preview_size: int = 3,
) -> dict:
    """Group wrong questions into priority-deduplicated buckets."""

    _, today_end = shanghai_today_boundaries()
    fourteen_days_ago = utcnow() - timedelta(days=14)

    all_items, total_count = await list_wrong_enriched(
        db, user_id, subject=subject, error_type=error_type, topic=topic,
        page=1, page_size=9999,
    )

    today_due: list[dict] = []
    high_freq: list[dict] = []
    recent_added: list[dict] = []
    to_consolidate: list[dict] = []
    mastered: list[dict] = []

    for item in all_items:
        wq_id = item["id"]

        if item["next_review_at"] and item["next_review_at"] <= today_end and not item["is_mastered"]:
            today_due.append(item)
        elif item["wrong_count"] >= 3 and not item["is_mastered"]:
            high_freq.append(item)
        elif item["created_at"] and item["created_at"] >= fourteen_days_ago and not item["is_mastered"]:
            recent_added.append(item)
        elif not item["is_mastered"]:
            to_consolidate.append(item)
        else:
            mastered.append(item)

    groups = [
        {"key": "today_due", "title": "今日应复习", "total": len(today_due), "items": today_due[:preview_size]},
        {"key": "high_frequency", "title": "高频错题", "total": len(high_freq), "items": high_freq[:preview_size]},
        {"key": "recent_added", "title": "最近新增", "total": len(recent_added), "items": recent_added[:preview_size]},
        {"key": "to_consolidate", "title": "待巩固", "total": len(to_consolidate), "items": to_consolidate[:preview_size]},
        {"key": "mastered", "title": "已经掌握", "total": len(mastered), "items": mastered[:preview_size]},
    ]

    summary = {
        "total_count": total_count,
        "mastered_count": len(mastered),
        "high_frequency_count": len(high_freq),
        "today_due_count": len(today_due),
    }

    return {"summary": summary, "groups": groups}
