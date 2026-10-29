"""Read activity dates in review, practice, pomodoro and exam source order."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class _ActivityWindow:
    start_date: date
    end_date: date
    start_utc: datetime
    end_utc: datetime
    day_start_minute: int


async def _collect_review_dates(
    db, user_id, core_408_ids, window, active_dates, *, ports
):
    reviewed_at_values = (
        await db.scalars(
            ports("select")(ports("ReviewRecord").reviewed_at)
            .join(
                ports("QuestionVersion"),
                ports("QuestionVersion").id
                == ports("ReviewRecord").question_version_id,
            )
            .where(
                ports("ReviewRecord").user_id == user_id,
                ports("QuestionVersion").subject_id.in_(core_408_ids),
                ports("ReviewRecord").reviewed_at >= window.start_utc,
                ports("ReviewRecord").reviewed_at < window.end_utc,
            )
        )
    ).all()
    active_dates.update(
        (
            ports("study_day_for_utc")(value, window.day_start_minute)
            for value in reviewed_at_values
            if value is not None
        )
    )


async def _collect_practice_dates(
    db, user_id, all_408_ids, window, active_dates, *, ports
):
    practice_rows = (
        await db.execute(
            ports("select")(
                ports("PracticeSession").started_at,
                ports("PracticeSession").finished_at,
                ports("PracticeSession").duration_sec,
            ).where(
                ports("PracticeSession").user_id == user_id,
                ports("PracticeSession").subject_id.in_(all_408_ids),
                ports("PracticeSession").status == "completed",
                ports("PracticeSession").started_at < window.end_utc,
                ports("PracticeSession").finished_at > window.start_utc,
            )
        )
    ).all()
    for row in practice_rows:
        split = ports("split_duration_excluding_intervals")(
            row.started_at,
            row.finished_at,
            max(0, int(row.duration_sec or 0)),
            [],
            window.day_start_minute,
        )
        active_dates.update(
            (
                day
                for day, sec in split.items()
                if window.start_date <= day <= window.end_date and sec > 0
            )
        )


async def _load_pomodoro_rows(db, user_id, all_408_ids, window, *, ports):
    return (
        (
            await db.execute(
                ports("select")(ports("PomodoroSession"))
                .options(
                    ports("selectinload")(ports("PomodoroSession").pause_intervals),
                    ports("selectinload")(ports("PomodoroSession").subject_allocations),
                )
                .where(
                    ports("PomodoroSession").user_id == user_id,
                    ports("or_")(
                        ports("PomodoroSession").subject_id.in_(all_408_ids),
                        ports("PomodoroSession").id.in_(
                            ports("select")(
                                ports("PomodoroSubjectAllocation").session_id
                            ).where(
                                ports("PomodoroSubjectAllocation").subject_id.in_(
                                    all_408_ids
                                )
                            )
                        ),
                    ),
                    ports("PomodoroSession").status == "completed",
                    ports("PomodoroSession").end_time.is_not(None),
                    ports("PomodoroSession").start_time < window.end_utc,
                    ports("PomodoroSession").end_time > window.start_utc,
                )
            )
        )
        .scalars()
        .all()
    )


def _collect_pomodoro_dates(pomodoro_rows, window, all_408_ids, active_dates, *, ports):
    for session in pomodoro_rows:
        split = ports("split_session_duration_by_study_day")(
            session, session.pause_intervals, window.day_start_minute
        )
        active_dates.update(
            (
                day
                for day, sec in split.items()
                if window.start_date <= day <= window.end_date
                and ports("_focus_duration_for_subject_scope")(
                    session, {day: sec}, set(all_408_ids)
                )
                > 0
            )
        )


async def _collect_exam_dates(db, user_id, window, active_dates, *, ports):
    exam_rows = (
        await db.execute(
            ports("select")(
                ports("ExamAttempt").started_at,
                ports("ExamAttempt").submitted_at,
                ports("ExamAttempt").duration_sec,
            ).where(
                ports("ExamAttempt").user_id == user_id,
                ports("ExamAttempt").submitted_at.is_not(None),
                ports("ExamAttempt").status.in_(("submitted", "expired")),
                ports("ExamAttempt").started_at < window.end_utc,
                ports("ExamAttempt").submitted_at > window.start_utc,
            )
        )
    ).all()
    for row in exam_rows:
        split = ports("split_duration_excluding_intervals")(
            row.started_at,
            row.submitted_at,
            max(0, int(row.duration_sec or 0)),
            [],
            window.day_start_minute,
        )
        active_dates.update(
            (
                day
                for day, sec in split.items()
                if window.start_date <= day <= window.end_date and sec > 0
            )
        )


async def _load_activity_dates(
    db: Any,
    user_id: int,
    *,
    start_date: Any,
    end_date: Any,
    all_408_ids: list[int],
    core_408_ids: list[int],
    day_start_minute: int,
    ports,
):
    if end_date < start_date:
        return set()
    window = _ActivityWindow(
        start_date,
        end_date,
        ports("study_day_utc_range")(start_date, day_start_minute)[0],
        ports("study_day_utc_range")(end_date, day_start_minute)[1],
        day_start_minute,
    )
    active_dates: set[date] = set()
    if core_408_ids:
        await _collect_review_dates(
            db, user_id, core_408_ids, window, active_dates, ports=ports
        )
    if all_408_ids:
        await _collect_practice_dates(
            db, user_id, all_408_ids, window, active_dates, ports=ports
        )
        pomodoro_rows = await _load_pomodoro_rows(
            db, user_id, all_408_ids, window, ports=ports
        )
        _collect_pomodoro_dates(
            pomodoro_rows, window, all_408_ids, active_dates, ports=ports
        )
    await _collect_exam_dates(db, user_id, window, active_dates, ports=ports)
    return active_dates
