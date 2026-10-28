"""Today's study-plan completion facts from durable activity sources.

The loader owns the bounded day-window queries; category allocation and rounding
remain in :mod:`app.services.study_plan_rules`.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.time_utils import study_day_utc_range
from app.models.admin import QuestionVersion
from app.models.exam import ExamAttempt
from app.models.pomodoro import PomodoroSession, PomodoroSubjectAllocation
from app.models.practice_session import PracticeSession
from app.models.review_scheduler import ReviewRecord
from app.services.pomodoro_attribution import (
    split_session_duration_by_study_day,
    split_session_duration_excluding_intervals,
)
from app.services.study_plan_rules import (
    ceil_minutes,
    completed_by_category,
    focus_duration_for_subject_scope,
    study_day_seconds,
)


async def load_today_completion(
    db: AsyncSession,
    user_id: int,
    *,
    today: date,
    planned: dict[str, int],
    all_408_ids: list[int],
    core_408_ids: list[int],
    day_start_minute: int,
) -> tuple[dict[str, int], int, int]:
    start_utc, end_utc = study_day_utc_range(today, day_start_minute)
    review_count = await _load_review_count(
        db, user_id, start_utc=start_utc, end_utc=end_utc, core_408_ids=core_408_ids
    )
    practice_rows = await _load_practice_rows(
        db, user_id, start_utc=start_utc, end_utc=end_utc, all_408_ids=all_408_ids
    )
    smart_minutes, other_minutes, activity_spans = _practice_minutes(
        practice_rows, today=today, day_start_minute=day_start_minute
    )
    exam_rows = await _load_exam_rows(db, user_id, start_utc=start_utc, end_utc=end_utc)
    exam_minutes, exam_spans = _exam_minutes(
        exam_rows, today=today, day_start_minute=day_start_minute
    )
    activity_spans.extend(exam_spans)
    focus_minutes, supplemental_focus_minutes = await _load_focus_minutes(
        db,
        user_id,
        all_408_ids=all_408_ids,
        today=today,
        start_utc=start_utc,
        end_utc=end_utc,
        day_start_minute=day_start_minute,
        activity_spans=activity_spans,
    )
    completed = completed_by_category(
        review_count=review_count,
        smart_minutes=smart_minutes,
        exam_minutes=exam_minutes,
        other_minutes=other_minutes,
        planned=planned,
    )
    return completed, focus_minutes, supplemental_focus_minutes


async def _load_review_count(
    db: AsyncSession,
    user_id: int,
    *,
    start_utc,
    end_utc,
    core_408_ids: list[int],
) -> int:
    if not core_408_ids:
        return 0
    return int(
        (
            await db.execute(
                select(func.count(ReviewRecord.id))
                .join(
                    QuestionVersion,
                    QuestionVersion.id == ReviewRecord.question_version_id,
                )
                .where(
                    ReviewRecord.user_id == user_id,
                    QuestionVersion.subject_id.in_(core_408_ids),
                    ReviewRecord.reviewed_at >= start_utc,
                    ReviewRecord.reviewed_at < end_utc,
                )
            )
        ).scalar_one()
        or 0
    )


async def _load_practice_rows(
    db: AsyncSession,
    user_id: int,
    *,
    start_utc,
    end_utc,
    all_408_ids: list[int],
):
    if not all_408_ids:
        return []
    return (
        await db.execute(
            select(
                PracticeSession.started_at,
                PracticeSession.finished_at,
                PracticeSession.mode,
                PracticeSession.duration_sec,
            ).where(
                PracticeSession.user_id == user_id,
                PracticeSession.subject_id.in_(all_408_ids),
                PracticeSession.status == "completed",
                PracticeSession.started_at < end_utc,
                PracticeSession.finished_at > start_utc,
            )
        )
    ).all()


def _practice_minutes(
    practice_rows, *, today: date, day_start_minute: int
) -> tuple[int, int, list[tuple]]:
    smart_sec = 0
    other_sec = 0
    activity_spans: list[tuple] = []
    for row in practice_rows:
        contributed = study_day_seconds(
            start=row.started_at,
            end=row.finished_at,
            duration_sec=row.duration_sec,
            target_day=today,
            day_start_minute=day_start_minute,
        )
        if str(row.mode or "") == "smart":
            smart_sec += contributed
        else:
            other_sec += contributed
        if row.finished_at > row.started_at:
            activity_spans.append((row.started_at, row.finished_at))
    return ceil_minutes(smart_sec), ceil_minutes(other_sec), activity_spans


async def _load_exam_rows(
    db: AsyncSession, user_id: int, *, start_utc, end_utc
):
    return (
        await db.execute(
            select(
                ExamAttempt.started_at,
                ExamAttempt.submitted_at,
                ExamAttempt.duration_sec,
            ).where(
                ExamAttempt.user_id == user_id,
                ExamAttempt.submitted_at.is_not(None),
                ExamAttempt.status.in_(("submitted", "expired")),
                ExamAttempt.started_at < end_utc,
                ExamAttempt.submitted_at > start_utc,
            )
        )
    ).all()


def _exam_minutes(
    exam_rows, *, today: date, day_start_minute: int
) -> tuple[int, list[tuple]]:
    exam_sec = 0
    spans: list[tuple] = []
    for row in exam_rows:
        exam_sec += study_day_seconds(
            start=row.started_at,
            end=row.submitted_at,
            duration_sec=row.duration_sec,
            target_day=today,
            day_start_minute=day_start_minute,
        )
        if row.submitted_at is not None and row.submitted_at > row.started_at:
            spans.append((row.started_at, row.submitted_at))
    return ceil_minutes(exam_sec), spans


async def _load_pomodoro_sessions(
    db: AsyncSession,
    user_id: int,
    *,
    all_408_ids: list[int],
    start_utc,
    end_utc,
):
    if not all_408_ids:
        return []
    return (
        (
            await db.execute(
                select(PomodoroSession)
                .options(
                    selectinload(PomodoroSession.pause_intervals),
                    selectinload(PomodoroSession.subject_allocations),
                )
                .where(
                    PomodoroSession.user_id == user_id,
                    or_(
                        PomodoroSession.subject_id.in_(all_408_ids),
                        PomodoroSession.id.in_(
                            select(PomodoroSubjectAllocation.session_id).where(
                                PomodoroSubjectAllocation.subject_id.in_(all_408_ids)
                            )
                        ),
                    ),
                    PomodoroSession.status == "completed",
                    PomodoroSession.end_time.is_not(None),
                    PomodoroSession.start_time < end_utc,
                    PomodoroSession.end_time > start_utc,
                )
            )
        )
        .scalars()
        .all()
    )


async def _load_focus_minutes(
    db: AsyncSession,
    user_id: int,
    *,
    all_408_ids: list[int],
    today: date,
    start_utc,
    end_utc,
    day_start_minute: int,
    activity_spans: list[tuple],
) -> tuple[int, int]:
    # Pomodoro focus is a *supplement* to durable practice/exam facts. The raw
    # focus total remains visible as focus_minutes, while only active focus wall
    # time not covered by practice/exam intervals can advance the completion
    # budget. Session pauses are removed before coverage is applied.
    focus_sec = 0
    focus_supplement_sec = 0
    subject_scope = set(all_408_ids)
    sessions = await _load_pomodoro_sessions(
        db,
        user_id,
        all_408_ids=all_408_ids,
        start_utc=start_utc,
        end_utc=end_utc,
    )
    for session in sessions:
        split = split_session_duration_by_study_day(
            session,
            session.pause_intervals,
            day_start_minute,
        )
        focus_sec += focus_duration_for_subject_scope(
            session, {today: split.get(today, 0)}, subject_scope
        )
        supplement_split = split_session_duration_excluding_intervals(
            session,
            session.pause_intervals,
            activity_spans,
            day_start_minute,
        )
        focus_supplement_sec += focus_duration_for_subject_scope(
            session, {today: supplement_split.get(today, 0)}, subject_scope
        )
    return ceil_minutes(focus_sec), ceil_minutes(focus_supplement_sec)
