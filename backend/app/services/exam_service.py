from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import Float, case, cast, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subject_scope import EXAM408_CORE_CODES as EXAM408_CORE_CODES
from app.core.time_utils import normalize_to_naive_utc, utcnow
from app.features.question_type import QT_SINGLE_CHOICE
from app.models.admin import QuestionVersion, Subject
from app.models.exam import ExamAnswer, ExamAttempt, ExamPaper, ExamPaperQuestion
from app.models.practice_record import PracticeRecord
from app.services import exam_read_projection, exam_result_projection
from app.services.practice.answer_projection_contract import (
    ANSWER_PROJECTION_TASK_SCHEMA_VERSION,
)
from app.services.question_revision_service import load_revision_kp_names
from app.utils.answer_normalizer import is_answer_correct
from app.utils.question_content import strip_student_segment_metadata


class ExamNotFoundError(ValueError):
    pass


class ExamStateError(ValueError):
    pass


TERMINAL_ATTEMPT_STATUSES = {"submitted", "expired"}
# The client flushes its last local answer/time slice immediately before the
# final submit request.  Do not let that PATCH become the operation that
# finalizes an expired attempt: otherwise it creates the history/result row
# first and the client observes a 409 instead of completing auto-submit.
ANSWER_SYNC_DEADLINE_GRACE_SEC = 8


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _elapsed_seconds(started_at: datetime, now: datetime | None = None) -> int:
    now = normalize_to_naive_utc(now or utcnow())
    started = normalize_to_naive_utc(started_at)
    return max(0, int((now - started).total_seconds()))


def _student_content(content: dict | None) -> dict:
    if not isinstance(content, dict):
        return {}
    clean = dict(content)
    for key in (
        "source_snapshot_url",
        "source_snapshot_full_page",
        "visual_regions",
        "visual_region_ids",
    ):
        clean.pop(key, None)
    return strip_student_segment_metadata(clean)


def _student_options(options: dict | None) -> dict:
    if not isinstance(options, dict):
        return {}
    clean: dict = {}
    for key, value in options.items():
        if isinstance(value, dict):
            next_value = dict(value)
            text = next_value.get("text", next_value.get("value"))
            if isinstance(text, str):
                next_value["text"] = " ".join(
                    text.replace("\r", "\n").splitlines()
                ).strip()
            clean[str(key)] = next_value
        elif isinstance(value, str):
            clean[str(key)] = " ".join(value.replace("\r", "\n").splitlines()).strip()
        else:
            clean[str(key)] = value
    return clean


async def _load_paper_with_summary(
    db: AsyncSession, paper_id: int
) -> tuple[ExamPaper, int, float]:
    row = (
        await db.execute(
            select(
                ExamPaper,
                func.count(ExamPaperQuestion.id),
                func.coalesce(func.sum(ExamPaperQuestion.score), 0),
            )
            .outerjoin(ExamPaperQuestion, ExamPaperQuestion.paper_id == ExamPaper.id)
            .where(ExamPaper.id == paper_id)
            .group_by(ExamPaper.id)
        )
    ).one_or_none()
    if row is None:
        raise ExamNotFoundError("试卷不存在")
    return row[0], int(row[1] or 0), _money(row[2])


async def list_published_papers(db: AsyncSession, user_id: int) -> list[dict]:
    rows = await db.execute(
        select(
            ExamPaper,
            func.count(ExamPaperQuestion.id).label("question_count"),
            func.coalesce(func.sum(ExamPaperQuestion.score), 0).label("total_score"),
        )
        .join(ExamPaperQuestion, ExamPaperQuestion.paper_id == ExamPaper.id)
        .where(ExamPaper.status == "published", ExamPaper.is_active.is_(True))
        .group_by(ExamPaper.id)
        .order_by(
            ExamPaper.year.desc().nullslast(),
            ExamPaper.created_at.desc(),
            ExamPaper.id.desc(),
        )
    )
    papers = rows.all()
    paper_ids = [int(row[0].id) for row in papers]
    attempts_by_paper: dict[int, list[ExamAttempt]] = defaultdict(list)
    if paper_ids:
        attempts = await db.execute(
            select(ExamAttempt)
            .where(ExamAttempt.user_id == user_id, ExamAttempt.paper_id.in_(paper_ids))
            .order_by(ExamAttempt.started_at.desc(), ExamAttempt.id.desc())
        )
        for attempt in attempts.scalars().all():
            attempts_by_paper[int(attempt.paper_id)].append(attempt)

    return exam_read_projection.paper_list(
        papers, attempts_by_paper, sys.modules[__name__]
    )


async def get_published_paper_detail(
    db: AsyncSession, paper_id: int, user_id: int
) -> dict:
    paper, question_count, total_score = await _load_paper_with_summary(db, paper_id)
    if paper.status != "published" or not paper.is_active:
        raise ExamNotFoundError("试卷不存在或已下架")
    attempts = list(
        (
            await db.execute(
                select(ExamAttempt)
                .where(ExamAttempt.user_id == user_id, ExamAttempt.paper_id == paper_id)
                .order_by(ExamAttempt.started_at.desc(), ExamAttempt.id.desc())
            )
        )
        .scalars()
        .all()
    )
    latest = next((a for a in attempts if a.status != "abandoned"), None)
    latest_status = latest.status if latest else None
    if (
        latest is not None
        and latest_status == "in_progress"
        and paper.duration_sec
        and _elapsed_seconds(latest.started_at) >= int(paper.duration_sec)
    ):
        latest_status = "expired"
    terminal_scores = [
        _money(a.score) for a in attempts if a.status in TERMINAL_ATTEMPT_STATUSES
    ]
    dist_rows = await db.execute(
        select(
            Subject.id,
            Subject.code,
            Subject.name,
            func.count(ExamPaperQuestion.id),
            func.coalesce(func.sum(ExamPaperQuestion.score), 0),
        )
        .join(ExamPaperQuestion, ExamPaperQuestion.section_subject_id == Subject.id)
        .where(ExamPaperQuestion.paper_id == paper_id)
        .group_by(Subject.id, Subject.code, Subject.name)
        .order_by(Subject.sort_order.asc(), Subject.id.asc())
    )
    return exam_read_projection.paper_detail(
        paper,
        question_count,
        total_score,
        latest,
        latest_status,
        terminal_scores,
        dist_rows,
        sys.modules[__name__],
    )


async def _get_attempt_for_user(
    db: AsyncSession,
    attempt_id: int,
    user_id: int,
    *,
    lock: bool = False,
) -> ExamAttempt:
    stmt = select(ExamAttempt).where(
        ExamAttempt.id == attempt_id, ExamAttempt.user_id == user_id
    )
    bind = db.get_bind()
    if lock and bind is not None and bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    attempt = await db.scalar(stmt)
    if attempt is None:
        raise ExamNotFoundError("考试记录不存在")
    return attempt


async def _load_attempt_rows(db: AsyncSession, attempt_id: int):
    rows = await db.execute(
        select(ExamAnswer, ExamPaperQuestion, QuestionVersion, Subject)
        .join(
            ExamPaperQuestion, ExamPaperQuestion.id == ExamAnswer.exam_paper_question_id
        )
        .join(QuestionVersion, QuestionVersion.id == ExamAnswer.question_version_id)
        .join(Subject, Subject.id == ExamPaperQuestion.section_subject_id)
        .where(ExamAnswer.attempt_id == attempt_id)
        .order_by(ExamPaperQuestion.position.asc(), ExamPaperQuestion.id.asc())
    )
    return rows.all()


async def _ensure_attempt_not_expired(
    db: AsyncSession, attempt: ExamAttempt
) -> ExamAttempt:
    if attempt.status != "in_progress":
        return attempt
    paper = await db.get(ExamPaper, int(attempt.paper_id))
    if paper is None or not paper.duration_sec:
        return attempt
    if _elapsed_seconds(attempt.started_at) < int(paper.duration_sec):
        return attempt

    # Expiration can be reached from multiple read/write entry points at the
    # same time (for example result refresh and manual submit at the deadline).
    # Re-lock the row here instead of relying on callers, because this helper is
    # also used by read APIs. Only the winner is allowed to finalize the attempt.
    locked = await db.execute(
        select(ExamAttempt).where(ExamAttempt.id == int(attempt.id)).with_for_update()
    )
    current = locked.scalar_one_or_none()
    if current is None:
        raise ExamStateError("考试记录不存在")
    if current.status in TERMINAL_ATTEMPT_STATUSES:
        attempt.status = current.status
        attempt.result_snapshot = current.result_snapshot
        return attempt
    await _finalize_attempt(db, current, terminal_status="expired")
    attempt.status = current.status
    attempt.result_snapshot = current.result_snapshot
    return attempt


async def start_attempt(
    db: AsyncSession, paper_id: int, user_id: int, request_id: str
) -> dict:
    request_id = str(request_id or "").strip()
    if len(request_id) < 8:
        raise ValueError("request_id 去除首尾空白后至少需要 8 个字符")
    paper, question_count, _ = await _load_paper_with_summary(db, paper_id)
    if paper.status != "published" or not paper.is_active:
        raise ExamNotFoundError("试卷不存在或已下架")
    if question_count <= 0:
        raise ExamStateError("试卷暂无可作答题目")

    existing_request = await db.scalar(
        select(ExamAttempt).where(
            ExamAttempt.user_id == user_id, ExamAttempt.request_id == request_id
        )
    )
    if existing_request is not None:
        if int(existing_request.paper_id) != int(paper_id):
            raise ExamStateError("request_id 已用于其他试卷")
        return await get_attempt_view(db, int(existing_request.id), user_id)

    existing_progress = await db.scalar(
        select(ExamAttempt)
        .where(
            ExamAttempt.user_id == user_id,
            ExamAttempt.paper_id == paper_id,
            ExamAttempt.status == "in_progress",
        )
        .order_by(ExamAttempt.started_at.desc(), ExamAttempt.id.desc())
    )
    if existing_progress is not None:
        await _ensure_attempt_not_expired(db, existing_progress)
        if existing_progress.status == "in_progress":
            return await get_attempt_view(db, int(existing_progress.id), user_id)

    items = list(
        (
            await db.execute(
                select(ExamPaperQuestion)
                .where(ExamPaperQuestion.paper_id == paper_id)
                .order_by(ExamPaperQuestion.position.asc())
            )
        )
        .scalars()
        .all()
    )
    if len(items) != question_count:
        raise ExamStateError("试卷题目结构异常")

    attempt = ExamAttempt(
        paper_id=paper.id,
        paper_version=paper.version,
        user_id=user_id,
        status="in_progress",
        request_id=request_id,
        started_at=utcnow(),
    )
    db.add(attempt)
    try:
        await db.flush()
    except IntegrityError:
        # Two starts can race with different request IDs. The database partial
        # unique index guarantees at most one in-progress attempt per user/paper;
        # after rollback, resolve either idempotency winner deterministically.
        await db.rollback()
        winner = await db.scalar(
            select(ExamAttempt).where(
                ExamAttempt.user_id == user_id, ExamAttempt.request_id == request_id
            )
        )
        if winner is not None and int(winner.paper_id) == int(paper_id):
            return await get_attempt_view(db, int(winner.id), user_id)
        winner = await db.scalar(
            select(ExamAttempt)
            .where(
                ExamAttempt.user_id == user_id,
                ExamAttempt.paper_id == paper_id,
                ExamAttempt.status == "in_progress",
            )
            .order_by(ExamAttempt.started_at.desc(), ExamAttempt.id.desc())
        )
        if winner is not None:
            return await get_attempt_view(db, int(winner.id), user_id)
        raise

    db.add_all(
        [
            ExamAnswer(
                attempt_id=attempt.id,
                exam_paper_question_id=item.id,
                question_id=item.question_id,
                question_version_id=item.question_version_id,
                used_time=0,
                marked_for_review=False,
            )
            for item in items
        ]
    )
    await db.commit()
    return await get_attempt_view(db, int(attempt.id), user_id)


async def get_attempt_view(db: AsyncSession, attempt_id: int, user_id: int) -> dict:
    attempt = await _get_attempt_for_user(db, attempt_id, user_id)
    # Keep this read endpoint side-effect free.  In particular, do not finalize
    # an elapsed attempt here: a client may be reopening after an offline period
    # with locally persisted answers that still need to be included in the
    # atomic submit request.  ``remaining_sec == 0`` is enough for the runner to
    # immediately enter auto-submit while preserving those pending answers.
    paper, question_count, total_score = await _load_paper_with_summary(
        db, int(attempt.paper_id)
    )
    rows = await _load_attempt_rows(db, int(attempt.id))
    if len(rows) != question_count:
        raise ExamStateError("考试题目快照不完整")
    elapsed = _elapsed_seconds(attempt.started_at)
    remaining = (
        max(0, int(paper.duration_sec) - elapsed) if paper.duration_sec else None
    )
    questions = []
    answers = []
    for answer, item, revision, subject in rows:
        if int(revision.question_id) != int(answer.question_id) or int(
            revision.id
        ) != int(item.question_version_id):
            raise ExamStateError("考试题目 revision 绑定异常")
        if str(revision.question_type or "") != QT_SINGLE_CHOICE:
            raise ExamStateError("考试包含非 single_choice 历史版本")
        questions.append(
            exam_read_projection.attempt_question(
                answer, item, revision, subject, sys.modules[__name__]
            )
        )
        answers.append(exam_read_projection.attempt_answer(answer, item))
    return exam_read_projection.attempt_view(
        attempt,
        paper,
        elapsed,
        remaining,
        question_count,
        total_score,
        questions,
        answers,
    )


async def _apply_final_submit_answers(
    db: AsyncSession,
    attempt: ExamAttempt,
    final_answers: list[dict] | None,
) -> None:
    """Apply unsynced client rows immediately before grading.

    The attempt row is already locked by ``submit_attempt``.  Applying the
    final pending rows and grading in the same database transaction means a
    submit can never observe a half-flushed client state.  Duplicate submit
    requests remain safe because terminal attempts return their immutable
    result snapshot before this helper is called.
    """

    if not final_answers:
        return

    rows = await db.execute(
        select(ExamAnswer, ExamPaperQuestion, QuestionVersion)
        .join(
            ExamPaperQuestion,
            ExamPaperQuestion.id == ExamAnswer.exam_paper_question_id,
        )
        .join(QuestionVersion, QuestionVersion.id == ExamAnswer.question_version_id)
        .where(ExamAnswer.attempt_id == int(attempt.id))
    )
    by_item = {
        int(item.id): (answer, revision)
        for answer, item, revision in rows.all()
        if int(item.paper_id) == int(attempt.paper_id)
    }

    seen: set[int] = set()
    now = utcnow()
    for payload in final_answers:
        item_id = int(payload.get("item_id") or 0)
        if item_id <= 0 or item_id in seen:
            raise ValueError("交卷答案中存在无效或重复题目")
        seen.add(item_id)

        row = by_item.get(item_id)
        if row is None:
            raise ExamNotFoundError("交卷答案包含不属于本次考试的题目")
        answer, revision = row

        normalized = str(payload.get("selected_answer") or "").strip().upper() or None
        if normalized is not None:
            options = _student_options(revision.options)
            valid_options = {str(key).strip().upper() for key in options}
            if normalized not in valid_options:
                raise ValueError("所选答案不在当前题目选项中")

        marked = bool(payload.get("marked_for_review", False))
        used_time = max(0, min(6 * 60 * 60, int(payload.get("used_time") or 0)))
        old_selected = str(answer.selected_answer or "").strip().upper() or None
        changed = False

        if normalized != old_selected:
            answer.selected_answer = normalized
            answer.answered_at = now if normalized else None
            changed = True
        if bool(answer.marked_for_review) != marked:
            answer.marked_for_review = marked
            changed = True
        if used_time > int(answer.used_time or 0):
            answer.used_time = used_time
            changed = True
        if changed:
            # This column already exists in the schema.  Keeping it monotonic is
            # useful for diagnosing duplicate/stale client writes and provides a
            # future optimistic-concurrency hook without a migration.
            answer.answer_revision = int(answer.answer_revision or 0) + 1


async def save_attempt_answer(
    db: AsyncSession,
    attempt_id: int,
    item_id: int,
    user_id: int,
    *,
    selected_answer: str | None | object = ...,
    marked_for_review: bool | None = None,
    used_time: int | None = None,
) -> dict:
    attempt = await _get_attempt_for_user(db, attempt_id, user_id, lock=True)
    if attempt.status != "in_progress":
        if attempt.status == "abandoned":
            raise ExamStateError("本次作答已取消，不能继续修改答案")
        raise ExamStateError("考试已结束，不能继续修改答案")

    # Important: answer PATCH is a persistence operation, not a terminal-state
    # transition.  Previously _ensure_attempt_not_expired() finalized the whole
    # attempt here as soon as the deadline was crossed.  At the exact countdown
    # boundary the client first flushes its current answer/time slice and then
    # POSTs /submit, so the PATCH could create the result/history record and
    # return 409 before the real submit request ran.
    #
    # Keep a very small grace window for the final network flush.  After that
    # window we still allow idempotent metadata/time persistence, but we reject
    # a changed choice so a stale or modified client cannot answer indefinitely
    # after the deadline.  Finalization remains owned by /submit (or the normal
    # lazy-expiry read/start paths).
    row = (
        await db.execute(
            select(ExamAnswer, ExamPaperQuestion, QuestionVersion, ExamPaper)
            .join(
                ExamPaperQuestion,
                ExamPaperQuestion.id == ExamAnswer.exam_paper_question_id,
            )
            .join(QuestionVersion, QuestionVersion.id == ExamAnswer.question_version_id)
            .join(ExamPaper, ExamPaper.id == ExamPaperQuestion.paper_id)
            .where(
                ExamAnswer.attempt_id == attempt.id,
                ExamPaperQuestion.id == item_id,
                ExamPaperQuestion.paper_id == attempt.paper_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise ExamNotFoundError("试卷题目不存在")
    answer, _item, revision, paper = row

    normalized = ...
    if selected_answer is not ...:
        normalized = str(selected_answer or "").strip().upper() or None
        if normalized is not None:
            options = _student_options(revision.options)
            if normalized not in {str(key).strip().upper() for key in options}:
                raise ValueError("所选答案不在当前题目选项中")

    deadline_overrun = 0
    if paper.duration_sec:
        deadline_overrun = max(
            0, _elapsed_seconds(attempt.started_at) - int(paper.duration_sec)
        )
    if (
        deadline_overrun > ANSWER_SYNC_DEADLINE_GRACE_SEC
        and normalized is not ...
        and normalized != (str(answer.selected_answer or "").strip().upper() or None)
    ):
        raise ExamStateError("考试已到时，不能再修改答案，请直接交卷")

    changed = False
    if normalized is not ...:
        current_selected = str(answer.selected_answer or "").strip().upper() or None
        if normalized != current_selected:
            answer.selected_answer = normalized
            answer.answered_at = utcnow() if normalized else None
            changed = True
    if marked_for_review is not None:
        next_marked = bool(marked_for_review)
        if bool(answer.marked_for_review) != next_marked:
            answer.marked_for_review = next_marked
            changed = True
    if used_time is not None:
        next_used_time = max(int(answer.used_time or 0), int(used_time))
        if next_used_time != int(answer.used_time or 0):
            answer.used_time = next_used_time
            changed = True
    if changed:
        answer.answer_revision = int(answer.answer_revision or 0) + 1
    await db.commit()
    return exam_read_projection.saved_answer(attempt, answer, item_id)


async def _create_projection_event(
    db: AsyncSession, practice_record_id: int, request_id: str
) -> None:
    from app.services.outbox_service import create_outbox

    await create_outbox(
        db,
        task_id=f"answer_projection:{practice_record_id}",
        task_type="answer_projection",
        payload={
            "practice_record_id": int(practice_record_id),
            "request_id": request_id,
        },
        schema_version=ANSWER_PROJECTION_TASK_SCHEMA_VERSION,
    )


async def _finalize_attempt(
    db: AsyncSession,
    attempt: ExamAttempt,
    *,
    terminal_status: str,
) -> dict:
    if attempt.status in TERMINAL_ATTEMPT_STATUSES:
        if not isinstance(attempt.result_snapshot, dict):
            raise ExamStateError("考试已结束但结果快照缺失")
        return dict(attempt.result_snapshot)
    if attempt.status != "in_progress":
        raise ExamStateError("当前考试状态不能交卷")
    if terminal_status not in TERMINAL_ATTEMPT_STATUSES:
        raise ValueError("无效终态")

    paper, question_count, total_score = await _load_paper_with_summary(
        db, int(attempt.paper_id)
    )
    rows = await _load_attempt_rows(db, int(attempt.id))
    if len(rows) != question_count:
        raise ExamStateError("考试题目快照不完整，禁止交卷")

    revision_ids = [int(revision.id) for _answer, _item, revision, _subject in rows]
    kp_names = await load_revision_kp_names(db, revision_ids)
    now = utcnow()
    duration = _elapsed_seconds(attempt.started_at, now)
    if paper.duration_sec:
        duration = min(duration, int(paper.duration_sec))

    total_correct = 0
    answered_count = 0
    earned_total = Decimal("0.00")
    subject_stats: dict[int, dict] = {}
    kp_losses: Counter[str] = Counter()
    kp_lost_score: defaultdict[str, float] = defaultdict(float)
    result_questions: list[dict] = []
    wrong_for_prewarm = []

    for answer, item, revision, subject in rows:
        if int(revision.id) != int(answer.question_version_id) or int(
            revision.question_id
        ) != int(answer.question_id):
            raise ExamStateError("考试答案与固定 revision 绑定异常")
        if str(revision.question_type or "") != QT_SINGLE_CHOICE:
            raise ExamStateError("固定 revision 已违反 V1 单选题约束")
        selected = str(answer.selected_answer or "").strip().upper() or None
        item_score = Decimal(str(item.score)).quantize(Decimal("0.01"))
        is_correct: bool | None = None
        earned = Decimal("0.00")
        status = "unanswered"
        if selected:
            answered_count += 1
            is_correct = bool(
                is_answer_correct(
                    selected, str(revision.answer or ""), QT_SINGLE_CHOICE
                )
            )
            status = "correct" if is_correct else "wrong"
            if is_correct:
                total_correct += 1
                earned = item_score
                earned_total += item_score
        answer.is_correct = is_correct
        answer.score = earned

        stats = subject_stats.setdefault(
            int(subject.id),
            {
                "subject_id": int(subject.id),
                "subject_code": subject.code,
                "subject_name": subject.name,
                "question_count": 0,
                "answered_count": 0,
                "correct_count": 0,
                "score": Decimal("0.00"),
                "total_score": Decimal("0.00"),
            },
        )
        stats["question_count"] += 1
        stats["total_score"] += item_score
        if selected:
            stats["answered_count"] += 1
        if is_correct:
            stats["correct_count"] += 1
            stats["score"] += item_score

        names = kp_names.get(int(revision.id), [])
        if status == "wrong":
            for name in names:
                kp_losses[str(name)] += 1
                kp_lost_score[str(name)] += float(item_score)

        wrong_question_id = None
        error_diagnosis_payload = None
        if selected and answer.practice_record_id is None:
            record = PracticeRecord(
                user_id=attempt.user_id,
                question_id=int(answer.question_id),
                question_version_id=int(answer.question_version_id),
                subject_id=int(item.section_subject_id),
                question_type=QT_SINGLE_CHOICE,
                user_answer=selected,
                is_correct=bool(is_correct),
                used_time=int(answer.used_time or 0),
                answered_at=answer.answered_at or now,
                mode="exam",
                projection_state="pending",
            )
            db.add(record)
            await db.flush()
            answer.practice_record_id = int(record.id)
            if not is_correct:
                from app.services.wrong_question_service import record_wrong

                wrong = await record_wrong(
                    db,
                    attempt.user_id,
                    int(answer.question_id),
                    selected,
                    question_version_id=int(answer.question_version_id),
                    commit=False,
                )
                wrong_for_prewarm.append(wrong)
                wrong_question_id = int(wrong.id)
                from app.services import error_diagnosis_service

                diagnosis = await error_diagnosis_service.record_error_event(
                    db,
                    user_id=int(attempt.user_id),
                    wrong_question_id=int(wrong.id),
                    question_id=int(answer.question_id),
                    question_version_id=int(answer.question_version_id),
                    practice_record_id=int(record.id),
                    exam_answer_id=int(answer.id),
                    source_context="exam",
                    user_answer=selected,
                    occurred_at=answer.answered_at or now,
                    queue_ai=False,
                )
                error_diagnosis_payload = error_diagnosis_service.serialize_diagnosis(
                    diagnosis
                )
            await _create_projection_event(
                db,
                int(record.id),
                request_id=f"exam:{attempt.id}:{item.id}",
            )

        result_questions.append(
            exam_result_projection.question_result(
                answer,
                item,
                revision,
                subject,
                item_score,
                earned,
                selected,
                is_correct,
                status,
                names,
                wrong_question_id,
                error_diagnosis_payload,
                sys.modules[__name__],
            )
        )

    subject_breakdown = exam_result_projection.subject_breakdown(
        subject_stats, sys.modules[__name__]
    )

    weak_kps = exam_result_projection.weak_knowledge_points(kp_losses, kp_lost_score)
    wrong_count = answered_count - total_correct
    unanswered_count = question_count - answered_count
    result = exam_result_projection.result_snapshot(
        attempt,
        paper,
        terminal_status,
        now,
        duration,
        {
            "question_count": question_count,
            "answered_count": answered_count,
            "total_correct": total_correct,
            "wrong_count": wrong_count,
            "unanswered_count": unanswered_count,
            "earned_total": earned_total,
            "total_score": total_score,
        },
        subject_breakdown,
        weak_kps,
        result_questions,
        sys.modules[__name__],
    )
    attempt.status = terminal_status
    attempt.submitted_at = now
    attempt.duration_sec = int(duration)
    attempt.answered_count = int(answered_count)
    attempt.correct_count = int(total_correct)
    attempt.score = earned_total

    # ``result_snapshot`` is stored in a SQLAlchemy JSON column. Nested payloads
    # (notably error-diagnosis metadata) may contain ``datetime`` values that
    # FastAPI can serialize in a response but the database JSON serializer cannot.
    # Normalize the complete snapshot at the persistence boundary so this path
    # remains safe even when future nested result fields add datetime/Decimal types.
    result = jsonable_encoder(result)
    attempt.result_snapshot = result
    await db.commit()

    if wrong_for_prewarm:
        try:
            from app.ai.prewarm_revision import build_prewarm_revision
            from app.services.ai_prewarm_worker import enqueue_prewarm

            for wrong in wrong_for_prewarm:
                revision = build_prewarm_revision(
                    review_count=wrong.review_count,
                    wrong_answer=wrong.wrong_answer,
                )
                await enqueue_prewarm(wrong.id, attempt.user_id, revision=revision)
        except Exception:
            pass
    return result


async def abandon_attempt(db: AsyncSession, attempt_id: int, user_id: int) -> dict:
    """Cancel a resumable attempt without producing an exam result/history row.

    The transition is intentionally idempotent.  A conditional UPDATE is used
    in addition to the PostgreSQL row lock so a stale client cannot overwrite a
    concurrent submit/expiry transition when running on a database without
    row-level ``FOR UPDATE`` semantics (notably local SQLite).
    """
    attempt = await _get_attempt_for_user(db, attempt_id, user_id, lock=True)
    if attempt.status == "abandoned":
        return {"id": int(attempt.id), "status": attempt.status}
    if attempt.status != "in_progress":
        raise ExamStateError("考试已结束，不能取消本次作答")

    paper = await db.get(ExamPaper, int(attempt.paper_id))
    if paper is None:
        raise ExamNotFoundError("试卷不存在")

    now = utcnow()
    elapsed = _elapsed_seconds(attempt.started_at, now)
    if paper.duration_sec and elapsed >= int(paper.duration_sec):
        # Once the timer has elapsed the attempt belongs to the submit/expiry
        # state machine.  Do not let a stale paper-list screen use cancellation
        # to bypass the timed-exam result.
        raise ExamStateError("考试已到时，不能取消本次作答，请完成交卷")

    transition = await db.execute(
        update(ExamAttempt)
        .where(
            ExamAttempt.id == int(attempt.id),
            ExamAttempt.user_id == int(user_id),
            ExamAttempt.status == "in_progress",
        )
        .values(
            status="abandoned",
            submitted_at=now,
            duration_sec=elapsed,
            result_snapshot=None,
        )
    )

    if transition.rowcount != 1:
        current = await _get_attempt_for_user(db, attempt_id, user_id)
        if current.status == "abandoned":
            return {"id": int(current.id), "status": current.status}
        raise ExamStateError("作答状态已变化，不能取消本次作答")

    await db.commit()
    return {"id": int(attempt.id), "status": "abandoned"}


async def submit_attempt(
    db: AsyncSession,
    attempt_id: int,
    user_id: int,
    *,
    final_answers: list[dict] | None = None,
) -> dict:
    attempt = await _get_attempt_for_user(db, attempt_id, user_id, lock=True)
    if attempt.status in TERMINAL_ATTEMPT_STATUSES:
        if not isinstance(attempt.result_snapshot, dict):
            raise ExamStateError("考试结果快照缺失")
        return dict(attempt.result_snapshot)
    if attempt.status != "in_progress":
        if attempt.status == "abandoned":
            raise ExamStateError("本次作答已取消，不能交卷")
        raise ExamStateError("当前考试状态不能交卷")

    # Persist any locally pending answers and finalize under the same attempt
    # row lock.  This is the key reliability boundary: the client no longer has
    # to win a sequence of PATCH requests immediately before POST /submit.
    await _apply_final_submit_answers(db, attempt, final_answers)

    paper = await db.get(ExamPaper, int(attempt.paper_id))
    if paper is None:
        raise ExamNotFoundError("试卷不存在")
    elapsed = _elapsed_seconds(attempt.started_at)
    terminal_status = (
        "expired"
        if paper.duration_sec and elapsed >= int(paper.duration_sec)
        else "submitted"
    )
    return await _finalize_attempt(db, attempt, terminal_status=terminal_status)


async def get_attempt_result(db: AsyncSession, attempt_id: int, user_id: int) -> dict:
    attempt = await _get_attempt_for_user(db, attempt_id, user_id)
    # Result lookup is read-only.  Never turn an elapsed in-progress attempt
    # into a history/result row from a GET request because the originating
    # client may still have an offline final-answer batch waiting to submit.
    if attempt.status not in TERMINAL_ATTEMPT_STATUSES:
        raise ExamStateError("考试尚未交卷")
    if not isinstance(attempt.result_snapshot, dict):
        raise ExamStateError("考试结果快照缺失")
    return dict(attempt.result_snapshot)


def _exam_history_paper_stats():
    """Compact immutable paper totals used by the history list.

    History intentionally does not hydrate ``result_snapshot``: a finalized
    snapshot contains every question and can be tens of KB per attempt.  The
    paper definition is immutable after publish, so count/score totals can be
    read from the normalized paper tables without loading those large JSON
    blobs.
    """
    return (
        select(
            ExamPaperQuestion.paper_id.label("paper_id"),
            func.count(ExamPaperQuestion.id).label("question_count"),
            func.coalesce(func.sum(ExamPaperQuestion.score), 0).label("total_score"),
        )
        .group_by(ExamPaperQuestion.paper_id)
        .subquery()
    )


def _exam_history_filters(user_id: int):
    return (
        ExamAttempt.user_id == user_id,
        ExamAttempt.status.in_(TERMINAL_ATTEMPT_STATUSES),
        # History is a finalized-result view, never an attempt list.  The
        # snapshot itself is deliberately not selected because it is large;
        # requiring it to exist is enough to exclude unfinished/partial rows.
        ExamAttempt.submitted_at.is_not(None),
        ExamAttempt.result_snapshot.is_not(None),
    )


def _history_row_to_item(row) -> dict:
    return exam_read_projection.history_item(row, sys.modules[__name__])


async def get_exam_history_overview(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Return timeline rows plus all-time aggregate statistics.

    The summary scans only scalar attempt/paper statistics and never loads the
    per-question result JSON, keeping the endpoint predictable as a user's
    history grows.  Rows are paginated so the mini-program can incrementally
    render long histories.
    """
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))
    paper_stats = _exam_history_paper_stats()
    filters = _exam_history_filters(user_id)

    question_count_expr = func.coalesce(paper_stats.c.question_count, 0)
    total_score_expr = func.coalesce(paper_stats.c.total_score, 0)
    accuracy_expr = case(
        (
            question_count_expr > 0,
            cast(ExamAttempt.correct_count, Float) / cast(question_count_expr, Float),
        ),
        else_=0.0,
    )
    summary_row = (
        await db.execute(
            select(
                func.count(ExamAttempt.id).label("completed_count"),
                func.coalesce(func.avg(cast(ExamAttempt.score, Float)), 0).label(
                    "average_choice_score"
                ),
                func.coalesce(func.avg(cast(total_score_expr, Float)), 0).label(
                    "average_total_choice_score"
                ),
                func.coalesce(func.avg(accuracy_expr), 0).label("average_accuracy"),
                func.coalesce(func.max(cast(ExamAttempt.score, Float)), 0).label(
                    "best_choice_score"
                ),
                func.coalesce(func.max(accuracy_expr), 0).label("best_accuracy"),
            )
            .join(ExamPaper, ExamPaper.id == ExamAttempt.paper_id)
            .outerjoin(paper_stats, paper_stats.c.paper_id == ExamAttempt.paper_id)
            .where(*filters)
        )
    ).one()

    completed_count = int(summary_row.completed_count or 0)
    summary = exam_read_projection.history_summary(summary_row, completed_count)

    page_rows = (
        await db.execute(
            select(
                ExamAttempt.id.label("attempt_id"),
                ExamAttempt.paper_id.label("paper_id"),
                ExamAttempt.status.label("status"),
                ExamAttempt.started_at.label("started_at"),
                ExamAttempt.submitted_at.label("submitted_at"),
                ExamAttempt.duration_sec.label("duration_sec"),
                ExamAttempt.answered_count.label("answered_count"),
                ExamAttempt.correct_count.label("correct_count"),
                ExamAttempt.score.label("choice_score"),
                ExamPaper.title.label("paper_title"),
                ExamPaper.paper_type.label("paper_type"),
                ExamPaper.year.label("year"),
                func.coalesce(paper_stats.c.question_count, 0).label("question_count"),
                func.coalesce(paper_stats.c.total_score, 0).label("total_choice_score"),
            )
            .join(ExamPaper, ExamPaper.id == ExamAttempt.paper_id)
            .outerjoin(paper_stats, paper_stats.c.paper_id == ExamAttempt.paper_id)
            .where(*filters)
            .order_by(ExamAttempt.submitted_at.desc(), ExamAttempt.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = [_history_row_to_item(row) for row in page_rows]

    return {
        "summary": summary,
        "items": items,
        "total": completed_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < completed_count,
    }


async def list_exam_history(
    db: AsyncSession, user_id: int, limit: int = 50
) -> list[dict]:
    """Backward-compatible list endpoint used by older mini-program builds."""
    overview = await get_exam_history_overview(
        db, user_id, limit=max(1, min(int(limit or 50), 100)), offset=0
    )
    return overview["items"]
