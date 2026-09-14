import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subject_scope import selected_408_subject_ids
from app.core.time_utils import (
    shanghai_date_utc_range,
    shanghai_today,
    shanghai_today_boundaries,
    utcnow,
)
from app.features.text_normalizer import _split_inline_roman_subitems
from app.models.admin import QuestionVersion, Subject
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.wrong_question import WrongQuestion
from app.services.pdf_text_normalizer import deduplicate_repeated_text
from app.services.question_revision_service import (
    load_latest_question_revision_ids,
    load_revision_views,
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
_CODE_OP_SPLIT_RE = re.compile(r"(?:<=|>=|==|!=|&&|\|\||<<|>>|[<>=!+\-*/%&|^])\s*$")
_CODE_SIGNALS = [
    "return",
    "printf",
    "scanf",
    "malloc",
    "free",
    "NULL",
    "struct",
    "typedef",
    "enum",
    "union",
    "int ",
    "void ",
    "char ",
    "float ",
    "double ",
    "bool",
    "const",
    "static",
    "sizeof",
    "->",
    "::",
    "{",
    "}",
    ";",
    "++",
    "--",
    "+=",
    "-=",
    "*=",
    "/=",
    "#include",
    "#define",
]
_CONTROL_KW = [
    "for",
    "while",
    "if",
    "else if",
    "else",
    "switch",
    "return",
    "break",
    "continue",
    "case",
    "do",
]
_DS_KW = [
    "LNode",
    "TNode",
    "BiTNode",
    "BiTree",
    "BSTNode",
    "LinkList",
    "SqList",
    "Stack",
    "Queue",
    "SqStack",
    "ElemType",
    "Status",
]


def _contains_code(text: str) -> bool:
    if not isinstance(text, str) or not text:
        return False
    score = sum(1 for sig in _CODE_SIGNALS if sig in text)
    score += sum(2 for kw in _DS_KW if kw in text)
    score += sum(
        1 for kw in _CONTROL_KW if re.search(r"\b" + re.escape(kw) + r"\b", text)
    )
    return score >= 3


def _fix_code_operator_splits(text: str) -> str:
    if not isinstance(text, str) or "\n" not in text:
        return text
    lines = text.split("\n")
    merged = [lines[0]]
    for line in lines[1:]:
        if _CODE_OP_SPLIT_RE.search(merged[-1]):
            merged[-1] += line.lstrip()
        else:
            merged.append(line)
    return "\n".join(merged)


def _sanitize_review_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return value
    value = re.sub(r"\r\n?", "\n", value)
    if _contains_code(value):
        return _fix_code_operator_splits(value)
    value = deduplicate_repeated_text(value)
    value = _split_inline_roman_subitems(value)
    return _fix_code_operator_splits(value)


def _sanitize_review_content(content: dict | str | None) -> dict:
    if isinstance(content, str):
        content = {"text": content}
    elif not isinstance(content, dict):
        content = {}
    sanitized = dict(content)
    for field in ("text", "stem"):
        if field in sanitized:
            sanitized[field] = _sanitize_review_text(sanitized[field])
    if sanitized.get("stem"):
        sanitized["text"] = sanitized["stem"]
    for field in (
        "source_snapshot_url",
        "source_snapshot_full_page",
        "visual_regions",
        "visual_region_ids",
    ):
        sanitized.pop(field, None)
    return strip_student_segment_metadata(sanitized)


def _sanitize_review_option_value(value):
    if isinstance(value, str):
        value = re.sub(r"\r\n?", "\n", value)
        value = _fix_code_operator_splits(value)
        return re.sub(r"\n+", " ", value).strip()
    if isinstance(value, dict):
        result = dict(value)
        text = result.get("text")
        if text in (None, ""):
            text = result.get("value")
        if isinstance(text, str):
            result["text"] = _sanitize_review_option_value(text)
        return result
    return value


def _sanitize_review_options(options) -> dict:
    if not isinstance(options, dict):
        return {}
    return {key: _sanitize_review_option_value(value) for key, value in options.items()}


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
_REVIEW_MASTERY_BY_REPETITIONS = {
    0: 20,
    1: 45,
    2: 65,
    3: 80,
    4: 90,
}
_REVIEW_AUTO_MASTER_REPETITIONS = 3


def review_mastery_percent(repetitions: int | None) -> int:
    reps = max(0, int(repetitions or 0))
    if reps >= 5:
        return 100
    return _REVIEW_MASTERY_BY_REPETITIONS.get(reps, 20)


def review_auto_mastered(repetitions: int | None) -> bool:
    return max(0, int(repetitions or 0)) >= _REVIEW_AUTO_MASTER_REPETITIONS


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
    version_changed = int(wq.question_version_id or 0) != int(schedule.question_version_id)
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


async def _prepare_latest_review_revisions(
    db: AsyncSession,
    *,
    user_id: int,
    schedules: list[ReviewSchedule],
) -> list[tuple[ReviewSchedule, object]]:
    """Bind issued review tasks to each question's newest immutable revision.

    Review schedules are long-lived learning state, while question revisions can
    be corrected after the schedule was created.  Student-facing review must show
    the newest revision, but grading still has to be pinned to exactly what was
    issued.  Rebinding the schedule at issuance preserves both properties.

    A revision change increments ``occurrence_seq`` so a page that already loaded
    the old version is rejected instead of submitting an answer against different
    semantics.
    """
    if not schedules:
        return []

    latest_ids = await load_latest_question_revision_ids(
        db, [int(schedule.question_id) for schedule in schedules]
    )
    revision_ids = list(latest_ids.values())
    revision_ids.extend(
        int(schedule.question_version_id)
        for schedule in schedules
        if int(schedule.question_version_id) not in revision_ids
    )
    latest_views = await load_revision_views(db, revision_ids)
    prepared: list[tuple[ReviewSchedule, object]] = []
    changed = False

    for schedule in schedules:
        question_id = int(schedule.question_id)
        latest_version_id = latest_ids.get(question_id)
        # A legacy schedule may predate the newest-revision index or run against
        # a database where that index is temporarily unavailable. If its pinned
        # immutable revision is still present, keep the task usable and pinned
        # rather than silently dropping it.
        revision_id = latest_version_id or int(schedule.question_version_id)
        revision = latest_views.get(int(revision_id))
        if (
            revision is None
            or int(revision.question_id) != question_id
        ):
            logger.warning(
                "review.latest_revision_missing uid=%s schedule_id=%s question_id=%s",
                user_id,
                schedule.id,
                question_id,
            )
            continue

        if latest_version_id is not None and int(schedule.question_version_id) != int(
            latest_version_id
        ):
            await lock_question_review_state(
                db, user_id=user_id, question_id=question_id
            )
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
                continue

            # Another request may have completed the same rebind while this one
            # waited for the row/advisory lock. Only the request that actually
            # changes the revision consumes a new occurrence sequence.
            if int(locked.question_version_id) != int(latest_version_id):
                locked.question_version_id = int(latest_version_id)
                locked.subject_id = revision.subject_id
                locked.occurrence_seq = int(locked.occurrence_seq or 0) + 1
                await _sync_schedule_to_wq(db, locked)
                await db.flush()
                changed = True
            schedule = locked

        prepared.append((schedule, revision))

    if changed:
        # Issuance must persist the exact version/occurrence tuple returned to the
        # client; otherwise a later grading request would see the old schedule.
        await db.commit()
    return prepared


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
    changed = False

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

    if wq is not None:
        # `changed` is the semantic mastery transition, not metadata repair. A
        # stale client must not gain an Undo right merely because this request
        # touched a row that was already mastered by another page/device.
        if bool(wq.mastered) != bool(mastered):
            wq.mastered = bool(mastered)
            changed = True
        if not mastered and wq.mastered_at is not None:
            # Repair legacy/inconsistent rows even when the boolean state was
            # already unmastered; this metadata cleanup is intentionally not a
            # user-visible state transition.
            wq.mastered_at = None

    if schedule is not None:
        if bool(schedule.mastered) != bool(mastered):
            schedule.mastered = bool(mastered)
            # Any manual eligibility transition invalidates review tasks already
            # issued to clients for the previous schedule occurrence.
            schedule.occurrence_seq = int(schedule.occurrence_seq or 0) + 1
            changed = True
    elif not mastered and wq is not None and wq.is_active and wq.question_version_id:
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
        changed = True

    # mastered_at is an event timestamp. Only stamp "now" when this request
    # actually caused a canonical mastery transition; repairing an already-
    # mastered legacy row here would invent a fake "mastered today" event and
    # pollute today's review-task accounting.
    if mastered and changed and wq is not None and wq.mastered_at is None:
        wq.mastered_at = now

    await db.flush()
    return changed


async def get_today_review(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None = None,
    limit: int = 20,
) -> dict:
    _, today_end = shanghai_today_boundaries()
    allowed_subject_ids = await _active_408_subject_ids(db)
    conditions = [
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.is_active,
        ReviewSchedule.next_review_at <= today_end,
        ~ReviewSchedule.mastered,
        _review_408_scope_condition(allowed_subject_ids),
    ]
    if subject_id:
        if subject_id not in allowed_subject_ids:
            return {"total_today": 0, "questions": []}
        conditions.append(ReviewSchedule.subject_id == subject_id)

    valid_schedule_stmt = (
        select(ReviewSchedule)
        .join(QuestionVersion, QuestionVersion.id == ReviewSchedule.question_version_id)
        .where(
            and_(
                *conditions,
                QuestionVersion.question_id == ReviewSchedule.question_id,
            )
        )
    )
    total = int(
        (
            await db.scalar(
                select(func.count(ReviewSchedule.id))
                .select_from(ReviewSchedule)
                .join(
                    QuestionVersion,
                    QuestionVersion.id == ReviewSchedule.question_version_id,
                )
                .where(
                    and_(
                        *conditions,
                        QuestionVersion.question_id == ReviewSchedule.question_id,
                    )
                )
            )
        )
        or 0
    )
    schedules = list(
        (
            await db.scalars(
                valid_schedule_stmt.order_by(
                    ReviewSchedule.next_review_at.asc(), ReviewSchedule.id.asc()
                ).limit(limit)
            )
        ).all()
    )
    questions = []
    prepared = await _prepare_latest_review_revisions(
        db, user_id=user_id, schedules=schedules
    )
    for schedule, revision in prepared:
        questions.append(_review_question_payload(schedule, revision))
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

    # Exact network replay is resolved before mutable schedule state.
    existing = await _get_review_record_by_request(
        db,
        user_id=user_id,
        request_id=request_id,
    )
    if existing is not None:
        if (
            int(existing.question_id) != int(question_id)
            or int(existing.question_version_id) != int(question_version_id)
            or int(existing.schedule_id or 0) != int(schedule_id)
            or int(existing.occurrence_seq) != int(occurrence_seq)
            or int(existing.rating) != int(rating)
            or (existing.user_answer or "") != (user_answer or "")
        ):
            raise ValueError("复习 request_id 已用于不同提交")
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

    schedule = await db.scalar(
        select(ReviewSchedule)
        .where(ReviewSchedule.id == schedule_id, ReviewSchedule.user_id == user_id)
        .with_for_update()
    )
    if schedule is None:
        raise ValueError(f"复习记录不存在: {schedule_id}")
    if int(schedule.question_id) != int(question_id):
        raise ValueError("题目与复习记录不匹配")
    if not schedule.is_active:
        raise ValueError("该复习任务已从复习队列移除，请刷新任务")
    if schedule.mastered:
        raise ValueError("该题已标记掌握，本次复习任务已失效")
    if int(schedule.question_version_id) != int(question_version_id):
        raise ValueError("复习题版本已更新，请刷新后重试")
    if int(schedule.occurrence_seq) != int(occurrence_seq):
        raise ValueError("本次复习任务已经提交或已失效，请刷新任务")

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

    is_correct = rating >= 3
    schedule.mastered = bool(is_correct and review_auto_mastered(schedule.repetitions))
    mastery_percent = review_mastery_percent(schedule.repetitions)

    latest_version_id = await db.scalar(
        select(QuestionVersion.id)
        .where(QuestionVersion.question_id == int(question_id))
        .order_by(QuestionVersion.version.desc(), QuestionVersion.id.desc())
        .limit(1)
    )
    if latest_version_id is not None and int(latest_version_id) == int(
        question_version_id
    ):
        from app.services import question_review_service

        await question_review_service.update_user_question_state_after_answer(
            db, user_id, question_id, is_correct, answered_at=now
        )

    synced_wq = await _sync_schedule_to_wq(
        db,
        schedule,
        latest_wrong_answer=latest_wrong_answer if not is_correct else None,
    )

    record = ReviewRecord(
        user_id=user_id,
        question_id=question_id,
        question_version_id=question_version_id,
        request_id=request_id,
        occurrence_seq=int(occurrence_seq),
        user_answer=user_answer,
        is_correct=is_correct,
        next_review_at=schedule.next_review_at,
        mastery_percent=mastery_percent,
        mastered=bool(schedule.mastered),
        schedule_id=schedule_id,
        rating=rating,
        interval_before=interval_before,
        interval_after=sm2_result["interval"],
        ease_factor_before=ef_before,
        ease_factor_after=sm2_result["efactor"],
        reviewed_at=now,
    )
    db.add(record)
    schedule.occurrence_seq = int(schedule.occurrence_seq) + 1

    if auto_commit:
        await db.commit()
        await db.refresh(schedule)

    return {
        "schedule_id": schedule.id,
        "question_id": question_id,
        "question_version_id": question_version_id,
        "occurrence_seq": int(occurrence_seq),
        "request_id": request_id,
        "rating": rating,
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


def _review_item_error_meta(message: str) -> tuple[str, bool, bool]:
    """Classify deterministic per-item review rejections for clients.

    Network/5xx failures never arrive here: those abort the HTTP request.  Every
    ValueError below describes a task snapshot that cannot be fixed by replaying
    the same schedule/version/occurrence tuple, so the client should fetch a
    fresh task instead of creating an endless local retry loop.
    """
    text = str(message or "")
    if "request_id 已用于不同提交" in text:
        return "REVIEW_REQUEST_CONFLICT", False, True
    if "复习记录不存在" in text:
        return "REVIEW_SCHEDULE_MISSING", False, True
    if "题目与复习记录不匹配" in text:
        return "REVIEW_TASK_MISMATCH", False, True
    if "版本" in text and ("更新" in text or "不存在" in text):
        return "REVIEW_VERSION_STALE", False, True
    if (
        "已从复习队列移除" in text
        or "已标记掌握" in text
        or "已经提交" in text
        or "已失效" in text
    ):
        return "REVIEW_TASK_STALE", False, True
    return "REVIEW_ITEM_REJECTED", False, True


async def grade_batch_review(
    db: AsyncSession,
    user_id: int,
    reviews: list[dict],
) -> dict:
    """Grade and persist one review batch against immutable revisions.

    Each item has its own request_id.  Replaying the same item is exact-idempotent;
    reusing that id for another answer/version is rejected.
    """
    if not reviews:
        raise ValueError("复习列表不能为空")

    # Preload immutable revisions once.  schedule ownership/version is still
    # checked under the per-question transaction lock in submit_review.
    version_ids = [int(item["question_version_id"]) for item in reviews]
    views = await load_revision_views(db, version_ids)

    indexed = list(enumerate(reviews))
    ordered = sorted(
        indexed,
        key=lambda pair: (
            int(pair[1]["question_id"]),
            int(pair[1]["schedule_id"]),
            pair[0],
        ),
    )
    results_by_index: list[tuple[int, dict]] = []
    correct_count = 0
    wrong_count = 0
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
                    {
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
                    },
                )
            )
            continue

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
        rating = 4 if is_correct else 1
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
                latest_wrong_answer=answer.strip() if not is_correct else None,
            )
            payload = {
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
            if result["is_correct"]:
                correct_count += 1
            else:
                wrong_count += 1
                if result.get("wrong_question_id"):
                    prewarm_candidates.append(
                        (
                            int(result["wrong_question_id"]),
                            int(result.get("wrong_review_count") or 0),
                            str(result.get("wrong_answer") or ""),
                        )
                    )
        except ValueError as exc:
            error_text = str(exc)
            error_code, retryable, refresh_required = _review_item_error_meta(
                error_text
            )
            payload = {
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
        results_by_index.append((original_index, payload))

    await db.commit()

    # Wrong review attempts invalidate the previous AI explanation. Warm the new
    # answer-specific analysis only after the review transaction is durable; AI
    # availability must never decide whether the review submission succeeds.
    if prewarm_candidates:
        try:
            from app.services.ai_prewarm_worker import (
                build_prewarm_revision,
                enqueue_prewarm,
            )

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

    results = [
        payload for _, payload in sorted(results_by_index, key=lambda pair: pair[0])
    ]
    # Counts describe successful submissions only.
    correct_count = sum(1 for item in results if item["success"] and item["is_correct"])
    wrong_count = sum(
        1 for item in results if item["success"] and not item["is_correct"]
    )
    return {
        "results": results,
        "total": len(results),
        "correct_count": correct_count,
        "wrong_count": wrong_count,
    }


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
        ReviewSchedule.user_id == user_id, ReviewSchedule.is_active
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
        ReviewSchedule.is_active,
        ReviewSchedule.next_review_at <= today_end,
        ~ReviewSchedule.mastered,
    )
    remaining_today = (await db.execute(remaining_q)).scalar()

    # Overdue (next_review_at < now, not reviewed today, exclude mastered)
    overdue_q = select(func.count(func.distinct(ReviewSchedule.question_id))).where(
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.is_active,
        ReviewSchedule.next_review_at < today_start,
        ~ReviewSchedule.mastered,
    )
    overdue = (await db.execute(overdue_q)).scalar()

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
    accuracy = round(correct_reviews / total_reviews, 4) if total_reviews > 0 else 0.0

    # By subject
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
        .where(ReviewSchedule.user_id == user_id, ReviewSchedule.is_active)
        .group_by(ReviewSchedule.subject_id)
    )

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
    reviewed_by_subject = {
        (r[0] if r[0] is not None else 0): r[1] for r in subject_reviewed_result.all()
    }

    subject_rows = subject_result.all()
    subject_ids = [row[0] for row in subject_rows if row[0] is not None]
    code_name = {}
    if subject_ids:
        subs = (
            (await db.execute(select(Subject).where(Subject.id.in_(subject_ids))))
            .scalars()
            .all()
        )
        code_name = {s.id: (s.code, s.name) for s in subs}

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
    views = await load_revision_views(db, [int(question_version_id)])
    revision = views.get(int(question_version_id))
    if revision is None or int(revision.question_id) != int(question_id):
        raise ValueError("错题版本不存在或与题目不匹配")

    first_review_date = shanghai_today() + timedelta(days=1)
    first_review_at = shanghai_date_utc_range(first_review_date)[0]
    schedule = await db.scalar(
        select(ReviewSchedule)
        .where(
            ReviewSchedule.user_id == user_id, ReviewSchedule.question_id == question_id
        )
        .with_for_update()
    )
    if schedule is None:
        schedule = ReviewSchedule(
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
        db.add(schedule)
    else:
        schedule.question_version_id = int(question_version_id)
        schedule.subject_id = revision.subject_id
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

    due_schedules = list(
        (
            await db.scalars(
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
        ).all()
    )

    reviewed_rows = list(
        (
            await db.execute(
                select(ReviewRecord.schedule_id, ReviewRecord.question_id).where(
                    ReviewRecord.user_id == user_id,
                    ReviewRecord.reviewed_at >= today_start,
                    ReviewRecord.reviewed_at <= today_end,
                )
            )
        ).all()
    )
    reviewed_schedule_ids = {sid for sid, _ in reviewed_rows if sid is not None}
    reviewed_question_ids = {int(qid) for _, qid in reviewed_rows}

    reviewed_schedules: list[ReviewSchedule] = []
    if reviewed_schedule_ids:
        reviewed_schedules = list(
            (
                await db.scalars(
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
            ).all()
        )

    # Manual mastery consumes today's visible task without creating a grade record.
    # WrongQuestion.mastered_at is the explicit event timestamp; schedule.updated_at
    # is intentionally not used because unrelated state changes may touch it.
    mastered_schedules = list(
        (
            await db.scalars(
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
                        WrongQuestion.question_version_id
                        == ReviewSchedule.question_version_id,
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
        ).all()
    )

    schedule_by_id = {
        int(schedule.id): schedule
        for schedule in due_schedules + reviewed_schedules + mastered_schedules
    }
    task_schedules = sorted(
        schedule_by_id.values(),
        key=lambda schedule: (schedule.next_review_at or today_end, int(schedule.id)),
    )
    task_question_ids = {int(s.question_id) for s in task_schedules}

    mastered_question_ids: set[int] = set()
    if task_question_ids:
        mastered_rows = await db.execute(
            select(WrongQuestion.question_id).where(
                WrongQuestion.user_id == user_id,
                WrongQuestion.question_id.in_(task_question_ids),
                WrongQuestion.is_active,
                WrongQuestion.mastered,
            )
        )
        mastered_question_ids = {int(row[0]) for row in mastered_rows.all()}

    completed_question_ids = (
        reviewed_question_ids | mastered_question_ids
    ) & task_question_ids
    pending_schedules = [
        schedule
        for schedule in task_schedules
        if int(schedule.question_id) not in completed_question_ids
        and not schedule.mastered
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
        # These fields are named question_ids and must stay in one ID domain.
        # Returning schedule ids for only all/remaining made equality/diff logic
        # impossible for clients and was especially confusing after mastery undo.
        "all_question_ids": [int(s.question_id) for s in task_schedules],
        "completed_question_ids": sorted(completed_set),
        "remaining_question_ids": [int(s.question_id) for s in pending_schedules],
        "has_due_review": today_due_count > 0,
        "is_completed": today_due_count > 0 and today_remaining_count == 0,
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

    correct_count = sum(1 for record in unique if bool(record.is_correct))
    wrong_count = sum(1 for record in unique if not bool(record.is_correct))
    skipped_count = 0  # backend doesn't explicitly record "skip"
    total_unique = len(unique)
    accuracy = round(correct_count / total_unique, 4) if total_unique > 0 else 0.0
    mastered_count = len(mastered_question_ids)

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

    subject_stats = list(subject_map.values())

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
