from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subject_scope import EXAM408_CORE_CODES
from app.core.time_utils import normalize_to_naive_utc, utcnow
from app.features.question_type import QT_SINGLE_CHOICE
from app.models.admin import QuestionVersion, Subject
from app.models.exam import ExamAnswer, ExamAttempt, ExamPaper, ExamPaperQuestion
from app.models.practice_record import PracticeRecord
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
    for key in ("source_snapshot_url", "source_snapshot_full_page", "visual_regions", "visual_region_ids"):
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
                next_value["text"] = " ".join(text.replace("\r", "\n").splitlines()).strip()
            clean[str(key)] = next_value
        elif isinstance(value, str):
            clean[str(key)] = " ".join(value.replace("\r", "\n").splitlines()).strip()
        else:
            clean[str(key)] = value
    return clean


async def _load_paper_with_summary(db: AsyncSession, paper_id: int) -> tuple[ExamPaper, int, float]:
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
        .order_by(ExamPaper.year.desc().nullslast(), ExamPaper.created_at.desc(), ExamPaper.id.desc())
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

    result: list[dict] = []
    for paper, question_count, total_score in papers:
        attempts = attempts_by_paper.get(int(paper.id), [])
        latest = attempts[0] if attempts else None
        latest_status = latest.status if latest else None
        if (
            latest is not None
            and latest_status == "in_progress"
            and paper.duration_sec
            and _elapsed_seconds(latest.started_at) >= int(paper.duration_sec)
        ):
            # Present an elapsed attempt as expired without mutating state in a
            # read-only list request. Starting a new attempt will finalize it.
            latest_status = "expired"
        terminal_scores = [_money(a.score) for a in attempts if a.status in TERMINAL_ATTEMPT_STATUSES]
        result.append({
            "id": int(paper.id),
            "title": paper.title,
            "paper_type": paper.paper_type,
            "year": paper.year,
            "source": paper.source,
            "duration_sec": paper.duration_sec,
            "version": int(paper.version),
            "question_count": int(question_count),
            "total_choice_score": _money(total_score),
            "latest_attempt_id": int(latest.id) if latest else None,
            "latest_attempt_status": latest_status,
            "best_choice_score": max(terminal_scores) if terminal_scores else None,
        })
    return result


async def get_published_paper_detail(db: AsyncSession, paper_id: int, user_id: int) -> dict:
    paper, question_count, total_score = await _load_paper_with_summary(db, paper_id)
    if paper.status != "published" or not paper.is_active:
        raise ExamNotFoundError("试卷不存在或已下架")
    attempts = list((await db.execute(
        select(ExamAttempt)
        .where(ExamAttempt.user_id == user_id, ExamAttempt.paper_id == paper_id)
        .order_by(ExamAttempt.started_at.desc(), ExamAttempt.id.desc())
    )).scalars().all())
    latest = attempts[0] if attempts else None
    latest_status = latest.status if latest else None
    if (
        latest is not None
        and latest_status == "in_progress"
        and paper.duration_sec
        and _elapsed_seconds(latest.started_at) >= int(paper.duration_sec)
    ):
        latest_status = "expired"
    terminal_scores = [_money(a.score) for a in attempts if a.status in TERMINAL_ATTEMPT_STATUSES]
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
    return {
        "id": int(paper.id),
        "title": paper.title,
        "paper_type": paper.paper_type,
        "year": paper.year,
        "source": paper.source,
        "duration_sec": paper.duration_sec,
        "version": int(paper.version),
        "question_count": question_count,
        "total_choice_score": total_score,
        "latest_attempt_id": int(latest.id) if latest else None,
        "latest_attempt_status": latest_status,
        "best_choice_score": max(terminal_scores) if terminal_scores else None,
        "subject_distribution": [
            {
                "subject_id": int(sid),
                "subject_code": code,
                "subject_name": name,
                "question_count": int(count),
                "total_score": _money(score),
            }
            for sid, code, name, count, score in dist_rows.all()
        ],
    }


async def _get_attempt_for_user(
    db: AsyncSession,
    attempt_id: int,
    user_id: int,
    *,
    lock: bool = False,
) -> ExamAttempt:
    stmt = select(ExamAttempt).where(ExamAttempt.id == attempt_id, ExamAttempt.user_id == user_id)
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
        .join(ExamPaperQuestion, ExamPaperQuestion.id == ExamAnswer.exam_paper_question_id)
        .join(QuestionVersion, QuestionVersion.id == ExamAnswer.question_version_id)
        .join(Subject, Subject.id == ExamPaperQuestion.section_subject_id)
        .where(ExamAnswer.attempt_id == attempt_id)
        .order_by(ExamPaperQuestion.position.asc(), ExamPaperQuestion.id.asc())
    )
    return rows.all()


async def _ensure_attempt_not_expired(db: AsyncSession, attempt: ExamAttempt) -> ExamAttempt:
    if attempt.status != "in_progress":
        return attempt
    paper = await db.get(ExamPaper, int(attempt.paper_id))
    if paper is None or not paper.duration_sec:
        return attempt
    if _elapsed_seconds(attempt.started_at) < int(paper.duration_sec):
        return attempt
    await _finalize_attempt(db, attempt, terminal_status="expired")
    return attempt


async def start_attempt(db: AsyncSession, paper_id: int, user_id: int, request_id: str) -> dict:
    request_id = str(request_id or "").strip()
    if len(request_id) < 8:
        raise ValueError("request_id 去除首尾空白后至少需要 8 个字符")
    paper, question_count, _ = await _load_paper_with_summary(db, paper_id)
    if paper.status != "published" or not paper.is_active:
        raise ExamNotFoundError("试卷不存在或已下架")
    if question_count <= 0:
        raise ExamStateError("试卷暂无可作答题目")

    existing_request = await db.scalar(
        select(ExamAttempt).where(ExamAttempt.user_id == user_id, ExamAttempt.request_id == request_id)
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

    items = list((await db.execute(
        select(ExamPaperQuestion)
        .where(ExamPaperQuestion.paper_id == paper_id)
        .order_by(ExamPaperQuestion.position.asc())
    )).scalars().all())
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
            select(ExamAttempt).where(ExamAttempt.user_id == user_id, ExamAttempt.request_id == request_id)
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

    db.add_all([
        ExamAnswer(
            attempt_id=attempt.id,
            exam_paper_question_id=item.id,
            question_id=item.question_id,
            question_version_id=item.question_version_id,
            used_time=0,
            marked_for_review=False,
        )
        for item in items
    ])
    await db.commit()
    return await get_attempt_view(db, int(attempt.id), user_id)


async def get_attempt_view(db: AsyncSession, attempt_id: int, user_id: int) -> dict:
    attempt = await _get_attempt_for_user(db, attempt_id, user_id)
    await _ensure_attempt_not_expired(db, attempt)
    paper, question_count, total_score = await _load_paper_with_summary(db, int(attempt.paper_id))
    rows = await _load_attempt_rows(db, int(attempt.id))
    if len(rows) != question_count:
        raise ExamStateError("考试题目快照不完整")
    elapsed = _elapsed_seconds(attempt.started_at)
    remaining = max(0, int(paper.duration_sec) - elapsed) if paper.duration_sec else None
    questions = []
    answers = []
    for answer, item, revision, subject in rows:
        if int(revision.question_id) != int(answer.question_id) or int(revision.id) != int(item.question_version_id):
            raise ExamStateError("考试题目 revision 绑定异常")
        if str(revision.question_type or "") != QT_SINGLE_CHOICE:
            raise ExamStateError("考试包含非 single_choice 历史版本")
        questions.append({
            "item_id": int(item.id),
            "question_id": int(answer.question_id),
            "question_version_id": int(answer.question_version_id),
            "position": int(item.position),
            "score": _money(item.score),
            "subject_id": int(item.section_subject_id),
            "subject_code": subject.code,
            "subject_name": subject.name,
            "question_type": QT_SINGLE_CHOICE,
            "content": _student_content(revision.content),
            "options": _student_options(revision.options),
            "image_url": revision.image_url,
        })
        answers.append({
            "item_id": int(item.id),
            "selected_answer": answer.selected_answer,
            "marked_for_review": bool(answer.marked_for_review),
            "used_time": int(answer.used_time or 0),
            "answered_at": answer.answered_at,
        })
    return {
        "id": int(attempt.id),
        "paper_id": int(paper.id),
        "paper_title": paper.title,
        "paper_type": paper.paper_type,
        "year": paper.year,
        "status": attempt.status,
        "started_at": attempt.started_at,
        "duration_limit_sec": paper.duration_sec,
        "elapsed_sec": elapsed,
        "remaining_sec": remaining,
        "question_count": question_count,
        "total_choice_score": total_score,
        "questions": questions,
        "answers": answers,
    }


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
    await _ensure_attempt_not_expired(db, attempt)
    if attempt.status != "in_progress":
        raise ExamStateError("考试已交卷，不能继续修改答案")
    row = (
        await db.execute(
            select(ExamAnswer, ExamPaperQuestion, QuestionVersion)
            .join(ExamPaperQuestion, ExamPaperQuestion.id == ExamAnswer.exam_paper_question_id)
            .join(QuestionVersion, QuestionVersion.id == ExamAnswer.question_version_id)
            .where(
                ExamAnswer.attempt_id == attempt.id,
                ExamPaperQuestion.id == item_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise ExamNotFoundError("试卷题目不存在")
    answer, _item, revision = row
    if selected_answer is not ...:
        normalized = str(selected_answer or "").strip().upper() or None
        if normalized is not None:
            options = _student_options(revision.options)
            if normalized not in {str(key).strip().upper() for key in options}:
                raise ValueError("所选答案不在当前题目选项中")
        answer.selected_answer = normalized
        answer.answered_at = utcnow() if normalized else None
    if marked_for_review is not None:
        answer.marked_for_review = bool(marked_for_review)
    if used_time is not None:
        answer.used_time = max(int(answer.used_time or 0), int(used_time))
    await db.commit()
    return {
        "attempt_id": int(attempt.id),
        "status": attempt.status,
        "answer": {
            "item_id": int(item_id),
            "selected_answer": answer.selected_answer,
            "marked_for_review": bool(answer.marked_for_review),
            "used_time": int(answer.used_time or 0),
            "answered_at": answer.answered_at,
        },
    }


async def _create_projection_event(db: AsyncSession, practice_record_id: int, request_id: str) -> None:
    from app.services.outbox_service import create_outbox

    await create_outbox(
        db,
        task_id=f"answer_projection:{practice_record_id}",
        task_type="answer_projection",
        payload={"practice_record_id": int(practice_record_id), "request_id": request_id},
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

    paper, question_count, total_score = await _load_paper_with_summary(db, int(attempt.paper_id))
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
        if int(revision.id) != int(answer.question_version_id) or int(revision.question_id) != int(answer.question_id):
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
            is_correct = bool(is_answer_correct(selected, str(revision.answer or ""), QT_SINGLE_CHOICE))
            status = "correct" if is_correct else "wrong"
            if is_correct:
                total_correct += 1
                earned = item_score
                earned_total += item_score
        answer.is_correct = is_correct
        answer.score = earned

        stats = subject_stats.setdefault(int(subject.id), {
            "subject_id": int(subject.id),
            "subject_code": subject.code,
            "subject_name": subject.name,
            "question_count": 0,
            "answered_count": 0,
            "correct_count": 0,
            "score": Decimal("0.00"),
            "total_score": Decimal("0.00"),
        })
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
                    queue_ai=True,
                )
                error_diagnosis_payload = error_diagnosis_service.serialize_diagnosis(diagnosis)
            await _create_projection_event(
                db,
                int(record.id),
                request_id=f"exam:{attempt.id}:{item.id}",
            )

        result_questions.append({
            "item_id": int(item.id),
            "question_id": int(answer.question_id),
            "question_version_id": int(answer.question_version_id),
            "position": int(item.position),
            "subject_id": int(subject.id),
            "subject_code": subject.code,
            "subject_name": subject.name,
            "score": _money(item_score),
            "earned_score": _money(earned),
            "selected_answer": selected,
            "correct_answer": str(revision.answer or ""),
            "is_correct": is_correct,
            "status": status,
            "marked_for_review": bool(answer.marked_for_review),
            "used_time": int(answer.used_time or 0),
            "content": _student_content(revision.content),
            "options": _student_options(revision.options),
            "analysis": revision.analysis,
            "image_url": revision.image_url,
            "knowledge_points": list(names),
            "wrong_question_id": wrong_question_id,
            "error_diagnosis": error_diagnosis_payload,
        })

    subject_breakdown = []
    for stats in subject_stats.values():
        answered = int(stats["answered_count"])
        correct = int(stats["correct_count"])
        subject_breakdown.append({
            "subject_id": stats["subject_id"],
            "subject_code": stats["subject_code"],
            "subject_name": stats["subject_name"],
            "question_count": int(stats["question_count"]),
            "answered_count": answered,
            "correct_count": correct,
            "score": _money(stats["score"]),
            "total_score": _money(stats["total_score"]),
            "accuracy": round(correct / int(stats["question_count"]), 4) if int(stats["question_count"]) else 0.0,
        })
    subject_order = {code: idx for idx, code in enumerate(EXAM408_CORE_CODES)}
    subject_breakdown.sort(key=lambda x: subject_order.get(x["subject_code"], 99))

    weak_kps = [
        {"name": name, "miss_count": int(count), "lost_score": round(kp_lost_score[name], 2)}
        for name, count in kp_losses.most_common(8)
    ]
    wrong_count = answered_count - total_correct
    unanswered_count = question_count - answered_count
    result = {
        "attempt_id": int(attempt.id),
        "paper_id": int(paper.id),
        "paper_title": paper.title,
        "paper_type": paper.paper_type,
        "year": paper.year,
        "attempt_status": terminal_status,
        "started_at": normalize_to_naive_utc(attempt.started_at).isoformat(),
        "submitted_at": normalize_to_naive_utc(now).isoformat(),
        "duration_sec": int(duration),
        "question_count": int(question_count),
        "answered_count": int(answered_count),
        "correct_count": int(total_correct),
        "wrong_count": int(wrong_count),
        "unanswered_count": int(unanswered_count),
        "choice_score": _money(earned_total),
        "total_choice_score": _money(total_score),
        "accuracy": round(total_correct / question_count, 4) if question_count else 0.0,
        "subject_breakdown": subject_breakdown,
        "weak_knowledge_points": weak_kps,
        "questions": result_questions,
    }
    attempt.status = terminal_status
    attempt.submitted_at = now
    attempt.duration_sec = int(duration)
    attempt.answered_count = int(answered_count)
    attempt.correct_count = int(total_correct)
    attempt.score = earned_total
    attempt.result_snapshot = result
    await db.commit()

    if wrong_for_prewarm:
        try:
            from app.services.ai_prewarm_worker import (
                build_prewarm_revision,
                enqueue_prewarm,
            )

            for wrong in wrong_for_prewarm:
                revision = build_prewarm_revision(
                    review_count=wrong.review_count,
                    wrong_answer=wrong.wrong_answer,
                )
                await enqueue_prewarm(wrong.id, attempt.user_id, revision=revision)
        except Exception:
            pass
    return result


async def submit_attempt(db: AsyncSession, attempt_id: int, user_id: int) -> dict:
    attempt = await _get_attempt_for_user(db, attempt_id, user_id, lock=True)
    if attempt.status in TERMINAL_ATTEMPT_STATUSES:
        if not isinstance(attempt.result_snapshot, dict):
            raise ExamStateError("考试结果快照缺失")
        return dict(attempt.result_snapshot)
    await _ensure_attempt_not_expired(db, attempt)
    if attempt.status in TERMINAL_ATTEMPT_STATUSES:
        return dict(attempt.result_snapshot or {})
    return await _finalize_attempt(db, attempt, terminal_status="submitted")


async def get_attempt_result(db: AsyncSession, attempt_id: int, user_id: int) -> dict:
    attempt = await _get_attempt_for_user(db, attempt_id, user_id)
    await _ensure_attempt_not_expired(db, attempt)
    if attempt.status not in TERMINAL_ATTEMPT_STATUSES:
        raise ExamStateError("考试尚未交卷")
    if not isinstance(attempt.result_snapshot, dict):
        raise ExamStateError("考试结果快照缺失")
    return dict(attempt.result_snapshot)


async def list_exam_history(db: AsyncSession, user_id: int, limit: int = 50) -> list[dict]:
    attempts = list((await db.execute(
        select(ExamAttempt)
        .where(ExamAttempt.user_id == user_id, ExamAttempt.status.in_(TERMINAL_ATTEMPT_STATUSES))
        .order_by(ExamAttempt.submitted_at.desc(), ExamAttempt.id.desc())
        .limit(limit)
    )).scalars().all())
    result: list[dict] = []
    for attempt in attempts:
        snapshot = attempt.result_snapshot if isinstance(attempt.result_snapshot, dict) else {}
        result.append({
            "attempt_id": int(attempt.id),
            "paper_id": int(attempt.paper_id),
            "paper_title": snapshot.get("paper_title") or f"试卷 #{attempt.paper_id}",
            "paper_type": snapshot.get("paper_type") or "mock_choice",
            "year": snapshot.get("year"),
            "status": attempt.status,
            "started_at": attempt.started_at,
            "submitted_at": attempt.submitted_at,
            "duration_sec": int(attempt.duration_sec or 0),
            "question_count": int(snapshot.get("question_count") or 0),
            "answered_count": int(attempt.answered_count or 0),
            "correct_count": int(attempt.correct_count or 0),
            "choice_score": _money(attempt.score),
            "total_choice_score": _money(snapshot.get("total_choice_score") or 0),
            "accuracy": float(snapshot.get("accuracy") or 0),
        })
    return result
