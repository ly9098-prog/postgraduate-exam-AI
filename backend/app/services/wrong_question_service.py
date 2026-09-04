import logging
from datetime import timedelta

from sqlalchemy import and_, case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.time_utils import shanghai_today_boundaries, utcnow
from app.models.admin import Subject
from app.models.question import Question
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.user_question_state import UserQuestionState
from app.models.wrong_question import WrongQuestion
from app.services.admin_subject_service import resolve_subject_ids
from app.services.knowledge_point_service import kp_fuzzy_condition, load_question_kps

logger = logging.getLogger(__name__)


def _canonical_active_wrong_rows(user_id: int):
    """Return one logical active WrongQuestion row per question.

    Historical concurrency bugs could leave multiple active rows for the same
    ``(user_id, question_id)``.  New writes are serialized now, but list/stats
    APIs still need to tolerate those old rows.  Pick the most recently updated
    row (then highest id as a deterministic tie-breaker) before filtering,
    pagination, or aggregation so one physical duplicate cannot become two
    visible wrong questions.
    """
    ranked = (
        select(
            WrongQuestion.id.label("id"),
            WrongQuestion.question_id.label("question_id"),
            WrongQuestion.error_type.label("error_type"),
            WrongQuestion.mastered.label("mastered"),
            WrongQuestion.review_count.label("review_count"),
            func.row_number()
            .over(
                partition_by=WrongQuestion.question_id,
                order_by=(
                    WrongQuestion.updated_at.desc(),
                    WrongQuestion.id.desc(),
                ),
            )
            .label("rn"),
        )
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.is_active,
        )
        .subquery("ranked_active_wrong_questions")
    )
    return (
        select(
            ranked.c.id,
            ranked.c.question_id,
            ranked.c.error_type,
            ranked.c.mastered,
            ranked.c.review_count,
        )
        .where(ranked.c.rn == 1)
        .subquery("canonical_active_wrong_questions")
    )


async def record_wrong(
    db: AsyncSession, user_id: int, question_id: int, wrong_answer: str, *, commit: bool = True
) -> WrongQuestion:
    # 与 ReviewSchedule 共用 user+question 事务锁，阻止并发首次答错同时创建
    # 两条 WrongQuestion / ReviewSchedule。
    from app.services import review_scheduler

    await review_scheduler.lock_question_review_state(
        db, user_id=user_id, question_id=question_id
    )
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
        # A new wrong attempt changes the analysis input (wrong_answer and
        # review_count). Clear the embedded cache immediately so wrong-detail
        # never renders advice for the previous attempt while prewarm refreshes.
        wq.ai_analysis = None
        wq.wrong_answer = wrong_answer
        wq.review_count = (wq.review_count or 0) + 1
        wq.last_review_at = utcnow()
        wq.mastered = False
        wq.mastered_at = None
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
    await review_scheduler.auto_schedule_wrong_question(
        db, user_id, question_id, commit=commit,
    )

    if not commit:
        await db.flush()
    await db.refresh(wq)
    return wq


async def get_by_id(db: AsyncSession, user_id: int, wq_id: int) -> WrongQuestion | None:
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id == wq_id,
            WrongQuestion.user_id == user_id,
            WrongQuestion.is_active,
        )
    )
    return result.scalar_one_or_none()


async def update_wrong(
    db: AsyncSession, user_id: int, wq_id: int, error_type: str | None
) -> WrongQuestion | None:
    wq = await get_by_id(db, user_id, wq_id)
    if not wq:
        return None
    should_rewarm = False
    if error_type is not None and error_type != wq.error_type:
        wq.error_type = error_type
        wq.ai_analysis = None
        should_rewarm = True
    await db.commit()
    await db.refresh(wq)
    if should_rewarm:
        try:
            from app.services.ai_prewarm_worker import build_prewarm_revision, enqueue_prewarm

            revision = build_prewarm_revision(
                review_count=wq.review_count,
                wrong_answer=wq.wrong_answer,
            )
            await enqueue_prewarm(wq.id, user_id, revision=revision)
        except Exception:
            # Editing the error classification must succeed even if Redis is
            # temporarily unavailable; the AI endpoint can regenerate on demand.
            logger.warning(
                "AI prewarm enqueue failed after wrong-question update wq_id=%s uid=%s",
                wq.id,
                user_id,
                exc_info=True,
            )
    return wq


async def get_stats(db: AsyncSession, user_id: int) -> dict:
    canonical = _canonical_active_wrong_rows(user_id)
    total_q = select(func.count(canonical.c.id))
    total = (await db.execute(total_q)).scalar() or 0

    type_result = await db.execute(
        select(canonical.c.error_type, func.count(canonical.c.id).label("cnt"))
        .group_by(canonical.c.error_type)
    )
    by_error_type = [{"type": r[0], "count": r[1]} for r in type_result.all()]

    # Count by subject from joined questions
    result3 = await db.execute(
        select(
            Question.subject_id.label("subject_id"),
            Subject.code.label("subject_code"),
            Subject.name.label("subject_name"),
            func.count(canonical.c.id).label("cnt"),
        )
        .select_from(canonical)
        .join(Question, canonical.c.question_id == Question.id)
        .join(Subject, Question.subject_id == Subject.id)
        .group_by(Question.subject_id, Subject.code, Subject.name)
    )

    by_subject = [
        {"subject_id": r[0], "subject_code": r[1], "subject_name": r[2], "count": r[3]}
        for r in result3.all()
    ]

    unmastered_q = select(func.count(canonical.c.id)).where(
        canonical.c.mastered.is_(False),
    )
    unmastered = (await db.execute(unmastered_q)).scalar() or 0

    mastered_q = select(func.count(canonical.c.id)).where(
        canonical.c.mastered.is_(True),
    )
    mastered = (await db.execute(mastered_q)).scalar() or 0

    hf_q = select(func.count(canonical.c.id)).where(
        canonical.c.mastered.is_(False),
        canonical.c.review_count >= 3,
    )
    high_frequency_count = (await db.execute(hf_q)).scalar() or 0

    # today_due_count: same definition as get_today_review_overview
    _, today_end = shanghai_today_boundaries()
    today_due_q = await db.execute(
        select(func.count(func.distinct(ReviewSchedule.question_id))).where(
            ReviewSchedule.user_id == user_id,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= today_end,
            ReviewSchedule.question_id.in_(
                select(canonical.c.question_id)
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
        select(ReviewSchedule)
        .where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.question_id == wq.question_id,
        )
        .order_by(ReviewSchedule.id.asc())
        .limit(1)
    )
    # 历史上可能存在重复 schedule；质量评分使用稳定的首条作为 canonical，
    # submit_review 会把 SM-2 状态同步到其余重复记录。
    schedule = result.scalars().first()

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
    subject_id: int | None = None,
    error_type: str | None = None,
    topic: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """Enhanced WQ list avoiding N+1 via correlated scalar subqueries."""

    canonical = _canonical_active_wrong_rows(user_id)
    conditions = []
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
        .where(~ReviewSchedule.mastered)
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

    # 掌握度不再使用“历史正确率”。它表示当前复习记忆状态，并与
    # question_review_service.REVIEW_MASTERY_BY_BOX 保持同一映射。
    mastery_pct_sub = (
        select(
            case(
                (UserQuestionState.box_level >= 5, 1.00),
                (UserQuestionState.box_level == 4, 0.90),
                (UserQuestionState.box_level == 3, 0.80),
                (UserQuestionState.box_level == 2, 0.65),
                (UserQuestionState.box_level == 1, 0.45),
                else_=0.20,
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
        .join(canonical, canonical.c.id == WrongQuestion.id)
        .outerjoin(Question, WrongQuestion.question_id == Question.id)
        .options(selectinload(Question.subject_ref))
    )

    if conditions:
        base_query = base_query.where(and_(*conditions))

    if subject_id:
        # An unresolvable subject_id resolves to an empty list; applying the
        # filter unconditionally (like list_wrong) makes that an empty result
        # instead of leaking every subject's wrong questions.
        subject_ids = await resolve_subject_ids(db, subject_id)
        base_query = base_query.where(Question.subject_id.in_(subject_ids))

    if topic:
        topic_filter = kp_fuzzy_condition(topic)
        if topic_filter is not None:
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
    kp_map = await load_question_kps(db, [row[1].id for row in rows if row[1]])
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
            "mastery_percent": round(float(mastery_pct if mastery_pct is not None else 0.20), 4),
            # mastered 是唯一状态源；百分比只展示进度，不能反向推导调度状态。
            "is_mastered": bool(wq.mastered),
            "next_review_at": next_review_val,
            "last_reviewed_at": last_reviewed,
            "last_wrong_at": wq.last_review_at,
            "created_at": wq.created_at,
            "updated_at": wq.updated_at,
            "subject_id": question.subject_id if question else None,
            "subject_code": question.subject_ref.code if question and question.subject_ref else None,
            "subject_name": question.subject_ref.name if question and question.subject_ref else None,
            "question_type": question.question_type if question else None,
            "content": question.content if question else None,
            "options": question.options if question else None,
            "answer": question.answer if question else None,
            "analysis": question.analysis if question else None,
            "knowledge_points": kp_map.get(question.id, []) if question else None,
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
    # Batch operations share transaction-scoped per-question locks.  Process them
    # in a stable order so two overlapping batches cannot deadlock by taking the
    # same advisory locks in opposite order.
    ordered_wqs = sorted(
        wqs.items(), key=lambda pair: (pair[1].question_id, pair[0])
    )

    if action == "add_to_review":
        from app.services import review_scheduler

        for wq_id, wq in ordered_wqs:
            try:
                await review_scheduler.lock_question_review_state(
                    db, user_id=user_id, question_id=wq.question_id
                )
                changed = False
                # Reactivate if soft-deleted
                if not wq.is_active:
                    wq.is_active = True
                    wq.removed_at = None
                    changed = True

                sch_result = await db.execute(
                    select(ReviewSchedule).where(
                        ReviewSchedule.user_id == user_id,
                        ReviewSchedule.question_id == wq.question_id,
                    )
                )
                schedules = list(sch_result.scalars().all())

                if schedules:
                    if any(schedule.mastered for schedule in schedules) or wq.mastered:
                        changed = await review_scheduler.set_mastered_state(
                            db,
                            user_id=user_id,
                            question_id=wq.question_id,
                            mastered=False,
                        ) or changed

                    now = utcnow()
                    # 所有历史重复 schedule 一并拉回当前复习队列，避免只更新一条
                    # 后仍残留相互冲突的 mastered / next_review_at 状态。
                    for schedule in schedules:
                        if schedule.next_review_at is None or schedule.next_review_at > now:
                            schedule.next_review_at = now
                            changed = True

                    if changed:
                        updated_count += 1
                    else:
                        skipped_ids.append(wq_id)
                else:
                    await review_scheduler.auto_schedule_wrong_question(
                        db, user_id, wq.question_id, commit=False,
                    )
                    await review_scheduler.set_mastered_state(
                        db, user_id=user_id, question_id=wq.question_id, mastered=False,
                    )
                    updated_count += 1
            except Exception:
                skipped_ids.append(wq_id)

    elif action in ("mark_mastered", "unmark_mastered"):
        from app.services import review_scheduler
        mastered = (action == "mark_mastered")
        for wq_id, wq in ordered_wqs:
            changed = await review_scheduler.set_mastered_state(
                db, user_id=user_id, question_id=wq.question_id, mastered=mastered,
            )
            if changed:
                updated_count += 1
            else:
                skipped_ids.append(wq_id)

    elif action == "remove_from_book":
        from app.services import review_scheduler

        now = utcnow()
        for wq_id, wq in ordered_wqs:
            await review_scheduler.lock_question_review_state(
                db, user_id=user_id, question_id=wq.question_id
            )
            if not wq.is_active:
                skipped_ids.append(wq_id)
                continue

            # Historical duplicate WrongQuestion rows represent the same logical
            # question.  Remove all active duplicates together; otherwise one stale
            # row could keep the question visible after the user removed it.
            related_result = await db.execute(
                select(WrongQuestion).where(
                    WrongQuestion.user_id == user_id,
                    WrongQuestion.question_id == wq.question_id,
                )
            )
            for related_wq in related_result.scalars().all():
                related_wq.is_active = False
                related_wq.removed_at = now

            # Remove from review queue by marking every historical duplicate
            # schedule mastered. 不调用 set_mastered_state，避免把“移出错题本”
            # 错误解释成用户已经掌握并改写 WrongQuestion.mastered。
            sch_result = await db.execute(
                select(ReviewSchedule).where(
                    ReviewSchedule.user_id == user_id,
                    ReviewSchedule.question_id == wq.question_id,
                )
            )
            for schedule in sch_result.scalars().all():
                schedule.mastered = True
            updated_count += 1

    elif action == "delete":
        from app.services import review_scheduler

        deleted_question_ids: set[int] = set()
        for wq_id, wq in ordered_wqs:
            # If a malformed historical dataset contains two requested WQ ids for
            # the same question, the first pass deletes the logical question and
            # subsequent ids are already satisfied without issuing duplicate SQL.
            if wq.question_id in deleted_question_ids:
                updated_count += 1
                continue
            await review_scheduler.lock_question_review_state(
                db, user_id=user_id, question_id=wq.question_id
            )

            # ReviewRecord.schedule_id has no ON DELETE CASCADE.  Delete history
            # first, otherwise PostgreSQL/SQLite FK enforcement can reject removal
            # of the associated ReviewSchedule.
            await db.execute(
                delete(ReviewRecord).where(
                    ReviewRecord.user_id == user_id,
                    ReviewRecord.question_id == wq.question_id,
                )
            )
            await db.execute(
                delete(ReviewSchedule).where(
                    ReviewSchedule.user_id == user_id,
                    ReviewSchedule.question_id == wq.question_id,
                )
            )
            # Delete all historical duplicate WQ rows for this logical question.
            await db.execute(
                delete(WrongQuestion).where(
                    WrongQuestion.user_id == user_id,
                    WrongQuestion.question_id == wq.question_id,
                )
            )
            deleted_question_ids.add(wq.question_id)
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
    subject_id: int | None = None,
    error_type: str | None = None,
    topic: str | None = None,
    preview_size: int = 3,
) -> dict:
    """Group wrong questions into priority-deduplicated buckets."""

    _, today_end = shanghai_today_boundaries()
    fourteen_days_ago = utcnow() - timedelta(days=14)

    all_items, total_count = await list_wrong_enriched(
        db, user_id, subject_id=subject_id, error_type=error_type, topic=topic,
        page=1, page_size=500,
    )

    today_due: list[dict] = []
    high_freq: list[dict] = []
    recent_added: list[dict] = []
    to_consolidate: list[dict] = []
    mastered: list[dict] = []

    for item in all_items:
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
