import logging
from datetime import date, timedelta

from sqlalchemy import and_, case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import shanghai_today_boundaries, study_day_utc_range, utcnow
from app.models.admin import Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.wrong_question import WrongQuestion
from app.services.knowledge_point_service import (
    load_question_kps,
    normalize_knowledge_name,
)
from app.services.subject_resolution import resolve_subject_ids

logger = logging.getLogger(__name__)


async def _load_wrong_question(
    db: AsyncSession, user_id: int, question_id: int
) -> WrongQuestion | None:
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.question_id == question_id,
        )
    )
    return result.scalars().first()


def _reactivate_existing_wrong_question(
    wq: WrongQuestion,
    wrong_answer: str,
    question_version_id: int,
) -> None:
    """软删除/已掌握的重答仍复用同一行，并清空旧 AI 缓存。"""
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
    wq.question_version_id = int(question_version_id)
    wq.review_count = (wq.review_count or 0) + 1
    wq.last_review_at = utcnow()
    wq.mastered = False
    wq.mastered_at = None


def _new_wrong_question(
    user_id: int,
    question_id: int,
    wrong_answer: str,
    question_version_id: int,
) -> WrongQuestion:
    return WrongQuestion(
        user_id=user_id,
        question_id=question_id,
        question_version_id=question_version_id,
        wrong_answer=wrong_answer,
        review_count=1,
        last_review_at=utcnow(),
    )


async def record_wrong(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    wrong_answer: str,
    *,
    question_version_id: int,
    commit: bool = True,
) -> WrongQuestion:
    # 与 ReviewSchedule 共用 user+question 事务锁，阻止并发首次答错同时创建
    # 两条 WrongQuestion / ReviewSchedule。
    from app.services import review_scheduler

    await review_scheduler.lock_question_review_state(
        db, user_id=user_id, question_id=question_id
    )
    wq = await _load_wrong_question(db, user_id, question_id)

    if wq:
        _reactivate_existing_wrong_question(wq, wrong_answer, question_version_id)
    else:
        wq = _new_wrong_question(
            user_id, question_id, wrong_answer, question_version_id
        )
        db.add(wq)

    # 错题自动进入复习调度（SM-2 由 ReviewSchedule 管理）
    await review_scheduler.auto_schedule_wrong_question(
        db,
        user_id,
        question_id,
        int(question_version_id),
        commit=commit,
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
            from app.ai.prewarm_revision import build_prewarm_revision
            from app.services.ai_prewarm_worker import enqueue_prewarm

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


def _wrong_book_conditions(user_id: int, allowed_subject_ids: set[int] | None) -> list:
    """错题本基础过滤：本人 + 生效中（+ 允许科目范围）。"""
    conditions = [WrongQuestion.user_id == user_id, WrongQuestion.is_active]
    if allowed_subject_ids is not None:
        conditions.append(
            WrongQuestion.question_id.in_(
                select(Question.id).where(Question.subject_id.in_(allowed_subject_ids))
            )
        )
    return conditions


def _wrong_stats_summary_statement(conditions: list):
    """Single covering-index-friendly aggregate replacing four COUNT queries.

    On a large SQLite wrong-question table this avoids repeatedly scanning the
    same user's active rows and removes the observed 1s+ ``mastered = 0`` count
    hot spot.
    """
    return select(
        func.count().label("total"),
        func.coalesce(func.sum(case((~WrongQuestion.mastered, 1), else_=0)), 0).label(
            "unmastered"
        ),
        func.coalesce(func.sum(case((WrongQuestion.mastered, 1), else_=0)), 0).label(
            "mastered"
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            ~WrongQuestion.mastered,
                            WrongQuestion.review_count >= 3,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("high_frequency_count"),
    ).where(and_(*conditions))


async def _wrong_stats_summary(
    db: AsyncSession, conditions: list
) -> tuple[int, int, int, int]:
    """返回 (total, unmastered, mastered, high_frequency_count)。"""
    summary_row = (await db.execute(_wrong_stats_summary_statement(conditions))).one()
    return (
        int(summary_row.total or 0),
        int(summary_row.unmastered or 0),
        int(summary_row.mastered or 0),
        int(summary_row.high_frequency_count or 0),
    )


async def _wrong_stats_by_error_type(db: AsyncSession, conditions: list) -> list[dict]:
    type_result = await db.execute(
        select(WrongQuestion.error_type, func.count(WrongQuestion.id).label("cnt"))
        .where(and_(*conditions))
        .group_by(WrongQuestion.error_type)
    )
    return [{"type": r[0], "count": r[1]} for r in type_result.all()]


async def _wrong_stats_by_subject(db: AsyncSession, conditions: list) -> list[dict]:
    # Wrong-book grouping follows the current question-bank projection.  The
    # immutable ``question_version_id`` remains reserved for review/history.
    result3 = await db.execute(
        select(
            Question.subject_id.label("subject_id"),
            Subject.code.label("subject_code"),
            Subject.name.label("subject_name"),
            func.count(WrongQuestion.id).label("cnt"),
        )
        .join(Question, WrongQuestion.question_id == Question.id)
        .join(Subject, Question.subject_id == Subject.id)
        .where(and_(*conditions))
        .group_by(Question.subject_id, Subject.code, Subject.name)
    )
    return [
        {"subject_id": r[0], "subject_code": r[1], "subject_name": r[2], "count": r[3]}
        for r in result3.all()
    ]


def _today_due_statement_conditions(
    user_id: int, allowed_subject_ids: set[int] | None
) -> list:
    """today_due_count: same definition as get_today_review_overview."""
    _, today_end = shanghai_today_boundaries()
    due_conditions = [
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.is_active,
        ~ReviewSchedule.mastered,
        ReviewSchedule.next_review_at <= today_end,
        ReviewSchedule.question_id.in_(
            select(WrongQuestion.question_id).where(
                WrongQuestion.user_id == user_id,
                WrongQuestion.is_active,
            )
        ),
    ]
    if allowed_subject_ids is not None:
        due_conditions.append(
            ReviewSchedule.question_id.in_(
                select(Question.id).where(Question.subject_id.in_(allowed_subject_ids))
            )
        )
    return due_conditions


async def _today_due_wrong_question_count(
    db: AsyncSession, user_id: int, allowed_subject_ids: set[int] | None
) -> int:
    today_due_q = await db.execute(
        select(func.count(func.distinct(ReviewSchedule.question_id))).where(
            and_(*_today_due_statement_conditions(user_id, allowed_subject_ids))
        )
    )
    return today_due_q.scalar() or 0


async def get_stats(
    db: AsyncSession, user_id: int, allowed_subject_ids: set[int] | None = None
) -> dict:
    conditions = _wrong_book_conditions(user_id, allowed_subject_ids)

    total, unmastered, mastered, high_frequency_count = await _wrong_stats_summary(
        db, conditions
    )
    by_error_type = await _wrong_stats_by_error_type(db, conditions)
    by_subject = await _wrong_stats_by_subject(db, conditions)
    today_due_count = await _today_due_wrong_question_count(
        db, user_id, allowed_subject_ids
    )

    return {
        "total": total,
        "unmastered": unmastered,
        "mastered": mastered,
        "high_frequency_count": high_frequency_count,
        "today_due_count": today_due_count,
        "by_subject": by_subject,
        "by_error_type": by_error_type,
    }


# ── Enhanced list query with correlated subqueries ──


def _wrong_review_record_count_subquery():
    return (
        select(func.count(ReviewRecord.id))
        .where(ReviewRecord.question_id == WrongQuestion.question_id)
        .where(ReviewRecord.question_version_id == WrongQuestion.question_version_id)
        .where(ReviewRecord.user_id == WrongQuestion.user_id)
        .correlate(WrongQuestion)
        .scalar_subquery()
    )


def _wrong_next_review_subquery():
    return (
        select(ReviewSchedule.next_review_at)
        .where(ReviewSchedule.question_id == WrongQuestion.question_id)
        .where(ReviewSchedule.question_version_id == WrongQuestion.question_version_id)
        .where(ReviewSchedule.user_id == WrongQuestion.user_id)
        .where(ReviewSchedule.is_active)
        .where(~ReviewSchedule.mastered)
        .correlate(WrongQuestion)
        .order_by(ReviewSchedule.next_review_at.asc().nulls_last())
        .limit(1)
        .scalar_subquery()
    )


def _wrong_last_reviewed_subquery():
    return (
        select(ReviewSchedule.last_reviewed_at)
        .where(ReviewSchedule.question_id == WrongQuestion.question_id)
        .where(ReviewSchedule.question_version_id == WrongQuestion.question_version_id)
        .where(ReviewSchedule.user_id == WrongQuestion.user_id)
        .correlate(WrongQuestion)
        .order_by(ReviewSchedule.last_reviewed_at.desc().nulls_last())
        .limit(1)
        .scalar_subquery()
    )


def _wrong_mastery_pct_subquery():
    # Revision-local review mastery comes from the schedule's successful SM-2
    # repetition count, never from mutable current-question adaptive state.
    return (
        select(
            case(
                # Manual/automatic mastery is the canonical final state. Showing
                # a mastered card at 20% (because repetitions stayed at 0) is
                # contradictory to the action the learner just confirmed.
                (ReviewSchedule.mastered, 1.00),
                (ReviewSchedule.repetitions >= 5, 1.00),
                (ReviewSchedule.repetitions == 4, 0.90),
                (ReviewSchedule.repetitions == 3, 0.80),
                (ReviewSchedule.repetitions == 2, 0.65),
                (ReviewSchedule.repetitions == 1, 0.45),
                else_=0.20,
            )
        )
        .where(ReviewSchedule.question_id == WrongQuestion.question_id)
        .where(ReviewSchedule.question_version_id == WrongQuestion.question_version_id)
        .where(ReviewSchedule.user_id == WrongQuestion.user_id)
        .correlate(WrongQuestion)
        .scalar_subquery()
    )


def _wrong_list_optional_conditions(
    error_type: str | None, date_from: date | None, date_to: date | None
) -> list:
    conditions: list = []
    if error_type:
        conditions.append(WrongQuestion.error_type == error_type)

    # Inclusive China calendar dates map to a half-open naive UTC range.
    if date_from is not None:
        conditions.append(WrongQuestion.created_at >= study_day_utc_range(date_from)[0])
    if date_to is not None:
        conditions.append(WrongQuestion.created_at < study_day_utc_range(date_to)[1])
    return conditions


def _wrong_list_base_query(conditions: list):
    # Display/filter wrong-book rows against the mutable current Question row so
    # admin corrections immediately propagate to the mini-program. Review and
    # mastery subqueries above deliberately stay bound to the historical
    # ``WrongQuestion.question_version_id`` that produced the wrong attempt.
    return (
        select(
            WrongQuestion,
            Question,
            Subject,
            _wrong_review_record_count_subquery().label("review_record_count"),
            _wrong_next_review_subquery().label("next_review"),
            _wrong_last_reviewed_subquery().label("last_reviewed"),
            _wrong_mastery_pct_subquery().label("mastery_pct"),
        )
        .outerjoin(Question, WrongQuestion.question_id == Question.id)
        .outerjoin(Subject, Question.subject_id == Subject.id)
        .where(and_(*conditions))
    )


async def _apply_wrong_subject_scope(db: AsyncSession, base_query, subject_id: int):
    subject_ids = await resolve_subject_ids(db, subject_id)
    return base_query.where(Question.subject_id.in_(subject_ids))


def _apply_wrong_topic_scope(base_query, topic: str):
    raw_topic = str(topic).strip()
    normalized_topic = normalize_knowledge_name(raw_topic)
    question_matches = (
        select(QuestionKnowledgePoint.question_id)
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
        )
        .where(
            (KnowledgePoint.name.contains(raw_topic))
            | (KnowledgePoint.normalized_name.contains(normalized_topic))
        )
    )
    return base_query.where(WrongQuestion.question_id.in_(question_matches))


def _wrong_mastery_percent(wq: WrongQuestion, mastery_pct) -> float:
    # WrongQuestion.mastered is the canonical wrong-book state.  Keep
    # the API contract consistent even when a legacy/incomplete row has
    # no matching ReviewSchedule: a mastered item must never serialize
    # as 20% and rely on one specific client to repair the display.
    if wq.mastered:
        return 1.0
    return round(float(mastery_pct if mastery_pct is not None else 0.20), 4)


def _wrong_ai_analysis_status(ai_analysis) -> str:
    return "ready" if isinstance(ai_analysis, dict) and ai_analysis else "empty"


def _wrong_list_item(row, kp_map: dict) -> dict:
    """把错题联表行投影成列表条目。"""
    wq = row[0]
    question = row[1]
    subject = row[2]
    review_count_val = row[3]
    next_review_val = row[4]
    last_reviewed = row[5]
    mastery_pct = row[6]

    return {
        "id": wq.id,
        "question_id": wq.question_id,
        "wrong_answer": wq.wrong_answer,
        "error_type": wq.error_type,
        "review_count": wq.review_count or 0,
        "review_record_count": review_count_val or 0,
        "wrong_count": wq.review_count or 0,
        "mastery_percent": _wrong_mastery_percent(wq, mastery_pct),
        "is_mastered": bool(wq.mastered),
        "next_review_at": next_review_val,
        "last_reviewed_at": last_reviewed,
        "last_wrong_at": wq.last_review_at,
        "created_at": wq.created_at,
        "updated_at": wq.updated_at,
        "subject_id": question.subject_id if question else None,
        "subject_code": subject.code if subject else None,
        "subject_name": subject.name if subject else None,
        "question_type": question.question_type if question else None,
        "content": question.content if question else None,
        "options": question.options if question else None,
        "answer": question.answer if question else None,
        "analysis": question.analysis if question else None,
        "knowledge_points": kp_map.get(int(question.id), []) if question else None,
        "image_url": question.image_url if question else None,
        "ai_analysis": wq.ai_analysis,
        "ai_analysis_status": _wrong_ai_analysis_status(wq.ai_analysis),
    }


async def list_wrong_enriched(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None = None,
    error_type: str | None = None,
    topic: str | None = None,
    page: int = 1,
    page_size: int = 20,
    allowed_subject_ids: set[int] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[dict], int]:
    """Enhanced WQ list avoiding N+1 via correlated scalar subqueries."""

    conditions = _wrong_book_conditions(user_id, allowed_subject_ids)
    conditions.extend(_wrong_list_optional_conditions(error_type, date_from, date_to))

    base_query = _wrong_list_base_query(conditions)

    if subject_id:
        base_query = await _apply_wrong_subject_scope(db, base_query, subject_id)

    if topic:
        base_query = _apply_wrong_topic_scope(base_query, topic)

    # Stable pagination: many imported/updated rows can share the same DB
    # timestamp. Without an id tie-breaker, OFFSET pages may duplicate/skip rows.
    base_query = base_query.order_by(
        WrongQuestion.updated_at.desc(), WrongQuestion.id.desc()
    )

    # Count after filters
    total_q = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(total_q)).scalar() or 0

    # Paginate
    q = base_query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).all()

    question_ids = [int(row[1].id) for row in rows if row[1] is not None]
    kp_map = await load_question_kps(db, question_ids)

    items = [_wrong_list_item(row, kp_map) for row in rows]
    return items, total


# ── Batch operations ──


BATCH_ACTIONS = frozenset(
    {"add_to_review", "mark_mastered", "unmark_mastered", "remove_from_book", "delete"}
)


def _dedupe_batch_ids(ids: list[int]) -> list[int]:
    """Deduplicate ids while preserving first-seen order."""

    seen: set[int] = set()
    return [x for x in ids if not (x in seen or seen.add(x))]


def _empty_batch_result(action: str) -> dict:
    return {
        "success": False,
        "action": action,
        "requested_count": 0,
        "updated_count": 0,
        "skipped_count": 0,
        "skipped_ids": [],
    }


async def _load_batch_wrong_questions(
    db: AsyncSession, user_id: int, deduped_ids: list[int]
) -> tuple[dict[int, WrongQuestion], list[int]]:
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
    return wqs, not_found_ids


def _ordered_batch_wrong_questions(
    wqs: dict[int, WrongQuestion],
) -> list[tuple[int, WrongQuestion]]:
    # Batch operations share transaction-scoped per-question locks.  Process them
    # in a stable order so two overlapping batches cannot deadlock by taking the
    # same advisory locks in opposite order.
    return sorted(wqs.items(), key=lambda pair: (pair[1].question_id, pair[0]))


def _reactivate_wrong_question_row(wq: WrongQuestion) -> bool:
    changed = False
    if not wq.is_active:
        wq.is_active = True
        wq.removed_at = None
        changed = True
    if wq.mastered:
        wq.mastered = False
        wq.mastered_at = None
        changed = True
    return changed


async def _rebind_wrong_review_schedule(
    db: AsyncSession, user_id: int, wq: WrongQuestion
) -> tuple[ReviewSchedule, bool]:
    """Return the wrong-book schedule rebound to the current question revision."""

    from app.services import review_scheduler

    schedule = await db.scalar(
        select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.question_id == wq.question_id,
        )
    )
    if schedule is not None and int(schedule.question_version_id) == int(
        wq.question_version_id
    ):
        return schedule, False
    schedule = await review_scheduler.auto_schedule_wrong_question(
        db,
        user_id,
        wq.question_id,
        int(wq.question_version_id),
        commit=False,
    )
    return schedule, True


def _force_schedule_due_now(schedule: ReviewSchedule, rebound: bool) -> bool:
    changed = False
    now = utcnow()
    if not schedule.is_active:
        schedule.is_active = True
        changed = True
    if schedule.mastered:
        schedule.mastered = False
        changed = True
    if schedule.next_review_at is None or schedule.next_review_at > now:
        schedule.next_review_at = now
        if not rebound:
            # Forcing a future occurrence into the queue invalidates any stale
            # client task issued for the previous schedule state.
            schedule.occurrence_seq = int(schedule.occurrence_seq or 0) + 1
        changed = True
    return changed


async def _add_wrong_question_to_review(
    db: AsyncSession, user_id: int, wq: WrongQuestion
) -> bool:
    """Reactivate one wrong-book row and its schedule inside a savepoint."""

    from app.services import review_scheduler

    # One bad/corrupt row must not partially reactivate the wrong-book record
    # while the API reports it as skipped; the caller intentionally continues
    # on errors, so every item gets its own savepoint.
    async with db.begin_nested():
        await review_scheduler.lock_question_review_state(
            db, user_id=user_id, question_id=wq.question_id
        )
        changed = _reactivate_wrong_question_row(wq)
        schedule, rebound = await _rebind_wrong_review_schedule(db, user_id, wq)
        changed = _force_schedule_due_now(schedule, rebound) or changed
        return changed


async def _batch_add_to_review(
    db: AsyncSession, user_id: int, ordered_wqs: list[tuple[int, WrongQuestion]]
) -> tuple[int, list[int]]:
    updated_count = 0
    skipped_ids: list[int] = []
    for wq_id, wq in ordered_wqs:
        try:
            if await _add_wrong_question_to_review(db, user_id, wq):
                updated_count += 1
            else:
                skipped_ids.append(wq_id)
        except Exception:
            skipped_ids.append(wq_id)
    return updated_count, skipped_ids


async def _batch_set_mastered_state(
    db: AsyncSession,
    user_id: int,
    ordered_wqs: list[tuple[int, WrongQuestion]],
    mastered: bool,
) -> tuple[int, list[int]]:
    from app.services import review_scheduler

    updated_count = 0
    skipped_ids: list[int] = []
    for wq_id, wq in ordered_wqs:
        # Mastery actions are wrong-book actions and must only apply to rows
        # that are still active in the book. A stale page can race a remove
        # from another page/device; mutating that now-inactive row would make
        # the stale client believe it changed visible state and could later
        # offer a destructive undo. `add_to_review` is the explicit path for
        # reactivating an inactive wrong question.
        if not wq.is_active:
            skipped_ids.append(wq_id)
            continue
        changed = await review_scheduler.set_mastered_state(
            db,
            user_id=user_id,
            question_id=wq.question_id,
            mastered=mastered,
        )
        if changed:
            updated_count += 1
        else:
            skipped_ids.append(wq_id)
    return updated_count, skipped_ids


async def _batch_remove_from_book(
    db: AsyncSession, user_id: int, ordered_wqs: list[tuple[int, WrongQuestion]]
) -> tuple[int, list[int]]:
    from app.services import review_scheduler

    now = utcnow()
    updated_count = 0
    skipped_ids: list[int] = []
    for wq_id, wq in ordered_wqs:
        await review_scheduler.lock_question_review_state(
            db, user_id=user_id, question_id=wq.question_id
        )
        if not wq.is_active:
            skipped_ids.append(wq_id)
            continue

        wq.is_active = False
        wq.removed_at = now
        schedule = await db.scalar(
            select(ReviewSchedule).where(
                ReviewSchedule.user_id == user_id,
                ReviewSchedule.question_id == wq.question_id,
            )
        )
        if schedule is not None:
            schedule.is_active = False
            schedule.occurrence_seq = int(schedule.occurrence_seq or 0) + 1
        updated_count += 1
    return updated_count, skipped_ids


async def _batch_delete_wrong_questions(
    db: AsyncSession, user_id: int, ordered_wqs: list[tuple[int, WrongQuestion]]
) -> tuple[int, list[int]]:
    from app.services import review_scheduler

    for _wq_id, wq in ordered_wqs:
        await review_scheduler.lock_question_review_state(
            db, user_id=user_id, question_id=wq.question_id
        )
        # Review history belongs to the deleted wrong-book workflow and is
        # removed before its schedule because schedule_id has no delete cascade.
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
        await db.execute(delete(WrongQuestion).where(WrongQuestion.id == wq.id))
    return len(ordered_wqs), []


async def batch_operate(
    db: AsyncSession,
    user_id: int,
    action: str,
    ids: list[int],
) -> dict:
    """Execute a batch operation on wrong questions — all in one transaction."""

    deduped_ids = _dedupe_batch_ids(ids)
    if not deduped_ids:
        return _empty_batch_result(action)

    wqs, not_found_ids = await _load_batch_wrong_questions(db, user_id, deduped_ids)
    ordered_wqs = _ordered_batch_wrong_questions(wqs)

    if action == "add_to_review":
        updated_count, skipped_ids = await _batch_add_to_review(
            db, user_id, ordered_wqs
        )
    elif action in ("mark_mastered", "unmark_mastered"):
        updated_count, skipped_ids = await _batch_set_mastered_state(
            db, user_id, ordered_wqs, mastered=action == "mark_mastered"
        )
    elif action == "remove_from_book":
        updated_count, skipped_ids = await _batch_remove_from_book(
            db, user_id, ordered_wqs
        )
    elif action == "delete":
        updated_count, skipped_ids = await _batch_delete_wrong_questions(
            db, user_id, ordered_wqs
        )
    else:
        updated_count, skipped_ids = 0, []

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

_TASK_FLOW_HIGH_FREQUENCY_MIN = 3
_TASK_FLOW_RECENT_DAYS = 14
_TASK_FLOW_PAGE_SIZE = 500
_TASK_FLOW_GROUPS: tuple[tuple[str, str], ...] = (
    ("today_due", "今日应复习"),
    ("high_frequency", "高频错题"),
    ("recent_added", "最近新增"),
    ("to_consolidate", "待巩固"),
    ("mastered", "已经掌握"),
)


async def _load_all_task_flow_items(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None = None,
    error_type: str | None = None,
    topic: str | None = None,
    allowed_subject_ids: set[int] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[dict], int]:
    # Task-flow totals must describe the whole filtered wrong book, not only
    # the first page.  The previous hard 500-row cap silently dropped older
    # rows for heavy users and made group totals/summary disagree with the
    # list view.
    all_items: list[dict] = []
    total_count = 0
    page = 1
    while True:
        page_items, total_count = await list_wrong_enriched(
            db,
            user_id,
            subject_id=subject_id,
            error_type=error_type,
            topic=topic,
            page=page,
            page_size=_TASK_FLOW_PAGE_SIZE,
            allowed_subject_ids=allowed_subject_ids,
            date_from=date_from,
            date_to=date_to,
        )
        all_items.extend(page_items)
        if not page_items or len(all_items) >= total_count:
            break
        page += 1
    return all_items, total_count


def _task_flow_bucket(item: dict, today_end, fourteen_days_ago) -> str:
    """Priority-deduplicated bucket key for one wrong-book list item."""

    if (
        item["next_review_at"]
        and item["next_review_at"] <= today_end
        and not item["is_mastered"]
    ):
        return "today_due"
    if item["wrong_count"] >= _TASK_FLOW_HIGH_FREQUENCY_MIN and not item["is_mastered"]:
        return "high_frequency"
    if (
        item["created_at"]
        and item["created_at"] >= fourteen_days_ago
        and not item["is_mastered"]
    ):
        return "recent_added"
    if not item["is_mastered"]:
        return "to_consolidate"
    return "mastered"


def _task_flow_groups(buckets: dict[str, list[dict]], preview_size: int) -> list[dict]:
    return [
        {
            "key": key,
            "title": title,
            "total": len(buckets[key]),
            "items": buckets[key][:preview_size],
        }
        for key, title in _TASK_FLOW_GROUPS
    ]


def _task_flow_summary(
    all_items: list[dict], total_count: int, today_due_count: int
) -> dict:
    # Summary counters are non-exclusive headline metrics.  Group buckets are
    # priority-deduplicated, so using len(high_freq) would exclude high-
    # frequency questions that also happen to be due today.
    return {
        "total_count": total_count,
        "mastered_count": sum(1 for item in all_items if item["is_mastered"]),
        "high_frequency_count": sum(
            1
            for item in all_items
            if item["wrong_count"] >= _TASK_FLOW_HIGH_FREQUENCY_MIN
            and not item["is_mastered"]
        ),
        "today_due_count": today_due_count,
    }


async def get_task_flow(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None = None,
    error_type: str | None = None,
    topic: str | None = None,
    preview_size: int = 3,
    allowed_subject_ids: set[int] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """Group wrong questions into priority-deduplicated buckets."""

    _, today_end = shanghai_today_boundaries()
    fourteen_days_ago = utcnow() - timedelta(days=_TASK_FLOW_RECENT_DAYS)

    all_items, total_count = await _load_all_task_flow_items(
        db,
        user_id,
        subject_id=subject_id,
        error_type=error_type,
        topic=topic,
        allowed_subject_ids=allowed_subject_ids,
        date_from=date_from,
        date_to=date_to,
    )

    buckets: dict[str, list[dict]] = {key: [] for key, _ in _TASK_FLOW_GROUPS}
    for item in all_items:
        buckets[_task_flow_bucket(item, today_end, fourteen_days_ago)].append(item)

    return {
        "summary": _task_flow_summary(
            all_items, total_count, len(buckets["today_due"])
        ),
        "groups": _task_flow_groups(buckets, preview_size),
    }
