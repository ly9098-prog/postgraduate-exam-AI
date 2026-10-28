import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subject_scope import selected_408_subject_ids
from app.core.time_utils import (
    normalize_to_naive_utc,
    shanghai_date_utc_range,
    shanghai_today,
    shanghai_today_boundaries,
    utcnow,
)
from app.features.text_normalizer import _split_inline_roman_subitems
from app.models.admin import QuestionVersion, Subject
from app.models.question import Question
from app.models.review_scheduler import ReviewRecord, ReviewSchedule, ReviewSession
from app.models.wrong_question import WrongQuestion
from app.services.pdf_text_normalizer import deduplicate_repeated_text
from app.services.question_revision_service import (
    load_latest_question_revision_ids,
    load_revision_views,
)
from app.services.review_text_utils import (
    _CODE_OP_SPLIT_RE,
    _CODE_SIGNALS,
    _CONTROL_KW,
    _DS_KW,
)
from app.services.review_text_utils import (
    contains_code as _contains_code,
)
from app.services.review_text_utils import (
    fix_code_operator_splits as _fix_code_operator_splits,
)
from app.services.review_text_utils import (
    sanitize_review_content as _sanitize_review_content,
)
from app.services.review_text_utils import (
    sanitize_review_option_value as _sanitize_review_option_value,
)
from app.services.review_text_utils import (
    sanitize_review_options as _sanitize_review_options,
)
from app.services.review_text_utils import (
    sanitize_review_text as _sanitize_review_text,
)
from app.services.review_utils import (
    _REVIEW_AUTO_MASTER_REPETITIONS,
    _REVIEW_MASTERY_BY_REPETITIONS,
    review_auto_mastered,
    review_mastery_percent,
)
from app.services.review_utils import (
    review_item_error_meta as _review_item_error_meta,
)
from app.services.sm2_service import calc_sm2
from app.utils.answer_normalizer import (
    extract_multi_blank_slot_ids,
    is_answer_correct,
)
from app.utils.question_content import strip_student_segment_metadata

# Asia/Shanghai = UTC+8, no DST
_SHANGHAI_TZ = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)


async def _active_408_subject_ids(db: AsyncSession) -> set[int]:
    result = await db.execute(select(Subject))
    return selected_408_subject_ids(result.scalars().all())


def _review_408_scope_condition(subject_ids: set[int]):
    # Prefer immutable revision subject identity; legacy revisions may have a
    # null subject_id, so fall back to the schedule snapshot in that case.
    return or_(
        QuestionVersion.subject_id.in_(subject_ids),
        and_(
            QuestionVersion.subject_id.is_(None),
            ReviewSchedule.subject_id.in_(subject_ids),
        ),
    )


# Keep review payload rendering consistent with the practice/wrong-book APIs.
# Review used to return raw immutable revision content, which meant OCR line
# breaks/admin-only fields could reappear only in the review flow.


def _review_question_payload(schedule: ReviewSchedule, revision) -> dict:
    content = _sanitize_review_content(revision.content)
    return {
        "schedule_id": schedule.id,
        "question_id": schedule.question_id,
        "question_version_id": schedule.question_version_id,
        "occurrence_seq": schedule.occurrence_seq,
        "subject_id": schedule.subject_id,
        "subject_code": revision.subject_ref.code if revision.subject_ref else "",
        "subject_name": revision.subject_ref.name if revision.subject_ref else "",
        "question_type": revision.question_type,
        "stem": content.get("text") or content.get("stem") or "",
        "options": _sanitize_review_options(revision.options),
        "content": content,
        "image_url": revision.image_url,
        "interval": schedule.interval,
        "repetitions": schedule.repetitions,
        "ease_factor": schedule.ease_factor,
    }


# Review mastery belongs to the immutable scheduled revision.  It must not be
# inferred from UserQuestionState because that table represents the mutable
# current-question adaptive state.  Successful SM-2 repetitions map onto the
# same visible mastery percentages used elsewhere in the product.
async def lock_review_request(
    db: AsyncSession,
    *,
    user_id: int,
    request_id: str,
) -> None:
    """Serialize one user's idempotency key before any review mutation."""
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    digest = hashlib.sha256(str(request_id).encode("utf-8")).digest()
    request_lock = int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
    await db.execute(
        select(func.pg_advisory_xact_lock(int(user_id) & 0x7FFFFFFF, request_lock))
    )


async def lock_question_review_state(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
) -> None:
    """Serialize one user's review/wrong-book state transitions on PostgreSQL.

    The database owns uniqueness, while this transaction-scoped lock prevents two
    concurrent requests from advancing the same schedule occurrence out of order.
    SQLite is a development fallback and relies on its writer serialization plus
    the database unique constraints.
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
    await db.execute(select(func.pg_advisory_xact_lock(lock_user, lock_question)))


async def _sync_schedule_to_wq(
    db: AsyncSession,
    schedule: ReviewSchedule,
    latest_wrong_answer: str | None = None,
) -> WrongQuestion | None:
    """Persist schedule state back to the single wrong-book row for this question."""
    wq = await db.scalar(
        select(WrongQuestion).where(
            WrongQuestion.user_id == schedule.user_id,
            WrongQuestion.question_id == schedule.question_id,
        )
    )
    if wq is None:
        return None

    # ReviewSchedule is always rebound when a newer wrong revision is produced.
    # Keep the wrong-book row and schedule on exactly the same immutable revision.
    version_changed = int(wq.question_version_id or 0) != int(
        schedule.question_version_id
    )
    wq.question_version_id = int(schedule.question_version_id)
    if version_changed:
        # AI analysis is revision-specific.  Once review moves to a newer
        # immutable question version, never keep advice generated for the old
        # stem/options/answer snapshot.
        wq.ai_analysis = None
    # ``WrongQuestion.last_review_at`` is the legacy storage backing the public
    # ``last_wrong_at`` field. A correct review must not make the UI claim the
    # learner was wrong again just now; true review time lives on ReviewSchedule.
    wq.mastered = bool(schedule.mastered)
    if schedule.mastered:
        if wq.mastered_at is None:
            wq.mastered_at = schedule.last_reviewed_at or utcnow()
    else:
        wq.mastered_at = None

    if latest_wrong_answer is not None:
        # A wrong review attempt changes the exact AI-analysis input just like a
        # wrong practice attempt. Drop the old embedded analysis immediately so
        # wrong-detail can never show advice for the previous answer while a new
        # prewarm is being generated.
        wq.ai_analysis = None
        wq.wrong_answer = latest_wrong_answer
        wq.last_review_at = schedule.last_reviewed_at or utcnow()
        wq.review_count = (wq.review_count or 0) + 1
        wq.mastered = False
        wq.mastered_at = None

    return wq


def _latest_revision_candidates(
    schedules: list[ReviewSchedule], latest_ids: dict
) -> list[int]:
    revision_ids = list(latest_ids.values())
    revision_ids.extend(
        int(schedule.question_version_id)
        for schedule in schedules
        if int(schedule.question_version_id) not in revision_ids
    )
    return revision_ids


def _latest_revision_view(latest_views: dict, latest_version_id, schedule):
    """Newest view for one schedule, falling back to its pinned immutable revision.

    A legacy schedule may predate the newest-revision index or run against a
    database where that index is temporarily unavailable. If its pinned
    immutable revision is still present, keep the task usable and pinned rather
    than silently dropping it.
    """
    return latest_views.get(int(latest_version_id or int(schedule.question_version_id)))


def _log_missing_review_revision(
    user_id: int, schedule: ReviewSchedule, question_id: int
) -> None:
    logger.warning(
        "review.latest_revision_missing uid=%s schedule_id=%s question_id=%s",
        user_id,
        schedule.id,
        question_id,
    )


async def _lock_and_rebind_latest_revision(
    db: AsyncSession,
    *,
    user_id: int,
    schedule: ReviewSchedule,
    latest_version_id: int,
    revision,
) -> tuple[ReviewSchedule | None, bool]:
    """Lock one stale schedule and rebind it; ``(None, False)`` means skip it."""
    question_id = int(schedule.question_id)
    await lock_question_review_state(db, user_id=user_id, question_id=question_id)
    locked = await db.scalar(
        select(ReviewSchedule)
        .where(
            ReviewSchedule.id == schedule.id,
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.question_id == question_id,
        )
        .with_for_update()
    )
    if locked is None or not locked.is_active or locked.mastered:
        return None, False

    # Another request may have completed the same rebind while this one waited
    # for the row/advisory lock. Only the request that actually changes the
    # revision consumes a new occurrence sequence.
    if int(locked.question_version_id) != int(latest_version_id):
        locked.question_version_id = int(latest_version_id)
        locked.subject_id = revision.subject_id
        locked.occurrence_seq = int(locked.occurrence_seq or 0) + 1
        await _sync_schedule_to_wq(db, locked)
        await db.flush()
        return locked, True
    return locked, False


async def _rebind_if_stale(
    db: AsyncSession,
    *,
    user_id: int,
    schedule: ReviewSchedule,
    latest_version_id: int | None,
    revision,
) -> tuple[ReviewSchedule | None, bool]:
    if latest_version_id is None or int(schedule.question_version_id) == int(
        latest_version_id
    ):
        return schedule, False
    return await _lock_and_rebind_latest_revision(
        db,
        user_id=user_id,
        schedule=schedule,
        latest_version_id=int(latest_version_id),
        revision=revision,
    )


async def _prepare_latest_review_revisions(
    db: AsyncSession,
    *,
    user_id: int,
    schedules: list[ReviewSchedule],
) -> list[tuple[ReviewSchedule, object]]:
    """Bind issued review tasks to each question's newest immutable revision.

    A revision change rebinds the schedule and increments ``occurrence_seq`` so a
    page that already loaded the old version is rejected instead of submitting an
    answer against different semantics.
    """
    if not schedules:
        return []

    latest_ids = await load_latest_question_revision_ids(
        db, [int(schedule.question_id) for schedule in schedules]
    )
    latest_views = await load_revision_views(
        db, _latest_revision_candidates(schedules, latest_ids)
    )
    prepared: list[tuple[ReviewSchedule, object]] = []
    changed = False

    for schedule in schedules:
        question_id = int(schedule.question_id)
        latest_version_id = latest_ids.get(question_id)
        revision = _latest_revision_view(latest_views, latest_version_id, schedule)
        if revision is None or int(revision.question_id) != question_id:
            _log_missing_review_revision(user_id, schedule, question_id)
            continue

        schedule, rebind_changed = await _rebind_if_stale(
            db,
            user_id=user_id,
            schedule=schedule,
            latest_version_id=latest_version_id,
            revision=revision,
        )
        if schedule is None:
            continue
        changed = rebind_changed or changed

        prepared.append((schedule, revision))

    if changed:
        # Issuance must persist the exact version/occurrence tuple returned to the
        # client; otherwise a later grading request would see the old schedule.
        await db.commit()
    return prepared


def _apply_manual_mastery_to_wrong_question(wq: WrongQuestion, mastered: bool) -> bool:
    # `changed` is the semantic mastery transition, not metadata repair. A stale
    # client must not gain an Undo right merely because this request touched a row
    # that was already mastered by another page/device.
    changed = False
    if bool(wq.mastered) != bool(mastered):
        wq.mastered = bool(mastered)
        changed = True
    if not mastered and wq.mastered_at is not None:
        # Repair legacy/inconsistent rows even when the boolean state was already
        # unmastered; this metadata cleanup is intentionally not a user-visible
        # state transition.
        wq.mastered_at = None
    return changed


def _toggle_schedule_mastery(schedule: ReviewSchedule, mastered: bool) -> bool:
    if bool(schedule.mastered) == bool(mastered):
        return False
    schedule.mastered = bool(mastered)
    # Any manual eligibility transition invalidates review tasks already issued
    # to clients for the previous schedule occurrence.
    schedule.occurrence_seq = int(schedule.occurrence_seq or 0) + 1
    return True


async def _restore_review_schedule(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
    wq: WrongQuestion,
    now: datetime,
) -> ReviewSchedule:
    views = await load_revision_views(db, [int(wq.question_version_id)])
    revision = views.get(int(wq.question_version_id))
    if revision is None:
        raise ValueError("错题版本不存在，无法恢复复习计划")
    schedule = ReviewSchedule(
        user_id=user_id,
        question_id=question_id,
        question_version_id=int(wq.question_version_id),
        subject_id=revision.subject_id,
        interval=1,
        ease_factor=2.5,
        repetitions=0,
        next_review_at=now,
        mastered=False,
        is_active=True,
        occurrence_seq=0,
    )
    db.add(schedule)
    return schedule


async def _apply_manual_mastery_to_schedule(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
    wq: WrongQuestion | None,
    schedule: ReviewSchedule | None,
    mastered: bool,
    now: datetime,
) -> tuple[bool, ReviewSchedule | None]:
    if schedule is not None:
        return _toggle_schedule_mastery(schedule, mastered), schedule
    if not mastered and wq is not None and wq.is_active and wq.question_version_id:
        restored = await _restore_review_schedule(
            db, user_id=user_id, question_id=question_id, wq=wq, now=now
        )
        return True, restored
    return False, schedule


async def set_mastered_state(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
    mastered: bool,
) -> bool:
    """Set manual mastery on the canonical wrong-book/schedule state."""
    await lock_question_review_state(db, user_id=user_id, question_id=question_id)
    now = utcnow()

    wq = await db.scalar(
        select(WrongQuestion).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.question_id == question_id,
        )
    )
    schedule = await db.scalar(
        select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.question_id == question_id,
        )
    )

    changed = (
        _apply_manual_mastery_to_wrong_question(wq, mastered)
        if wq is not None
        else False
    )
    schedule_changed, schedule = await _apply_manual_mastery_to_schedule(
        db,
        user_id=user_id,
        question_id=question_id,
        wq=wq,
        schedule=schedule,
        mastered=mastered,
        now=now,
    )
    changed = schedule_changed or changed

    # mastered_at is an event timestamp. Only stamp "now" when this request
    # actually caused a canonical mastery transition; repairing an already-
    # mastered legacy row here would invent a fake "mastered today" event and
    # pollute today's review-task accounting.
    if mastered and changed and wq is not None and wq.mastered_at is None:
        wq.mastered_at = now

    await db.flush()
    return changed


def _today_review_conditions(
    user_id: int, allowed_subject_ids: set[int], today_end: datetime
) -> list:
    return [
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.is_active,
        ReviewSchedule.next_review_at <= today_end,
        ~ReviewSchedule.mastered,
        _review_408_scope_condition(allowed_subject_ids),
    ]


def _valid_revision_schedule_filters(conditions: list) -> tuple:
    return (
        *conditions,
        QuestionVersion.question_id == ReviewSchedule.question_id,
    )


async def _count_today_review_schedules(db: AsyncSession, conditions: list) -> int:
    return int(
        (
            await db.scalar(
                select(func.count(ReviewSchedule.id))
                .select_from(ReviewSchedule)
                .join(
                    QuestionVersion,
                    QuestionVersion.id == ReviewSchedule.question_version_id,
                )
                .where(and_(*_valid_revision_schedule_filters(conditions)))
            )
        )
        or 0
    )


async def _load_today_review_schedules(
    db: AsyncSession, conditions: list, limit: int
) -> list[ReviewSchedule]:
    stmt = (
        select(ReviewSchedule)
        .join(QuestionVersion, QuestionVersion.id == ReviewSchedule.question_version_id)
        .where(and_(*_valid_revision_schedule_filters(conditions)))
    )
    result = await db.scalars(
        stmt.order_by(
            ReviewSchedule.next_review_at.asc(), ReviewSchedule.id.asc()
        ).limit(limit)
    )
    return list(result.all())


async def get_today_review(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None = None,
    limit: int = 20,
) -> dict:
    _, today_end = shanghai_today_boundaries()
    allowed_subject_ids = await _active_408_subject_ids(db)
    conditions = _today_review_conditions(user_id, allowed_subject_ids, today_end)
    if subject_id:
        if subject_id not in allowed_subject_ids:
            return {"total_today": 0, "questions": []}
        conditions.append(ReviewSchedule.subject_id == subject_id)

    total = await _count_today_review_schedules(db, conditions)
    schedules = await _load_today_review_schedules(db, conditions, limit)
    prepared = await _prepare_latest_review_revisions(
        db, user_id=user_id, schedules=schedules
    )
    questions = [
        _review_question_payload(schedule, revision) for schedule, revision in prepared
    ]
    return {"total_today": total, "questions": questions}


async def _get_review_record_by_request(
    db: AsyncSession,
    *,
    user_id: int,
    request_id: str,
) -> ReviewRecord | None:
    return await db.scalar(
        select(ReviewRecord).where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.request_id == request_id,
        )
    )


def _validate_review_replay(
    existing: ReviewRecord,
    *,
    schedule_id: int,
    question_id: int,
    question_version_id: int,
    occurrence_seq: int,
    rating: int,
    user_answer: str | None,
) -> None:
    if (
        int(existing.question_id) != int(question_id)
        or int(existing.question_version_id) != int(question_version_id)
        or int(existing.schedule_id or 0) != int(schedule_id)
        or int(existing.occurrence_seq) != int(occurrence_seq)
        or int(existing.rating) != int(rating)
        or (existing.user_answer or "") != (user_answer or "")
    ):
        raise ValueError("复习 request_id 已用于不同提交")


def _review_replay_payload(
    existing: ReviewRecord,
    *,
    schedule_id: int,
    question_id: int,
    question_version_id: int,
    request_id: str,
) -> dict:
    return {
        "schedule_id": existing.schedule_id or schedule_id,
        "question_id": question_id,
        "question_version_id": question_version_id,
        "occurrence_seq": int(existing.occurrence_seq),
        "request_id": request_id,
        "rating": existing.rating,
        "interval_after": existing.interval_after or 0,
        "ease_factor_after": existing.ease_factor_after or 2.5,
        "next_review_at": existing.next_review_at,
        "is_correct": bool(existing.is_correct),
        "mastery_percent": int(existing.mastery_percent or 20),
        "mastered": bool(existing.mastered),
        "already_submitted": True,
    }


async def _resolve_review_replay(
    db: AsyncSession, user_id: int, request: dict
) -> dict | None:
    """Return the idempotent replay payload, or ``None`` for a fresh submission."""
    existing = await _get_review_record_by_request(
        db,
        user_id=user_id,
        request_id=request["request_id"],
    )
    if existing is None:
        return None
    _validate_review_replay(
        existing,
        schedule_id=request["schedule_id"],
        question_id=request["question_id"],
        question_version_id=request["question_version_id"],
        occurrence_seq=request["occurrence_seq"],
        rating=request["rating"],
        user_answer=request["user_answer"],
    )
    return _review_replay_payload(
        existing,
        schedule_id=request["schedule_id"],
        question_id=request["question_id"],
        question_version_id=request["question_version_id"],
        request_id=request["request_id"],
    )


async def _load_locked_review_schedule(
    db: AsyncSession, user_id: int, request: dict
) -> ReviewSchedule:
    schedule = await db.scalar(
        select(ReviewSchedule)
        .where(
            ReviewSchedule.id == request["schedule_id"],
            ReviewSchedule.user_id == user_id,
        )
        .with_for_update()
    )
    if schedule is None:
        raise ValueError(f"复习记录不存在: {request['schedule_id']}")
    if int(schedule.question_id) != int(request["question_id"]):
        raise ValueError("题目与复习记录不匹配")
    if not schedule.is_active:
        raise ValueError("该复习任务已从复习队列移除，请刷新任务")
    if schedule.mastered:
        raise ValueError("该题已标记掌握，本次复习任务已失效")
    if int(schedule.question_version_id) != int(request["question_version_id"]):
        raise ValueError("复习题版本已更新，请刷新后重试")
    if int(schedule.occurrence_seq) != int(request["occurrence_seq"]):
        raise ValueError("本次复习任务已经提交或已失效，请刷新任务")
    return schedule


def _apply_sm2_update(schedule: ReviewSchedule, rating: int) -> tuple:
    sm2_result = calc_sm2(
        quality=rating,
        efactor=schedule.ease_factor,
        interval=schedule.interval,
        repetitions=schedule.repetitions,
        review_date=shanghai_today(),
    )
    interval_before = schedule.interval
    ef_before = schedule.ease_factor
    now = utcnow()

    schedule.ease_factor = sm2_result["efactor"]
    schedule.interval = sm2_result["interval"]
    schedule.repetitions = sm2_result["repetitions"]
    schedule.next_review_at = shanghai_date_utc_range(sm2_result["next_review_date"])[0]
    schedule.last_reviewed_at = now
    return sm2_result, interval_before, ef_before, now


async def _maybe_update_user_question_state(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    question_version_id: int,
    is_correct: bool,
    now: datetime,
) -> None:
    latest_version_id = await db.scalar(
        select(QuestionVersion.id)
        .where(QuestionVersion.question_id == int(question_id))
        .order_by(QuestionVersion.version.desc(), QuestionVersion.id.desc())
        .limit(1)
    )
    if latest_version_id is None or int(latest_version_id) != int(question_version_id):
        return

    from app.services import question_review_service

    await question_review_service.update_user_question_state_after_answer(
        db, user_id, question_id, is_correct, answered_at=now
    )


def _build_review_record(
    request: dict,
    *,
    user_id: int,
    is_correct: bool,
    schedule: ReviewSchedule,
    interval_before: int,
    ef_before: float,
    mastery_percent: int,
    sm2_result: dict,
    now: datetime,
) -> ReviewRecord:
    return ReviewRecord(
        user_id=user_id,
        question_id=request["question_id"],
        question_version_id=request["question_version_id"],
        request_id=request["request_id"],
        occurrence_seq=int(request["occurrence_seq"]),
        user_answer=request["user_answer"],
        is_correct=is_correct,
        next_review_at=schedule.next_review_at,
        mastery_percent=mastery_percent,
        mastered=bool(schedule.mastered),
        schedule_id=request["schedule_id"],
        rating=request["rating"],
        interval_before=interval_before,
        interval_after=sm2_result["interval"],
        ease_factor_before=ef_before,
        ease_factor_after=sm2_result["efactor"],
        reviewed_at=now,
    )


def _review_submit_payload(
    request: dict,
    schedule: ReviewSchedule,
    sm2_result: dict,
    is_correct: bool,
    mastery_percent: int,
    synced_wq: WrongQuestion | None,
) -> dict:
    return {
        "schedule_id": schedule.id,
        "question_id": request["question_id"],
        "question_version_id": request["question_version_id"],
        "occurrence_seq": int(request["occurrence_seq"]),
        "request_id": request["request_id"],
        "rating": request["rating"],
        "interval_after": sm2_result["interval"],
        "ease_factor_after": sm2_result["efactor"],
        "next_review_at": schedule.next_review_at,
        "is_correct": is_correct,
        "mastery_percent": mastery_percent,
        "mastered": bool(schedule.mastered),
        "already_submitted": False,
        # Internal fields used by grade_batch_review after the transaction commits.
        # They are intentionally not copied into the public batch response.
        "wrong_question_id": int(synced_wq.id)
        if synced_wq is not None and not is_correct
        else None,
        "wrong_review_count": int(synced_wq.review_count or 0)
        if synced_wq is not None and not is_correct
        else None,
        "wrong_answer": synced_wq.wrong_answer
        if synced_wq is not None and not is_correct
        else None,
    }


async def _apply_review_grade(
    db: AsyncSession, user_id: int, schedule: ReviewSchedule, request: dict
) -> dict:
    """Apply SM-2 to a locked schedule and persist the immutable review record."""
    sm2_result, interval_before, ef_before, now = _apply_sm2_update(
        schedule, request["rating"]
    )
    is_correct = request["rating"] >= 3
    schedule.mastered = bool(is_correct and review_auto_mastered(schedule.repetitions))
    mastery_percent = review_mastery_percent(schedule.repetitions)

    await _maybe_update_user_question_state(
        db,
        user_id,
        request["question_id"],
        request["question_version_id"],
        is_correct,
        now,
    )
    synced_wq = await _sync_schedule_to_wq(
        db,
        schedule,
        latest_wrong_answer=request["latest_wrong_answer"] if not is_correct else None,
    )
    db.add(
        _build_review_record(
            request,
            user_id=user_id,
            is_correct=is_correct,
            schedule=schedule,
            interval_before=interval_before,
            ef_before=ef_before,
            mastery_percent=mastery_percent,
            sm2_result=sm2_result,
            now=now,
        )
    )
    schedule.occurrence_seq = int(schedule.occurrence_seq) + 1
    return _review_submit_payload(
        request, schedule, sm2_result, is_correct, mastery_percent, synced_wq
    )


async def submit_review(
    db: AsyncSession,
    user_id: int,
    schedule_id: int,
    question_id: int,
    question_version_id: int,
    occurrence_seq: int,
    rating: int,
    *,
    request_id: str,
    auto_commit: bool = True,
    user_answer: str | None = None,
    latest_wrong_answer: str | None = None,
) -> dict:
    if rating < 0 or rating > 5:
        raise ValueError(f"评分必须在 0-5 之间，收到: {rating}")

    await lock_review_request(db, user_id=user_id, request_id=request_id)
    await lock_question_review_state(db, user_id=user_id, question_id=question_id)

    request = {
        "schedule_id": schedule_id,
        "question_id": question_id,
        "question_version_id": question_version_id,
        "occurrence_seq": occurrence_seq,
        "rating": rating,
        "request_id": request_id,
        "user_answer": user_answer,
        "latest_wrong_answer": latest_wrong_answer,
    }
    # Exact network replay is resolved before mutable schedule state.
    replay = await _resolve_review_replay(db, user_id, request)
    if replay is not None:
        return replay

    schedule = await _load_locked_review_schedule(db, user_id, request)
    payload = await _apply_review_grade(db, user_id, schedule, request)
    if auto_commit:
        await db.commit()
        await db.refresh(schedule)
    return payload


# 单组复习计时上限（与刷题会话一致），异常大的值按上限截断。
REVIEW_SESSION_MAX_DURATION_SEC = 6 * 60 * 60
# 客户端校准时钟与服务端的允许误差；超出的 finished_at 按服务端当前时间截断。
_REVIEW_SESSION_CLOCK_TOLERANCE_SEC = 5


def _parse_review_session_datetime(value) -> datetime | None:
    text_val = str(value or "").strip()
    if not text_val:
        return None
    try:
        parsed = datetime.fromisoformat(text_val.replace("Z", "+00:00"))
    except ValueError:
        return None
    return normalize_to_naive_utc(parsed)


def _normalize_review_session(session_meta: dict | None) -> dict | None:
    """Return a sanitized timing window, or ``None`` when nothing should be recorded.

    Review timing only feeds learning-time statistics, so malformed metadata is
    dropped/clamped instead of rejecting the graded batch.
    """
    if not session_meta:
        return None
    request_id = str(session_meta.get("request_id") or "").strip()
    if not request_id:
        return None
    try:
        duration_sec = int(session_meta.get("duration_sec"))
    except (TypeError, ValueError):
        return None
    duration_sec = min(duration_sec, REVIEW_SESSION_MAX_DURATION_SEC)
    if duration_sec <= 0:
        return None

    now = utcnow()
    finished_at = _parse_review_session_datetime(session_meta.get("finished_at"))
    if finished_at is None or finished_at > now + timedelta(
        seconds=_REVIEW_SESSION_CLOCK_TOLERANCE_SEC
    ):
        finished_at = now
    started_at = _parse_review_session_datetime(session_meta.get("started_at"))
    earliest = finished_at - timedelta(seconds=REVIEW_SESSION_MAX_DURATION_SEC)
    if started_at is None or started_at > finished_at or started_at < earliest:
        started_at = finished_at - timedelta(seconds=duration_sec)
    wall_sec = int((finished_at - started_at).total_seconds())
    if duration_sec > wall_sec:
        # 前台时长不可能超过墙钟窗口：扩展起点而非丢弃时长（时钟校准漂移）。
        started_at = finished_at - timedelta(seconds=duration_sec)
    return {
        "request_id": request_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": duration_sec,
    }


def _allocate_review_session_duration(
    groups: list[tuple[int | None, int]], duration_sec: int
) -> list[int]:
    """Split duration by successful question count; remainders go to larger groups."""
    total = sum(count for _, count in groups)
    shares = [duration_sec * count // total for _, count in groups]
    remainder = duration_sec - sum(shares)
    order = sorted(
        range(len(groups)),
        key=lambda i: (-groups[i][1], groups[i][0] is None, groups[i][0] or 0),
    )
    for i in order[:remainder]:
        shares[i] += 1
    return shares


async def _review_session_subject_map(
    db: AsyncSession, user_id: int, succeeded: list[dict]
) -> dict[int, int | None]:
    schedule_ids = sorted({int(item["schedule_id"]) for item in succeeded})
    subject_rows = await db.execute(
        select(
            ReviewSchedule.id,
            func.coalesce(ReviewSchedule.subject_id, Question.subject_id),
        )
        .outerjoin(Question, Question.id == ReviewSchedule.question_id)
        .where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.id.in_(schedule_ids),
        )
    )
    return {int(sid): subj for sid, subj in subject_rows.all()}


def _review_session_stats_by_subject(
    succeeded: list[dict], subject_by_schedule: dict[int, int | None]
) -> dict[int | None, dict]:
    stats_by_subject: dict[int | None, dict] = {}
    for item in succeeded:
        subject_id = subject_by_schedule.get(int(item["schedule_id"]))
        bucket = stats_by_subject.setdefault(
            subject_id, {"question_count": 0, "correct_count": 0, "wrong_count": 0}
        )
        bucket["question_count"] += 1
        if item.get("is_correct"):
            bucket["correct_count"] += 1
        else:
            bucket["wrong_count"] += 1
    return stats_by_subject


async def _review_session_already_recorded(
    db: AsyncSession, user_id: int, base_request_id: str
) -> bool:
    existing = await db.scalar(
        select(func.count(ReviewSession.id)).where(
            ReviewSession.user_id == user_id,
            ReviewSession.request_id.startswith(base_request_id + ":", autoescape=True),
        )
    )
    return bool(existing)


def _add_review_session_rows(
    db: AsyncSession,
    user_id: int,
    stats_by_subject: dict[int | None, dict],
    window: dict,
) -> None:
    base_request_id = window["request_id"]
    groups = [
        (subject_id, bucket["question_count"])
        for subject_id, bucket in stats_by_subject.items()
    ]
    shares = _allocate_review_session_duration(groups, window["duration_sec"])
    for (subject_id, _), share in zip(groups, shares):
        bucket = stats_by_subject[subject_id]
        db.add(
            ReviewSession(
                user_id=user_id,
                subject_id=subject_id,
                request_id=f"{base_request_id}:{subject_id if subject_id is not None else 'none'}",
                started_at=window["started_at"],
                finished_at=window["finished_at"],
                duration_sec=share,
                question_count=bucket["question_count"],
                correct_count=bucket["correct_count"],
                wrong_count=bucket["wrong_count"],
                status="completed",
            )
        )


async def _record_review_session(
    db: AsyncSession,
    user_id: int,
    session_meta: dict | None,
    results: list[dict],
) -> None:
    """Persist per-subject ReviewSession rows for one graded group (best effort).

    Runs after the grading transaction commits: a statistics write failure must
    never undo SM-2 progress.  Replays of the same client segment id are no-ops.
    """
    window = _normalize_review_session(session_meta)
    if window is None:
        return
    succeeded = [item for item in results if item.get("success")]
    if not succeeded:
        return
    try:
        subject_by_schedule = await _review_session_subject_map(db, user_id, succeeded)
        stats_by_subject = _review_session_stats_by_subject(
            succeeded, subject_by_schedule
        )
        if await _review_session_already_recorded(db, user_id, window["request_id"]):
            return
        _add_review_session_rows(db, user_id, stats_by_subject, window)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning(
            "review session timing record failed uid=%s", user_id, exc_info=True
        )


def _batch_review_missing_payload(
    item: dict, version_id: int, occurrence_seq: int, request_id: str
) -> dict:
    return {
        "schedule_id": item["schedule_id"],
        "question_id": item["question_id"],
        "question_version_id": version_id,
        "occurrence_seq": occurrence_seq,
        "request_id": request_id,
        "success": False,
        "error": "复习题版本不存在",
        "error_code": "REVIEW_VERSION_MISSING",
        "retryable": False,
        "refresh_required": True,
        "is_correct": False,
        "correct_answer": "",
        "rating": 0,
        "interval_after": 0,
        "ease_factor_after": 0.0,
        "next_review_at": None,
        "mastery_percent": 20,
        "mastered": False,
    }


def _batch_review_question_answer(revision, item: dict) -> tuple[str, bool, int]:
    answer = str(item.get("user_answer") or "")
    slot_ids = extract_multi_blank_slot_ids(
        getattr(revision, "content", None),
        getattr(revision, "options", None),
    )
    is_correct = is_answer_correct(
        answer,
        revision.answer or "",
        revision.question_type or "",
        slot_ids=slot_ids,
    )
    return answer, is_correct, (4 if is_correct else 1)


def _batch_review_success_payload(
    item: dict,
    revision,
    version_id: int,
    occurrence_seq: int,
    request_id: str,
    result: dict,
) -> dict:
    return {
        "schedule_id": result["schedule_id"],
        "question_id": item["question_id"],
        "question_version_id": version_id,
        "occurrence_seq": occurrence_seq,
        "request_id": request_id,
        "success": True,
        "error": None,
        "error_code": None,
        "retryable": False,
        "refresh_required": False,
        "is_correct": bool(result["is_correct"]),
        "correct_answer": revision.answer or "",
        "rating": result["rating"],
        "interval_after": result["interval_after"],
        "ease_factor_after": result["ease_factor_after"],
        "next_review_at": result["next_review_at"],
        "mastery_percent": result["mastery_percent"],
        "mastered": result["mastered"],
    }


def _batch_review_error_payload(
    item: dict,
    revision,
    version_id: int,
    occurrence_seq: int,
    request_id: str,
    rating: int,
    error_text: str,
) -> dict:
    error_code, retryable, refresh_required = _review_item_error_meta(error_text)
    return {
        "schedule_id": item["schedule_id"],
        "question_id": item["question_id"],
        "question_version_id": version_id,
        "occurrence_seq": occurrence_seq,
        "request_id": request_id,
        "success": False,
        "error": error_text,
        "error_code": error_code,
        "retryable": retryable,
        "refresh_required": refresh_required,
        "is_correct": False,
        "correct_answer": revision.answer or "",
        "rating": rating,
        "interval_after": 0,
        "ease_factor_after": 0.0,
        "next_review_at": None,
        "mastery_percent": 20,
        "mastered": False,
    }


def _batch_review_prewarm_candidate(result: dict) -> tuple[int, int, str] | None:
    if result["is_correct"] or not result.get("wrong_question_id"):
        return None
    return (
        int(result["wrong_question_id"]),
        int(result.get("wrong_review_count") or 0),
        str(result.get("wrong_answer") or ""),
    )


async def _grade_batch_review_item(
    db: AsyncSession, user_id: int, original_index: int, item: dict, revision
) -> tuple[int, dict, tuple[int, int, str] | None]:
    version_id = int(item["question_version_id"])
    request_id = str(item["request_id"])
    occurrence_seq = int(item["occurrence_seq"])
    answer, _is_correct, rating = _batch_review_question_answer(revision, item)
    try:
        result = await submit_review(
            db,
            user_id=user_id,
            schedule_id=int(item["schedule_id"]),
            question_id=int(item["question_id"]),
            question_version_id=version_id,
            occurrence_seq=occurrence_seq,
            rating=rating,
            request_id=request_id,
            auto_commit=False,
            user_answer=answer,
            latest_wrong_answer=answer.strip() if not _is_correct else None,
        )
    except ValueError as exc:
        payload = _batch_review_error_payload(
            item, revision, version_id, occurrence_seq, request_id, rating, str(exc)
        )
        return original_index, payload, None
    payload = _batch_review_success_payload(
        item, revision, version_id, occurrence_seq, request_id, result
    )
    return original_index, payload, _batch_review_prewarm_candidate(result)


async def _prewarm_review_wrong_answers(
    prewarm_candidates: list[tuple[int, int, str]], user_id: int
) -> None:
    if not prewarm_candidates:
        return
    # Wrong review attempts invalidate the previous AI explanation. Warm the new
    # answer-specific analysis only after the review transaction is durable; AI
    # availability must never decide whether the review submission succeeds.
    try:
        from app.ai.prewarm_revision import build_prewarm_revision
        from app.services.ai_prewarm_worker import enqueue_prewarm

        for wq_id, review_count, wrong_answer in prewarm_candidates:
            revision = build_prewarm_revision(
                review_count=review_count,
                wrong_answer=wrong_answer,
            )
            await enqueue_prewarm(wq_id, user_id, revision=revision)
    except Exception:
        logger.warning(
            "AI prewarm enqueue failed after review batch uid=%s",
            user_id,
            exc_info=True,
        )


def _ordered_review_items(reviews: list[dict]) -> list[tuple[int, dict]]:
    """Stable per-question ordering so overlapping batches cannot deadlock."""
    return sorted(
        enumerate(reviews),
        key=lambda pair: (
            int(pair[1]["question_id"]),
            int(pair[1]["schedule_id"]),
            pair[0],
        ),
    )


async def _grade_batch_review_loop(
    db: AsyncSession, user_id: int, ordered: list[tuple[int, dict]], views: dict
) -> tuple[list[tuple[int, dict]], list[tuple[int, int, str]]]:
    results_by_index: list[tuple[int, dict]] = []
    prewarm_candidates: list[tuple[int, int, str]] = []
    for original_index, item in ordered:
        version_id = int(item["question_version_id"])
        revision = views.get(version_id)
        request_id = str(item["request_id"])
        occurrence_seq = int(item["occurrence_seq"])
        if revision is None or int(revision.question_id) != int(item["question_id"]):
            results_by_index.append(
                (
                    original_index,
                    _batch_review_missing_payload(
                        item, version_id, occurrence_seq, request_id
                    ),
                )
            )
            continue

        index, payload, prewarm = await _grade_batch_review_item(
            db, user_id, original_index, item, revision
        )
        results_by_index.append((index, payload))
        if prewarm is not None:
            prewarm_candidates.append(prewarm)
    return results_by_index, prewarm_candidates


async def grade_batch_review(
    db: AsyncSession,
    user_id: int,
    reviews: list[dict],
    *,
    session_meta: dict | None = None,
) -> dict:
    """Grade and persist one review batch against immutable revisions.

    Each item has its own request_id.  Replaying the same item is exact-idempotent;
    reusing that id for another answer/version is rejected.  ``session_meta`` (the
    client's foreground timing for this group) is recorded afterwards as
    ReviewSession rows for learning-time statistics.
    """
    if not reviews:
        raise ValueError("复习列表不能为空")

    # Preload immutable revisions once.  schedule ownership/version is still
    # checked under the per-question transaction lock in submit_review.
    version_ids = [int(item["question_version_id"]) for item in reviews]
    views = await load_revision_views(db, version_ids)

    results_by_index, prewarm_candidates = await _grade_batch_review_loop(
        db, user_id, _ordered_review_items(reviews), views
    )
    await db.commit()

    await _prewarm_review_wrong_answers(prewarm_candidates, user_id)

    results = [
        payload for _, payload in sorted(results_by_index, key=lambda pair: pair[0])
    ]
    await _record_review_session(db, user_id, session_meta, results)
    # Counts describe successful submissions only.
    return {
        "results": results,
        "total": len(results),
        "correct_count": sum(
            1 for item in results if item["success"] and item["is_correct"]
        ),
        "wrong_count": sum(
            1 for item in results if item["success"] and not item["is_correct"]
        ),
    }


async def _count_active_review_schedules(db: AsyncSession, user_id: int):
    q = select(func.count(ReviewSchedule.id)).where(
        ReviewSchedule.user_id == user_id, ReviewSchedule.is_active
    )
    return (await db.execute(q)).scalar()


async def _count_reviews_between(
    db: AsyncSession, user_id: int, start: datetime, end: datetime
):
    q = select(func.count(ReviewRecord.id)).where(
        ReviewRecord.user_id == user_id,
        ReviewRecord.reviewed_at >= start,
        ReviewRecord.reviewed_at <= end,
    )
    return (await db.execute(q)).scalar()


async def _count_remaining_today(db: AsyncSession, user_id: int, today_end: datetime):
    q = select(func.count(func.distinct(ReviewSchedule.question_id))).where(
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.is_active,
        ReviewSchedule.next_review_at <= today_end,
        ~ReviewSchedule.mastered,
    )
    return (await db.execute(q)).scalar()


async def _count_overdue_reviews(db: AsyncSession, user_id: int, today_start: datetime):
    q = select(func.count(func.distinct(ReviewSchedule.question_id))).where(
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.is_active,
        ReviewSchedule.next_review_at < today_start,
        ~ReviewSchedule.mastered,
    )
    return (await db.execute(q)).scalar()


async def _review_accuracy_since(
    db: AsyncSession, user_id: int, since: datetime
) -> float:
    # Accuracy last N days (rating >= 3 = correct)
    accuracy_q = await db.execute(
        select(
            func.count(ReviewRecord.id),
            func.sum(case((ReviewRecord.rating >= 3, 1), else_=0)),
        ).where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.reviewed_at >= since,
        )
    )
    acc_row = accuracy_q.one()
    total_reviews = acc_row[0] or 0
    correct_reviews = acc_row[1] or 0
    return round(correct_reviews / total_reviews, 4) if total_reviews > 0 else 0.0


async def _review_schedule_subject_rows(
    db: AsyncSession, user_id: int, today_end: datetime
) -> list:
    result = await db.execute(
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
        .where(ReviewSchedule.user_id == user_id, ReviewSchedule.is_active)
        .group_by(ReviewSchedule.subject_id)
    )
    return result.all()


async def _reviewed_by_subject_today(
    db: AsyncSession, user_id: int, today_start: datetime, today_end: datetime
) -> dict:
    # Reviewed history is grouped by the immutable revision subject. A schedule may
    # already have been rebound to a newer revision after the historical review.
    subject_reviewed_result = await db.execute(
        select(
            QuestionVersion.subject_id,
            func.count(ReviewRecord.id).label("reviewed"),
        )
        .join(QuestionVersion, QuestionVersion.id == ReviewRecord.question_version_id)
        .where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.reviewed_at >= today_start,
            ReviewRecord.reviewed_at <= today_end,
        )
        .group_by(QuestionVersion.subject_id)
    )
    return {
        (r[0] if r[0] is not None else 0): r[1] for r in subject_reviewed_result.all()
    }


async def _subject_code_names(db: AsyncSession, subject_ids: list) -> dict:
    if not subject_ids:
        return {}
    subs = (
        (await db.execute(select(Subject).where(Subject.id.in_(subject_ids))))
        .scalars()
        .all()
    )
    return {s.id: (s.code, s.name) for s in subs}


def _review_stats_by_subject(
    subject_rows: list, reviewed_by_subject: dict, code_name: dict
) -> list[dict]:
    by_subject = []
    for row in subject_rows:
        sid = row[0] or 0
        sched = row[1] or 0
        rem = row[2] or 0
        rev = reviewed_by_subject.get(sid, 0)
        by_subject.append(
            {
                "subject_id": sid,
                "subject_code": code_name.get(sid, ("", ""))[0],
                "subject_name": code_name.get(sid, ("", ""))[1],
                "scheduled": sched,
                "reviewed": rev,
                "remaining": rem,
            }
        )
    return by_subject


async def get_review_stats(
    db: AsyncSession,
    user_id: int,
    days: int = 7,
) -> dict:
    today = shanghai_today()
    today_start, today_end = shanghai_today_boundaries()
    since = shanghai_date_utc_range(today - timedelta(days=days - 1))[0]

    total_scheduled = await _count_active_review_schedules(db, user_id)
    total_reviewed_today = await _count_reviews_between(
        db, user_id, today_start, today_end
    )
    remaining_today = await _count_remaining_today(db, user_id, today_end)
    overdue = await _count_overdue_reviews(db, user_id, today_start)
    accuracy = await _review_accuracy_since(db, user_id, since)
    subject_rows = await _review_schedule_subject_rows(db, user_id, today_end)
    reviewed_by_subject = await _reviewed_by_subject_today(
        db, user_id, today_start, today_end
    )

    subject_ids = [row[0] for row in subject_rows if row[0] is not None]
    code_name = await _subject_code_names(db, subject_ids)
    by_subject = _review_stats_by_subject(subject_rows, reviewed_by_subject, code_name)

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
    count_q = select(func.count(ReviewRecord.id)).where(ReviewRecord.user_id == user_id)
    total = (await db.execute(count_q)).scalar()

    result = await db.execute(
        select(ReviewRecord)
        .where(ReviewRecord.user_id == user_id)
        .order_by(ReviewRecord.reviewed_at.desc(), ReviewRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    records = list(result.scalars().all())

    items = [
        {
            "question_id": r.question_id,
            "question_version_id": r.question_version_id,
            "rating": r.rating,
            "interval_after": r.interval_after or 0,
            "is_correct": r.is_correct,
            "user_answer": r.user_answer,
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


async def _load_wrong_question_revision(
    db: AsyncSession, question_id: int, question_version_id: int
):
    views = await load_revision_views(db, [int(question_version_id)])
    revision = views.get(int(question_version_id))
    if revision is None or int(revision.question_id) != int(question_id):
        raise ValueError("错题版本不存在或与题目不匹配")
    return revision


def _first_wrong_review_at() -> datetime:
    first_review_date = shanghai_today() + timedelta(days=1)
    return shanghai_date_utc_range(first_review_date)[0]


def _new_wrong_review_schedule(
    user_id: int,
    question_id: int,
    question_version_id: int,
    revision,
    first_review_at: datetime,
) -> ReviewSchedule:
    return ReviewSchedule(
        user_id=user_id,
        question_id=question_id,
        question_version_id=question_version_id,
        subject_id=revision.subject_id,
        interval=1,
        ease_factor=2.5,
        repetitions=0,
        next_review_at=first_review_at,
        mastered=False,
        is_active=True,
        occurrence_seq=0,
    )


def _reset_wrong_review_schedule(
    schedule: ReviewSchedule,
    question_version_id: int,
    subject_id: int | None,
    first_review_at: datetime,
) -> None:
    schedule.question_version_id = int(question_version_id)
    schedule.subject_id = subject_id
    schedule.interval = 1
    schedule.ease_factor = 2.5
    schedule.repetitions = 0
    schedule.next_review_at = first_review_at
    schedule.last_reviewed_at = None
    schedule.mastered = False
    schedule.is_active = True
    # A fresh wrong answer creates a new review occurrence and invalidates
    # any in-flight task issued for the previous schedule state.
    schedule.occurrence_seq = int(schedule.occurrence_seq or 0) + 1


async def auto_schedule_wrong_question(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    question_version_id: int,
    *,
    commit: bool = True,
) -> ReviewSchedule:
    """Create/reset the canonical schedule for the exact wrong revision."""
    await lock_question_review_state(db, user_id=user_id, question_id=question_id)
    revision = await _load_wrong_question_revision(db, question_id, question_version_id)
    first_review_at = _first_wrong_review_at()
    schedule = await db.scalar(
        select(ReviewSchedule)
        .where(
            ReviewSchedule.user_id == user_id, ReviewSchedule.question_id == question_id
        )
        .with_for_update()
    )
    if schedule is None:
        schedule = _new_wrong_review_schedule(
            user_id, question_id, question_version_id, revision, first_review_at
        )
        db.add(schedule)
    else:
        _reset_wrong_review_schedule(
            schedule, question_version_id, revision.subject_id, first_review_at
        )

    await _sync_schedule_to_wq(db, schedule)
    if commit:
        await db.commit()
        await db.refresh(schedule)
    else:
        await db.flush()
    return schedule


async def mark_mastered(
    db: AsyncSession, user_id: int, schedule_id: int
) -> tuple[ReviewSchedule | None, bool]:
    """标记复习题目为已掌握，从复习池移除，并返回本次是否实际改动。"""
    result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.id == schedule_id,
            ReviewSchedule.user_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        return None, False
    if not schedule.is_active:
        # A stale review page may race "remove from wrong book" on another
        # surface. Mastering an inactive schedule must be a no-op; otherwise the
        # stale client can create an undo for state it no longer owns.
        return schedule, False
    changed = await set_mastered_state(
        db,
        user_id=user_id,
        question_id=schedule.question_id,
        mastered=True,
    )
    await db.commit()
    await db.refresh(schedule)
    return schedule, bool(changed)


async def unmark_mastered(
    db: AsyncSession, user_id: int, schedule_id: int
) -> tuple[ReviewSchedule | None, bool]:
    """取消已掌握标记，恢复到复习池，并返回本次是否实际改动。"""
    result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.id == schedule_id,
            ReviewSchedule.user_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        return None, False
    if not schedule.is_active:
        # Do not resurrect an occurrence that was explicitly removed from the
        # review pool by another page/device. `add_to_review` is the only
        # operation allowed to reactivate that workflow.
        return schedule, False
    changed = await set_mastered_state(
        db,
        user_id=user_id,
        question_id=schedule.question_id,
        mastered=False,
    )
    await db.commit()
    await db.refresh(schedule)
    return schedule, bool(changed)


# ── Today review task flow ──


def _today_due_review_statement(
    user_id: int, today_end: datetime, allowed_subject_ids: set[int]
):
    return (
        select(ReviewSchedule)
        .join(
            QuestionVersion,
            QuestionVersion.id == ReviewSchedule.question_version_id,
        )
        .where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.is_active,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= today_end,
            # Legacy/corrupt schedule rows must never surface another question's
            # immutable revision. Excluding them here also prevents one broken
            # schedule from keeping the "today remaining" counter non-zero.
            QuestionVersion.question_id == ReviewSchedule.question_id,
            _review_408_scope_condition(allowed_subject_ids),
        )
    )


async def _today_due_review_schedules(
    db: AsyncSession, user_id: int, today_end: datetime, allowed_subject_ids: set[int]
) -> list[ReviewSchedule]:
    stmt = _today_due_review_statement(user_id, today_end, allowed_subject_ids)
    return list((await db.scalars(stmt)).all())


async def _today_reviewed_rows(
    db: AsyncSession, user_id: int, today_start: datetime, today_end: datetime
) -> list:
    rows = await db.execute(
        select(ReviewRecord.schedule_id, ReviewRecord.question_id).where(
            ReviewRecord.user_id == user_id,
            ReviewRecord.reviewed_at >= today_start,
            ReviewRecord.reviewed_at <= today_end,
        )
    )
    return list(rows.all())


async def _today_reviewed_schedules(
    db: AsyncSession,
    user_id: int,
    reviewed_schedule_ids: set[int],
    allowed_subject_ids: set[int],
) -> list[ReviewSchedule]:
    stmt = (
        select(ReviewSchedule)
        .join(
            QuestionVersion,
            QuestionVersion.id == ReviewSchedule.question_version_id,
        )
        .where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.id.in_(reviewed_schedule_ids),
            QuestionVersion.question_id == ReviewSchedule.question_id,
            _review_408_scope_condition(allowed_subject_ids),
        )
    )
    return list((await db.scalars(stmt)).all())


async def _today_mastered_schedules(
    db: AsyncSession,
    user_id: int,
    today_start: datetime,
    today_end: datetime,
    allowed_subject_ids: set[int],
) -> list[ReviewSchedule]:
    stmt = (
        select(ReviewSchedule)
        .join(
            QuestionVersion,
            QuestionVersion.id == ReviewSchedule.question_version_id,
        )
        .join(
            WrongQuestion,
            and_(
                WrongQuestion.user_id == ReviewSchedule.user_id,
                WrongQuestion.question_id == ReviewSchedule.question_id,
                WrongQuestion.question_version_id == ReviewSchedule.question_version_id,
            ),
        )
        .where(
            ReviewSchedule.user_id == user_id,
            QuestionVersion.question_id == ReviewSchedule.question_id,
            _review_408_scope_condition(allowed_subject_ids),
            ReviewSchedule.is_active,
            ReviewSchedule.mastered,
            ReviewSchedule.next_review_at <= today_end,
            WrongQuestion.is_active,
            WrongQuestion.mastered,
            WrongQuestion.mastered_at >= today_start,
            WrongQuestion.mastered_at <= today_end,
        )
    )
    return list((await db.scalars(stmt)).all())


def _merge_today_task_schedules(
    due_schedules: list[ReviewSchedule],
    reviewed_schedules: list[ReviewSchedule],
    mastered_schedules: list[ReviewSchedule],
    today_end: datetime,
) -> list[ReviewSchedule]:
    schedule_by_id = {
        int(schedule.id): schedule
        for schedule in due_schedules + reviewed_schedules + mastered_schedules
    }
    return sorted(
        schedule_by_id.values(),
        key=lambda schedule: (schedule.next_review_at or today_end, int(schedule.id)),
    )


async def _today_mastered_question_ids(
    db: AsyncSession, user_id: int, task_question_ids: set[int]
) -> set[int]:
    if not task_question_ids:
        return set()
    mastered_rows = await db.execute(
        select(WrongQuestion.question_id).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.question_id.in_(task_question_ids),
            WrongQuestion.is_active,
            WrongQuestion.mastered,
        )
    )
    return {int(row[0]) for row in mastered_rows.all()}


async def _today_reviewed_context(
    db: AsyncSession,
    user_id: int,
    today_start: datetime,
    today_end: datetime,
    allowed_subject_ids: set[int],
) -> tuple[list[ReviewSchedule], set[int]]:
    reviewed_rows = await _today_reviewed_rows(db, user_id, today_start, today_end)
    reviewed_schedule_ids = {sid for sid, _ in reviewed_rows if sid is not None}
    reviewed_question_ids = {int(qid) for _, qid in reviewed_rows}

    reviewed_schedules: list[ReviewSchedule] = []
    if reviewed_schedule_ids:
        reviewed_schedules = await _today_reviewed_schedules(
            db, user_id, reviewed_schedule_ids, allowed_subject_ids
        )
    return reviewed_schedules, reviewed_question_ids


def _pending_today_schedules(
    task_schedules: list[ReviewSchedule], completed_question_ids: set[int]
) -> list[ReviewSchedule]:
    return [
        schedule
        for schedule in task_schedules
        if int(schedule.question_id) not in completed_question_ids
        and not schedule.mastered
    ]


async def _get_today_review_task_state(
    db: AsyncSession,
    user_id: int,
) -> dict:
    """Build one stable view of today's review work.

    A schedule advances ``next_review_at`` immediately after submission, so today's
    task set is the union of currently-due schedules, schedules consumed by a
    ReviewRecord today, and schedules manually mastered today. Database uniqueness
    guarantees one schedule per user/question; no duplicate-repair heuristics live
    in runtime code.
    """
    today_start, today_end = shanghai_today_boundaries()
    allowed_subject_ids = await _active_408_subject_ids(db)

    due_schedules = await _today_due_review_schedules(
        db, user_id, today_end, allowed_subject_ids
    )
    reviewed_schedules, reviewed_question_ids = await _today_reviewed_context(
        db, user_id, today_start, today_end, allowed_subject_ids
    )
    # Manual mastery consumes today's visible task without creating a grade record.
    # WrongQuestion.mastered_at is the explicit event timestamp; schedule.updated_at
    # is intentionally not used because unrelated state changes may touch it.
    mastered_schedules = await _today_mastered_schedules(
        db, user_id, today_start, today_end, allowed_subject_ids
    )

    task_schedules = _merge_today_task_schedules(
        due_schedules, reviewed_schedules, mastered_schedules, today_end
    )
    task_question_ids = {int(s.question_id) for s in task_schedules}
    mastered_question_ids = await _today_mastered_question_ids(
        db, user_id, task_question_ids
    )

    completed_question_ids = (
        reviewed_question_ids | mastered_question_ids
    ) & task_question_ids
    pending_schedules = _pending_today_schedules(task_schedules, completed_question_ids)

    return {
        "today_start": today_start,
        "today_end": today_end,
        "task_schedules": task_schedules,
        "pending_schedules": pending_schedules,
        "task_question_ids": task_question_ids,
        "completed_question_ids": completed_question_ids,
        "mastered_question_ids": mastered_question_ids,
    }


def _today_review_overdue_split(
    pending_schedules: list[ReviewSchedule], today_start: datetime
) -> tuple[int, int]:
    # 逾期/今日新增描述“当前仍未完成”的任务，完成后不会继续制造入口页压力。
    today_overdue_count = sum(
        1
        for s in pending_schedules
        if s.next_review_at is not None and s.next_review_at < today_start
    )
    today_new_due_count = max(0, len(pending_schedules) - today_overdue_count)
    return today_overdue_count, today_new_due_count


def _today_review_batch_metrics(
    today_due_count: int,
    today_remaining_count: int,
    today_completed_count: int,
    batch_size: int,
) -> dict:
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
        "estimated_minutes": estimated_minutes,
        "batch_size": batch_size,
        "current_batch_no": current_batch_no,
        "total_batch_count": total_batch_count,
        "remaining_batch_count": remaining_batch_count,
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
    (
        today_completed_count,
        _completion_rate,
        is_completed,
    ) = _today_completion_metrics(today_due_count, today_remaining_count)
    today_overdue_count, today_new_due_count = _today_review_overdue_split(
        pending_schedules, today_start
    )
    batch_size = 10
    metrics = _today_review_batch_metrics(
        today_due_count, today_remaining_count, today_completed_count, batch_size
    )

    return {
        "date": datetime.now(_SHANGHAI_TZ).strftime("%Y-%m-%d"),
        "today_due_count": today_due_count,
        "today_completed_count": today_completed_count,
        "today_remaining_count": today_remaining_count,
        "today_overdue_count": today_overdue_count,
        "today_new_due_count": today_new_due_count,
        "estimated_minutes": metrics["estimated_minutes"],
        "batch_size": metrics["batch_size"],
        "current_batch_no": metrics["current_batch_no"],
        "total_batch_count": metrics["total_batch_count"],
        "remaining_batch_count": metrics["remaining_batch_count"],
        # These fields are named question_ids and must stay in one ID domain.
        # Returning schedule ids for only all/remaining made equality/diff logic
        # impossible for clients and was especially confusing after mastery undo.
        "all_question_ids": [int(s.question_id) for s in task_schedules],
        "completed_question_ids": sorted(completed_set),
        "remaining_question_ids": [int(s.question_id) for s in pending_schedules],
        "has_due_review": today_due_count > 0,
        "is_completed": is_completed,
    }


async def get_next_today_review_batch(
    db: AsyncSession,
    user_id: int,
    batch_size: int = 10,
) -> dict:
    """Return the next review batch using immutable scheduled revisions."""
    state = await _get_today_review_task_state(db, user_id)
    task_schedules = state["task_schedules"]
    pending = state["pending_schedules"]
    batch = pending[:batch_size]

    questions = []
    prepared = await _prepare_latest_review_revisions(
        db, user_id=user_id, schedules=batch
    )
    for schedule, revision in prepared:
        questions.append(_review_question_payload(schedule, revision))

    due_count = len(task_schedules)
    remaining_count = len(pending)
    completed_count = max(0, due_count - remaining_count)
    total_batch_count = (
        max(1, (due_count + batch_size - 1) // batch_size) if due_count else 1
    )
    batch_no = min((completed_count // batch_size) + 1, total_batch_count)
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


async def _today_result_records(
    db: AsyncSession,
    user_id: int,
    today_start: datetime,
    today_end: datetime,
    task_question_ids: set[int],
) -> list[ReviewRecord]:
    # 只统计属于今日任务集合的复习记录，避免其他入口同日写入 ReviewRecord
    # 时污染“今日复习”的准确率与学科统计。
    if not task_question_ids:
        return []
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
    return list(result.scalars().all())


def _dedupe_records_by_question(records: list[ReviewRecord]) -> list[ReviewRecord]:
    # 若同题同日被重复提交，取最新一次。
    seen_q: set[int] = set()
    unique: list[ReviewRecord] = []
    for record in records:
        if record.question_id in seen_q:
            continue
        seen_q.add(record.question_id)
        unique.append(record)
    return unique


async def _today_result_subject_stats(
    db: AsyncSession, unique: list[ReviewRecord]
) -> list[dict]:
    # Subject stats are revision-bound, never derived from the mutable schedule.
    subject_map: dict[int, dict] = {}
    revision_views = await load_revision_views(
        db, [int(record.question_version_id) for record in unique]
    )
    for record in unique:
        revision = revision_views.get(int(record.question_version_id))
        subj_id = (
            int(revision.subject_id)
            if revision and revision.subject_id is not None
            else 0
        )
        subject = revision.subject_ref if revision else None
        entry = subject_map.setdefault(
            subj_id,
            {
                "subject_id": subj_id,
                "subject_code": subject.code if subject else "",
                "subject_name": subject.name if subject else "",
                "reviewed": 0,
                "correct": 0,
                "wrong": 0,
                "skipped": 0,
            },
        )
        entry["reviewed"] += 1
        if bool(record.is_correct):
            entry["correct"] += 1
        else:
            entry["wrong"] += 1
    return list(subject_map.values())


async def _tomorrow_due_count(
    db: AsyncSession, user_id: int, tomorrow_start: datetime
) -> int:
    tomorrow_end = tomorrow_start + timedelta(days=1) - timedelta(microseconds=1)
    tomorrow_q = await db.execute(
        select(func.count(func.distinct(ReviewSchedule.question_id))).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.is_active,
            ~ReviewSchedule.mastered,
            ReviewSchedule.next_review_at >= tomorrow_start,
            ReviewSchedule.next_review_at <= tomorrow_end,
        )
    )
    return tomorrow_q.scalar() or 0


def _today_result_metrics(unique: list[ReviewRecord]) -> dict:
    correct_count = sum(1 for record in unique if bool(record.is_correct))
    wrong_count = sum(1 for record in unique if not bool(record.is_correct))
    total_unique = len(unique)
    accuracy = round(correct_count / total_unique, 4) if total_unique > 0 else 0.0
    return {
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "skipped_count": 0,  # backend doesn't explicitly record "skip"
        "accuracy": accuracy,
    }


def _today_completion_metrics(
    today_due_count: int, today_remaining_count: int
) -> tuple[int, float, bool]:
    today_completed_count = max(0, today_due_count - today_remaining_count)
    completion_rate = (
        round(today_completed_count / today_due_count, 4)
        if today_due_count > 0
        else 0.0
    )
    is_completed = today_due_count > 0 and today_remaining_count == 0
    return today_completed_count, completion_rate, is_completed


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

    records = await _today_result_records(
        db, user_id, today_start, today_end, task_question_ids
    )
    unique = _dedupe_records_by_question(records)
    metrics = _today_result_metrics(unique)
    mastered_count = len(mastered_question_ids)

    subject_stats = await _today_result_subject_stats(db, unique)
    tomorrow_due_count = await _tomorrow_due_count(db, user_id, tomorrow_start)

    today_due_count = len(task_schedules)
    today_remaining_count = len(pending_schedules)
    today_completed_count, completion_rate, is_completed = _today_completion_metrics(
        today_due_count, today_remaining_count
    )

    return {
        "date": datetime.now(_SHANGHAI_TZ).strftime("%Y-%m-%d"),
        "today_due_count": today_due_count,
        "today_completed_count": today_completed_count,
        "correct_count": metrics["correct_count"],
        "wrong_count": metrics["wrong_count"],
        "skipped_count": metrics["skipped_count"],
        "mastered_count": mastered_count,
        "accuracy": metrics["accuracy"],
        "completion_rate": completion_rate,
        "updated_schedule_count": today_completed_count,
        "tomorrow_due_count": tomorrow_due_count,
        "subject_stats": subject_stats,
        "is_completed": is_completed,
    }
