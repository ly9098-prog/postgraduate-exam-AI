import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.time_utils import (
    current_study_day,
    minute_to_time_text,
    study_day_for_utc,
    study_day_utc_range,
    study_week_utc_range,
    utcnow,
)
from app.models.admin import Subject
from app.models.pomodoro import (
    PomodoroPauseInterval,
    PomodoroSession,
    UserPomodoroSettings,
)
from app.models.user import User
from app.services.pomodoro_attribution import split_session_duration_by_study_day

logger = logging.getLogger(__name__)


def _effective_paused_sec(session, now) -> int:
    """Paused seconds derived from the canonical pause intervals (single source of truth).

    ``total_paused_sec`` is a derived cache kept for the active-timer UI; this
    recomputes the truth from the intervals so the cache can never diverge.
    """
    total = 0
    for i in session.pause_intervals:
        if i.started_at is None:
            continue
        end = i.ended_at if i.ended_at is not None else now
        if end > i.started_at:
            total += int((end - i.started_at).total_seconds())
    return total


def _close_open_pause_interval(session, now) -> PomodoroPauseInterval | None:
    """Close the session's open pause interval at ``now``.

    Invariant (§13): a paused session has exactly one open pause interval.  A paused
    session with ``paused_at`` set but no open interval is a data anomaly — logged
    loudly and never silently repaired at runtime.
    """
    open_interval = next((i for i in session.pause_intervals if i.ended_at is None), None)
    if open_interval is None:
        if session.paused_at is not None:
            logger.warning(
                "pomodoro data anomaly: session %s has paused_at but no open pause interval; "
                "pause segment not recorded as an interval",
                session.id,
            )
        return None
    open_interval.ended_at = now
    return open_interval


def _server_actual_duration(session, now) -> int:
    """Server-authoritative active seconds: wall clock minus canonical pause time."""
    raw = int((now - session.start_time).total_seconds())
    return max(0, raw - _effective_paused_sec(session, now))


async def start_session(
    db: AsyncSession,
    user_id: int,
    subject_id: int,
    chapter_id: str | None,
    preset: str,
    work_duration: int,
    break_duration: int,
    notification_enabled: bool = False,
) -> PomodoroSession:
    # Check for active session first — don't auto-cancel
    active = await get_active_session(db, user_id)
    if active is not None:
        raise ValueError("当前已有进行中的专注，请先结束后再开始")

    user_row = await db.execute(select(User.openid).where(User.id == user_id))
    openid_snapshot = user_row.scalar_one_or_none()

    # Free timer overrides: no countdown, no notification
    if preset == "free":
        work_duration = 0
        break_duration = 0
        notification_enabled = False
    elif work_duration <= 0:
        raise ValueError("非自由计时模式需要设置学习时长")

    start = utcnow()
    expected_end = start + timedelta(minutes=max(0, work_duration)) if work_duration > 0 else None

    # Validate subject_id
    subj = await db.get(Subject, subject_id)
    if subj is None:
        raise ValueError(f"科目不存在: subject_id={subject_id}")
    if not subj.is_active:
        raise ValueError(f"科目不可用: {subj.name}")
    # Check leaf: if subject has active children, reject
    child_count = await db.scalar(
        select(func.count(Subject.id)).where(
            Subject.parent_id == subject_id,
            Subject.is_active.is_(True),
        )
    )
    if child_count and child_count > 0:
        raise ValueError(f"请选择具体子科目，不能选择父级科目: {subj.name}")

    session = PomodoroSession(
        user_id=user_id,
        subject_id=subject_id,
        chapter_id=chapter_id,
        preset=preset,
        work_duration=work_duration,
        break_duration=break_duration,
        start_time=start,
        expected_end_time=expected_end,
        status="running",
        notification_enabled=bool(notification_enabled),
        notification_sent=False,
        openid_snapshot=openid_snapshot,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    # Populate subject_ref for post-commit serialization
    session.subject_ref = subj
    return session


async def complete_session(db: AsyncSession, session_id: int, user_id: int) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession)
        .options(
            joinedload(PomodoroSession.subject_ref),
            selectinload(PomodoroSession.pause_intervals),
        )
        .where(
            PomodoroSession.id == session_id,
            PomodoroSession.user_id == user_id,
            PomodoroSession.status.in_(["running", "paused"]),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    now = utcnow()

    # Close any open pause interval so the whole pause is captured by intervals.
    if session.paused_at is not None:
        _close_open_pause_interval(session, now)
        session.paused_at = None

    session.end_time = now
    # actual_duration is computed entirely server-side from timestamps + intervals
    # (§14); the client never overrides it.
    session.actual_duration = _server_actual_duration(session, now)
    session.total_paused_sec = _effective_paused_sec(session, now)  # derived cache
    session.status = "completed"
    if not session.notification_sent:
        session.notification_sent = True
        session.notification_sent_at = now
        if not session.notification_error:
            session.notification_error = "skipped: user completed before scheduler"
    await db.flush()
    await db.refresh(session)
    return session


async def interrupt_session(db: AsyncSession, session_id: int, user_id: int) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession)
        .options(
            joinedload(PomodoroSession.subject_ref),
            selectinload(PomodoroSession.pause_intervals),
        )
        .where(
            PomodoroSession.id == session_id,
            PomodoroSession.user_id == user_id,
            PomodoroSession.status.in_(["running", "paused"]),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    now = utcnow()

    if session.paused_at is not None:
        _close_open_pause_interval(session, now)
        session.paused_at = None

    session.end_time = now
    session.actual_duration = _server_actual_duration(session, now)
    session.total_paused_sec = _effective_paused_sec(session, now)  # derived cache
    session.status = "interrupted"
    if not session.notification_sent:
        session.notification_sent = True
        session.notification_sent_at = now
        if not session.notification_error:
            session.notification_error = "skipped: user interrupted"
    await db.flush()
    await db.refresh(session)
    return session


async def pause_session(db: AsyncSession, session_id: int, user_id: int) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession)
        .options(
            joinedload(PomodoroSession.subject_ref),
            selectinload(PomodoroSession.pause_intervals),
        )
        .where(
            PomodoroSession.id == session_id,
            PomodoroSession.user_id == user_id,
            PomodoroSession.status.in_(["running", "paused"]),
        )
        # Row lock so two concurrent pause requests cannot both see status="running"
        # and each append an open pause interval (PostgreSQL; no-op on SQLite).
        .with_for_update()
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    # Idempotent: already paused, just return current session
    if session.status == "paused":
        await db.refresh(session)
        return session
    now = utcnow()
    # Record the pause interval so attribution can subtract exactly where the
    # pause fell.  Defensive: never create a second open interval (covers engines
    # without SELECT FOR UPDATE, e.g. SQLite, and double-tap races).
    if not any(i.ended_at is None for i in session.pause_intervals):
        session.pause_intervals.append(
            PomodoroPauseInterval(session_id=session.id, started_at=now, ended_at=None)
        )
    session.paused_at = now
    session.status = "paused"
    await db.flush()
    await db.refresh(session)
    return session


async def resume_session(
    db: AsyncSession,
    session_id: int,
    user_id: int,
) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession)
        .options(
            joinedload(PomodoroSession.subject_ref),
            selectinload(PomodoroSession.pause_intervals),
        )
        .where(
            PomodoroSession.id == session_id,
            PomodoroSession.user_id == user_id,
            PomodoroSession.status.in_(["running", "paused"]),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    now = utcnow()

    if session.status == "paused" and session.paused_at is not None:
        _close_open_pause_interval(session, now)
        session.paused_at = None
        session.status = "running"
        # Recompute the derived cache and the countdown end from canonical data —
        # idempotent, repeated resumes never double-extend the countdown.
        session.total_paused_sec = _effective_paused_sec(session, now)
        if session.expected_end_time is not None:
            session.expected_end_time = (
                session.start_time
                + timedelta(minutes=session.work_duration)
                + timedelta(seconds=session.total_paused_sec)
            )

    await db.flush()
    await db.refresh(session)
    return session


async def get_active_session(db: AsyncSession, user_id: int) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession)
        .options(joinedload(PomodoroSession.subject_ref))
        .where(
            PomodoroSession.user_id == user_id,
            PomodoroSession.status.in_(["running", "paused"]),
        )
        .order_by(PomodoroSession.start_time.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ── Settings ─────────────────────────────────────────────────────────────

async def get_pomodoro_settings(db: AsyncSession, user_id: int) -> dict:
    row = await db.get(UserPomodoroSettings, user_id)
    day_start_minute = row.day_start_minute if row is not None else 0
    return {
        "day_start_minute": day_start_minute,
        "day_start_time": minute_to_time_text(day_start_minute),
        "timezone": "Asia/Shanghai",
    }


async def update_pomodoro_settings(db: AsyncSession, user_id: int, day_start_minute: int) -> dict:
    if day_start_minute < 0 or day_start_minute > 1439:
        raise ValueError("day_start_minute must be in range 0..1439")
    row = await db.get(UserPomodoroSettings, user_id)
    if row is None:
        db.add(UserPomodoroSettings(user_id=user_id, day_start_minute=day_start_minute))
    else:
        row.day_start_minute = day_start_minute
    await db.flush()
    return await get_pomodoro_settings(db, user_id)


# ── Statistics ───────────────────────────────────────────────────────────

async def _load_overlapping_sessions(
    db: AsyncSession,
    user_id: int,
    period_start: datetime,
    period_end: datetime,
) -> list[PomodoroSession]:
    """Load completed sessions overlapping the half-open range [period_start, period_end).

    Eager-loads subject_ref and pause_intervals so attribution needs no extra queries.
    """
    result = await db.execute(
        select(PomodoroSession)
        .options(
            joinedload(PomodoroSession.subject_ref),
            selectinload(PomodoroSession.pause_intervals),
        )
        .where(
            PomodoroSession.user_id == user_id,
            PomodoroSession.status == "completed",
            PomodoroSession.start_time < period_end,
            PomodoroSession.end_time > period_start,
        )
    )
    return list(result.scalars().all())


def _resolve_subject(session) -> tuple[int | None, str, str]:
    """Return (group_key, code, name) for a session's subject.

    Only active subjects render under their real id/name; inactive or orphaned
    (deleted) subjects merge into a single 未分类 group so no duration is lost and
    no duplicate 未分类 slices are produced.
    """
    ref = session.subject_ref
    if session.subject_id is not None and ref is not None and ref.is_active:
        return session.subject_id, ref.code or "", ref.name or ""
    return None, "", "未分类"


async def get_stats(db: AsyncSession, user_id: int) -> dict:
    settings = await get_pomodoro_settings(db, user_id)
    dsm = settings["day_start_minute"]
    today_date = current_study_day(dsm)
    today_start, today_end = study_day_utc_range(today_date, dsm)
    week_start, week_end = study_week_utc_range(dsm)
    week_start_date = study_day_for_utc(week_start, dsm)
    week_end_date = week_start_date + timedelta(days=7)

    period_start = min(today_start, week_start)
    period_end = max(today_end, week_end)
    sessions = await _load_overlapping_sessions(db, user_id, period_start, period_end)

    today_sessions = 0
    today_duration = 0
    week_sessions = 0
    week_duration = 0
    for s in sessions:
        start_day = study_day_for_utc(s.start_time, dsm)
        if start_day == today_date:
            today_sessions += 1
        if week_start_date <= start_day < week_end_date:
            week_sessions += 1
        for day, sec in split_session_duration_by_study_day(s, s.pause_intervals, dsm).items():
            if day == today_date:
                today_duration += sec
            if week_start_date <= day < week_end_date:
                week_duration += sec

    return {
        "today_sessions": today_sessions,
        "today_duration_sec": today_duration,
        "week_sessions": week_sessions,
        "week_duration_sec": week_duration,
        "today_date": today_date.isoformat(),
        "week_start_date": week_start_date.isoformat(),
        "day_start_minute": dsm,
        "day_start_time": settings["day_start_time"],
    }


async def get_trends(db: AsyncSession, user_id: int, days: int = 7) -> list[dict]:
    settings = await get_pomodoro_settings(db, user_id)
    dsm = settings["day_start_minute"]
    today = current_study_day(dsm)
    start_day = today - timedelta(days=days - 1)
    period_start = study_day_utc_range(start_day, dsm)[0]
    period_end = study_day_utc_range(today, dsm)[1]

    sessions = await _load_overlapping_sessions(db, user_id, period_start, period_end)

    agg = {
        today - timedelta(days=days - 1 - i): {"sessions": 0, "duration_sec": 0}
        for i in range(days)
    }
    for s in sessions:
        start_day = study_day_for_utc(s.start_time, dsm)
        if start_day in agg:
            agg[start_day]["sessions"] += 1
        for day, sec in split_session_duration_by_study_day(s, s.pause_intervals, dsm).items():
            if day in agg:
                agg[day]["duration_sec"] += sec

    return [
        {
            "date": d.isoformat(),
            "sessions": agg[d]["sessions"],
            "duration_sec": agg[d]["duration_sec"],
        }
        for d in sorted(agg)
    ]


async def get_subject_breakdown(
    db: AsyncSession,
    user_id: int,
    filter_date: date | None = None,
) -> list[dict]:
    settings = await get_pomodoro_settings(db, user_id)
    dsm = settings["day_start_minute"]
    target_date = filter_date or current_study_day(dsm)
    period_start, period_end = study_day_utc_range(target_date, dsm)
    sessions = await _load_overlapping_sessions(db, user_id, period_start, period_end)

    groups: dict[int | None, dict] = {}
    for s in sessions:
        start_day = study_day_for_utc(s.start_time, dsm)
        day_contrib = split_session_duration_by_study_day(s, s.pause_intervals, dsm).get(target_date, 0)
        if day_contrib <= 0 and start_day != target_date:
            continue
        if day_contrib <= 0:
            # 本日无时长贡献：不出现在科目分布，避免 0% 扇形 / "N次 0分钟"
            continue
        key, code, name = _resolve_subject(s)
        g = groups.setdefault(key, {
            "subject_id": key, "subject_code": code, "subject_name": name,
            "duration_sec": 0, "sessions": 0,
        })
        g["duration_sec"] += day_contrib
        if start_day == target_date:
            g["sessions"] += 1

    result = [
        {
            "subject_id": key,
            "subject_code": g["subject_code"],
            "subject_name": g["subject_name"],
            "sessions": g["sessions"],
            "duration_sec": g["duration_sec"],
        }
        for key, g in groups.items()
    ]
    result.sort(key=lambda r: r["duration_sec"], reverse=True)
    return result


async def get_daily_summary(
    db: AsyncSession,
    user_id: int,
    filter_date: date | None = None,
) -> dict:
    settings = await get_pomodoro_settings(db, user_id)
    dsm = settings["day_start_minute"]
    target_date = filter_date or current_study_day(dsm)
    period_start, period_end = study_day_utc_range(target_date, dsm)
    sessions = await _load_overlapping_sessions(db, user_id, period_start, period_end)

    groups: dict[int | None, dict] = {}
    session_count = 0
    total_duration = 0
    for s in sessions:
        start_day = study_day_for_utc(s.start_time, dsm)
        day_contrib = split_session_duration_by_study_day(s, s.pause_intervals, dsm).get(target_date, 0)
        if day_contrib <= 0 and start_day != target_date:
            continue
        if start_day == target_date:
            session_count += 1
        total_duration += day_contrib
        if day_contrib <= 0:
            # 本日无时长贡献：仍计入总次数/总时长，但不生成 0% 科目切片
            continue
        key, code, name = _resolve_subject(s)
        g = groups.setdefault(key, {
            "subject_id": key, "subject_code": code, "subject_name": name,
            "duration_sec": 0, "sessions": 0,
        })
        g["duration_sec"] += day_contrib
        if start_day == target_date:
            g["sessions"] += 1

    subjects = [
        {
            "subject_id": key,
            "subject_code": g["subject_code"],
            "subject_name": g["subject_name"],
            "sessions": g["sessions"],
            "duration_sec": g["duration_sec"],
        }
        for key, g in groups.items()
    ]
    subjects.sort(key=lambda r: r["duration_sec"], reverse=True)

    return {
        "date": target_date.isoformat(),
        "timezone": "Asia/Shanghai",
        "day_start_minute": dsm,
        "day_start_time": settings["day_start_time"],
        "sessions": session_count,
        "duration_sec": total_duration,
        "subjects": subjects,
    }


async def get_history(
    db: AsyncSession, user_id: int, page: int = 1, page_size: int = 20,
    filter_date: date | None = None,
) -> tuple[list[PomodoroSession], int]:
    where = [
        PomodoroSession.user_id == user_id,
        ~PomodoroSession.status.in_(["running", "paused"]),
    ]
    if filter_date is not None:
        dsm = (await get_pomodoro_settings(db, user_id))["day_start_minute"]
        start_utc, end_utc = study_day_utc_range(filter_date, dsm)
        where.extend([
            PomodoroSession.start_time >= start_utc,
            PomodoroSession.start_time < end_utc,
        ])

    count_result = await db.execute(
        select(func.count(PomodoroSession.id)).where(*where)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(PomodoroSession)
        .options(joinedload(PomodoroSession.subject_ref))
        .where(*where)
        .order_by(PomodoroSession.start_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), total
