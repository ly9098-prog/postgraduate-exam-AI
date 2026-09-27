import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, literal, null, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.subject_scope import (
    is_study_subject_enabled,
    select_study_subject_records,
)
from app.core.time_utils import (
    current_study_day,
    minute_to_time_text,
    normalize_to_naive_utc,
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
from app.models.practice_session import PracticeSession
from app.models.review_scheduler import ReviewSession
from app.models.user import User
from app.services.pomodoro_attribution import (
    active_intervals_for_session,
    split_duration_excluding_intervals,
    split_session_duration_by_study_day,
)

logger = logging.getLogger(__name__)

FREE_TIMER_MAX_DURATION_SEC = 5 * 60 * 60
COUNTDOWN_COMPLETE_EARLY_TOLERANCE_SEC = 2
CLIENT_ACTION_FUTURE_TOLERANCE_SEC = 5
CLIENT_ACTION_PAST_TOLERANCE_SEC = 5

# Statistics represent persisted learning records only after a focus session has
# ended. Running/paused sessions remain visible through the active-session API and
# must not change historical or daily aggregates while the timer is still open.
POMODORO_STATS_TERMINAL_STATUSES = ("completed", "interrupted")
POMODORO_STATS_STATUSES = POMODORO_STATS_TERMINAL_STATUSES


class PomodoroStaleActionError(ValueError):
    """Explicit client action predates the latest canonical session event."""


class PomodoroNotReadyError(ValueError):
    """Countdown completion arrived before the configured active duration elapsed."""


class PomodoroClockSkewError(ValueError):
    """Explicit client event time is implausibly ahead of current server time."""


class PomodoroStartIdempotencyConflictError(ValueError):
    """A client_start_id was reused with a different start payload."""


def _effective_paused_sec(session, now) -> int:
    """Paused seconds derived from the canonical pause intervals (single source of truth).

    ``total_paused_sec`` is a derived cache kept for the active-timer UI; this
    recomputes the truth from the intervals so the cache can never diverge.

    Overlapping intervals are merged before summing, and the float seconds are
    accumulated once then truncated, so multi-pause sessions agree with
    attribution's merged semantics instead of overcounting by up to N-1 seconds.
    """
    spans = []
    for i in session.pause_intervals:
        if i.started_at is None or i.started_at >= now:
            continue
        end = i.ended_at if i.ended_at is not None else now
        if end > now:
            end = now
        if end > i.started_at:
            spans.append((i.started_at, end))
    if not spans and getattr(session, "pause_intervals", None):
        return 0
    if not spans:
        # Pre-V2 sessions carry only the derived cache (intervals are created by
        # migrate_pomodoro_sessions_v2 --apply). Preserve it instead of silently
        # zeroing the pause, which would inflate actual_duration until backfill.
        legacy = getattr(session, "total_paused_sec", 0) or 0
        if legacy > 0:
            logger.warning(
                "pomodoro legacy session %s: total_paused_sec=%s but no pause intervals; "
                "run migrate_pomodoro_sessions_v2 --apply to backfill",
                getattr(session, "id", None),
                legacy,
            )
        return int(legacy)
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s < merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return int(sum((e - s).total_seconds() for s, e in merged))


def _close_open_pause_interval(session, now) -> PomodoroPauseInterval | None:
    """Close the session's open pause interval at ``now``.

    Invariant (§13): a paused session has exactly one open pause interval.  A paused
    session with ``paused_at`` set but no open interval is a data anomaly — logged
    loudly and never silently repaired at runtime.
    """
    open_interval = next(
        (i for i in session.pause_intervals if i.ended_at is None), None
    )
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


def _latest_session_event_time(session) -> datetime:
    """Latest canonical timestamp already recorded on the session timeline."""
    latest = session.start_time
    for interval in getattr(session, "pause_intervals", ()) or ():
        if interval.started_at is not None and interval.started_at > latest:
            latest = interval.started_at
        if interval.ended_at is not None and interval.ended_at > latest:
            latest = interval.ended_at
    return latest


def _closing_action_floor(session) -> datetime:
    """Timeline floor for an action that may close an open pause interval."""
    floor = _latest_session_event_time(session)
    open_interval = next(
        (
            i
            for i in getattr(session, "pause_intervals", ()) or ()
            if i.ended_at is None
        ),
        None,
    )
    if open_interval is not None:
        floor = max(floor, open_interval.started_at + timedelta(microseconds=1))
    return floor


def _resolve_client_action_time(
    session,
    client_action_at: datetime | None,
    server_now: datetime,
    *,
    floor: datetime | None = None,
    reject_stale_before: datetime | None = None,
) -> datetime:
    """Resolve a delayed client action without allowing old events to reorder state.

    Missing timestamps (legacy clients) still use server time. When a modern client
    explicitly supplies ``client_action_at``, however, a timestamp older than the
    latest canonical event is rejected rather than silently pushed forward. That
    prevents a late cross-device pause/resume from reversing the user's newer state.
    """
    explicit_client_time = client_action_at is not None
    if not explicit_client_time:
        candidate = server_now
    else:
        try:
            candidate = normalize_to_naive_utc(client_action_at)
        except (TypeError, ValueError):
            candidate = server_now
            explicit_client_time = False

    if explicit_client_time and candidate > server_now + timedelta(
        seconds=CLIENT_ACTION_FUTURE_TOLERANCE_SEC
    ):
        raise PomodoroClockSkewError("POMODORO_CLOCK_SKEW")

    if explicit_client_time and candidate < session.start_time - timedelta(
        seconds=CLIENT_ACTION_PAST_TOLERANCE_SEC
    ):
        raise PomodoroClockSkewError("POMODORO_CLOCK_SKEW")

    if (
        explicit_client_time
        and reject_stale_before is not None
        and candidate < reject_stale_before
    ):
        raise PomodoroStaleActionError("POMODORO_STALE_ACTION")

    lower = session.start_time
    if floor is not None and floor > lower:
        lower = floor
    if candidate < lower:
        candidate = lower
    if candidate > server_now:
        candidate = server_now
    if candidate < lower:
        candidate = lower
    return candidate


async def _get_session_by_client_start_id(
    db: AsyncSession, user_id: int, client_start_id: str | None
) -> PomodoroSession | None:
    if not client_start_id:
        return None
    result = await db.execute(
        select(PomodoroSession)
        .options(joinedload(PomodoroSession.subject_ref))
        .where(
            PomodoroSession.user_id == user_id,
            PomodoroSession.client_start_id == client_start_id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


def _start_payload_matches(
    session: PomodoroSession,
    *,
    subject_id: int,
    chapter_id: str | None,
    preset: str,
    work_duration: int,
    break_duration: int,
    notification_enabled: bool,
) -> bool:
    expected_work = 0 if preset == "free" else work_duration
    expected_break = 0 if preset == "free" else break_duration
    expected_notification = False if preset == "free" else bool(notification_enabled)
    return (
        session.subject_id == subject_id
        and session.chapter_id == chapter_id
        and session.preset == preset
        and int(session.work_duration or 0) == int(expected_work or 0)
        and int(session.break_duration or 0) == int(expected_break or 0)
        and bool(session.notification_enabled) == expected_notification
    )


async def start_session(
    db: AsyncSession,
    user_id: int,
    subject_id: int,
    chapter_id: str | None,
    preset: str,
    work_duration: int,
    break_duration: int,
    notification_enabled: bool = False,
    client_start_id: str | None = None,
) -> PomodoroSession:
    # True idempotency must be checked before the active-session guard. If the
    # original /start committed but its response was lost, retrying the same key
    # returns that exact row instead of colliding with the row it just created.
    existing = await _get_session_by_client_start_id(db, user_id, client_start_id)
    if existing is not None:
        if not _start_payload_matches(
            existing,
            subject_id=subject_id,
            chapter_id=chapter_id,
            preset=preset,
            work_duration=work_duration,
            break_duration=break_duration,
            notification_enabled=notification_enabled,
        ):
            raise PomodoroStartIdempotencyConflictError(
                "POMODORO_START_IDEMPOTENCY_CONFLICT"
            )
        return existing

    # Check for active session first — don't auto-cancel another device's timer.
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
    expected_end = (
        start + timedelta(minutes=max(0, work_duration)) if work_duration > 0 else None
    )

    # Validate subject_id
    subj = await db.get(Subject, subject_id)
    if subj is None:
        raise ValueError(f"科目不存在: subject_id={subject_id}")
    if not is_study_subject_enabled(subj):
        raise ValueError(f"科目不可用: {subj.name}")
    all_subjects = list((await db.execute(select(Subject))).scalars().all())
    enabled_ids = {item.id for item in select_study_subject_records(all_subjects)}
    child_count = sum(
        1
        for item in all_subjects
        if item.parent_id == subject_id and item.id in enabled_ids
    )
    if child_count and child_count > 0:
        raise ValueError(f"请选择具体子科目，不能选择父级科目: {subj.name}")

    session = PomodoroSession(
        user_id=user_id,
        subject_id=subject_id,
        chapter_id=chapter_id,
        client_start_id=client_start_id,
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
    try:
        async with db.begin_nested():
            db.add(session)
            await db.flush()
    except IntegrityError as exc:
        # First check the idempotency key: concurrent retries with the same key can
        # lose either the client-key index race or the one-active-session race.
        existing = await _get_session_by_client_start_id(db, user_id, client_start_id)
        if existing is not None:
            if not _start_payload_matches(
                existing,
                subject_id=subject_id,
                chapter_id=chapter_id,
                preset=preset,
                work_duration=work_duration,
                break_duration=break_duration,
                notification_enabled=notification_enabled,
            ):
                raise PomodoroStartIdempotencyConflictError(
                    "POMODORO_START_IDEMPOTENCY_CONFLICT"
                ) from exc
            return existing

        conflict = await get_active_session(db, user_id)
        if conflict is not None:
            logger.info(
                "pomodoro start_session: active-session uniqueness race for user %s",
                user_id,
            )
            raise ValueError("当前已有进行中的专注，请先结束后再开始") from exc
        raise

    await db.refresh(session)
    session.subject_ref = subj
    return session


def _countdown_completion_ready(session, action_time: datetime) -> bool:
    work_cap_sec = max(0, int(session.work_duration or 0) * 60)
    if session.preset in ("free", "debug") or work_cap_sec <= 0:
        return True
    active_sec_at_action = _server_actual_duration(session, action_time)
    return active_sec_at_action + COUNTDOWN_COMPLETE_EARLY_TOLERANCE_SEC >= work_cap_sec


def _truncate_pause_timeline_at(session, cutoff: datetime) -> None:
    """Discard pause/resume events that happened after an earlier terminal action."""
    for interval in list(getattr(session, "pause_intervals", ()) or ()):
        if interval.started_at is None:
            continue
        if interval.started_at >= cutoff:
            session.pause_intervals.remove(interval)
            continue
        if interval.ended_at is None or interval.ended_at > cutoff:
            if cutoff > interval.started_at:
                interval.ended_at = cutoff
            else:
                session.pause_intervals.remove(interval)
    session.paused_at = None


def _apply_terminal_state(
    session: PomodoroSession,
    *,
    requested_status: str,
    action_time: datetime,
    server_now: datetime,
) -> None:
    # An earlier terminal action invalidates any pause/resume events after it.
    _truncate_pause_timeline_at(session, action_time)
    paused_sec = _effective_paused_sec(session, action_time)
    actual_duration = _server_actual_duration(session, action_time)
    effective_end = action_time

    if session.preset == "free":
        actual_duration = min(actual_duration, FREE_TIMER_MAX_DURATION_SEC)
        if actual_duration >= FREE_TIMER_MAX_DURATION_SEC:
            effective_end = min(
                action_time,
                session.start_time
                + timedelta(seconds=paused_sec + FREE_TIMER_MAX_DURATION_SEC),
            )
    else:
        work_cap_sec = max(0, int(session.work_duration or 0) * 60)
        if work_cap_sec > 0:
            actual_duration = min(actual_duration, work_cap_sec)
            if actual_duration >= work_cap_sec:
                effective_end = min(
                    action_time,
                    session.start_time + timedelta(seconds=paused_sec + work_cap_sec),
                )

    session.end_time = effective_end
    session.actual_duration = actual_duration
    session.total_paused_sec = paused_sec
    session.status = requested_status
    if not session.notification_sent:
        session.notification_sent = True
        session.notification_sent_at = server_now
        if not session.notification_error:
            session.notification_error = (
                "skipped: user completed before scheduler"
                if requested_status == "completed"
                else "skipped: user interrupted"
            )


def _resolve_terminal_action_time(
    session: PomodoroSession,
    client_action_at: datetime | None,
    server_now: datetime,
) -> datetime:
    # Terminal actions are different from pause/resume: an older terminal event is
    # allowed to supersede later non-terminal events because the session should
    # have stopped at the earliest valid terminal timestamp.
    return _resolve_client_action_time(
        session,
        client_action_at,
        server_now,
        floor=session.start_time,
        reject_stale_before=None,
    )


async def complete_session(
    db: AsyncSession,
    session_id: int,
    user_id: int,
    client_action_at: datetime | None = None,
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
            PomodoroSession.status.in_(
                ["running", "paused", "completed", "interrupted"]
            ),
        )
        .with_for_update(of=PomodoroSession)
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    now = utcnow()
    # Legacy retries without an explicit event time are purely idempotent once a
    # terminal row exists. Modern clients can provide an earlier timestamp, in
    # which case the earliest valid terminal event wins.
    if session.status in ("completed", "interrupted") and client_action_at is None:
        return session

    try:
        action_time = _resolve_terminal_action_time(session, client_action_at, now)
    except PomodoroClockSkewError:
        if session.status in ("completed", "interrupted"):
            return session
        raise
    if session.end_time is not None and session.status in ("completed", "interrupted"):
        if action_time >= session.end_time:
            return session
        if not _countdown_completion_ready(session, action_time):
            return session
    elif not _countdown_completion_ready(session, action_time):
        raise PomodoroNotReadyError("POMODORO_NOT_READY")

    _apply_terminal_state(
        session,
        requested_status="completed",
        action_time=action_time,
        server_now=now,
    )
    await db.flush()
    await db.refresh(session)
    return session


async def interrupt_session(
    db: AsyncSession,
    session_id: int,
    user_id: int,
    client_action_at: datetime | None = None,
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
            PomodoroSession.status.in_(
                ["running", "paused", "interrupted", "completed"]
            ),
        )
        .with_for_update(of=PomodoroSession)
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    now = utcnow()
    if session.status in ("interrupted", "completed") and client_action_at is None:
        return session

    try:
        action_time = _resolve_terminal_action_time(session, client_action_at, now)
    except PomodoroClockSkewError:
        if session.status in ("interrupted", "completed"):
            return session
        raise
    if session.end_time is not None and session.status in ("interrupted", "completed"):
        if action_time >= session.end_time:
            return session

    _apply_terminal_state(
        session,
        requested_status="interrupted",
        action_time=action_time,
        server_now=now,
    )
    await db.flush()
    await db.refresh(session)
    return session


async def pause_session(
    db: AsyncSession,
    session_id: int,
    user_id: int,
    client_action_at: datetime | None = None,
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
        .with_for_update(of=PomodoroSession)
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    now = utcnow()
    if session.status == "paused":
        # State-idempotent is not timeline-idempotent. If an earlier pause from
        # another device arrives after a later pause already committed, move the
        # open interval back so those seconds are not falsely counted as focus.
        open_interval = next(
            (i for i in session.pause_intervals if i.ended_at is None), None
        )
        if client_action_at is None or open_interval is None:
            await db.refresh(session)
            return session

        prior_latest = session.start_time
        for interval in session.pause_intervals:
            if interval is open_interval:
                continue
            if interval.started_at is not None:
                prior_latest = max(prior_latest, interval.started_at)
            if interval.ended_at is not None:
                prior_latest = max(prior_latest, interval.ended_at)
        action_time = _resolve_client_action_time(
            session,
            client_action_at,
            now,
            floor=prior_latest,
            reject_stale_before=prior_latest,
        )
        if action_time < open_interval.started_at:
            open_interval.started_at = action_time
            session.paused_at = action_time
            await db.flush()
            await db.refresh(session)
        return session

    latest_event = _latest_session_event_time(session)
    action_time = _resolve_client_action_time(
        session,
        client_action_at,
        now,
        floor=latest_event,
        reject_stale_before=latest_event,
    )
    if not any(i.ended_at is None for i in session.pause_intervals):
        session.pause_intervals.append(
            PomodoroPauseInterval(
                session_id=session.id, started_at=action_time, ended_at=None
            )
        )
    session.paused_at = action_time
    session.status = "paused"
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        logger.warning(
            "pomodoro pause_session: concurrent open pause interval for session %s; treating as idempotent",
            session.id,
        )
        session.pause_intervals[:] = [
            i for i in session.pause_intervals if i.id is not None
        ]
        session.paused_at = None
        session.status = "running"
        await db.refresh(session)
    return session


async def resume_session(
    db: AsyncSession,
    session_id: int,
    user_id: int,
    client_action_at: datetime | None = None,
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
        .with_for_update(of=PomodoroSession)
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    now = utcnow()
    open_interval = next(
        (i for i in session.pause_intervals if i.ended_at is None), None
    )

    if session.status == "running" and open_interval is None:
        # Symmetric timeline idempotency for a delayed resume: when the most recent
        # canonical event is the end of a pause interval, an earlier duplicate
        # resume may shorten that pause without changing the current running state.
        closed = [i for i in session.pause_intervals if i.ended_at is not None]
        latest_closed = max(closed, key=lambda i: i.ended_at) if closed else None
        latest_event = _latest_session_event_time(session)
        if (
            client_action_at is not None
            and latest_closed is not None
            and latest_closed.ended_at == latest_event
        ):
            prior_latest = session.start_time
            for interval in session.pause_intervals:
                if interval.started_at is not None:
                    prior_latest = max(prior_latest, interval.started_at)
                if interval is not latest_closed and interval.ended_at is not None:
                    prior_latest = max(prior_latest, interval.ended_at)
            floor = max(
                prior_latest, latest_closed.started_at + timedelta(microseconds=1)
            )
            action_time = _resolve_client_action_time(
                session,
                client_action_at,
                now,
                floor=floor,
                reject_stale_before=prior_latest,
            )
            if action_time < latest_closed.ended_at:
                latest_closed.ended_at = action_time
        elif client_action_at is not None:
            # Validate obvious future skew, but a duplicate resume with no pause
            # history has no timeline effect and can remain idempotent.
            _resolve_client_action_time(
                session, client_action_at, now, floor=session.start_time
            )

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

    floor = _latest_session_event_time(session)
    if open_interval is not None:
        floor = max(floor, open_interval.started_at + timedelta(microseconds=1))
    action_time = _resolve_client_action_time(
        session,
        client_action_at,
        now,
        floor=floor,
        reject_stale_before=_latest_session_event_time(session),
    )

    if open_interval is not None:
        _close_open_pause_interval(session, action_time)

    if session.status == "paused":
        session.paused_at = None
        session.status = "running"

    session.total_paused_sec = _effective_paused_sec(session, action_time)
    if session.status == "running" and session.expected_end_time is not None:
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


async def update_pomodoro_settings(
    db: AsyncSession, user_id: int, day_start_minute: int
) -> dict:
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


class _LiteSession:
    """Duck-typed session row for attribution; keeps ``pomodoro_attribution`` untouched.

    Exposes only the fields the stats aggregators touch — ``start_time`` /
    ``end_time`` / ``actual_duration`` / ``pause_intervals`` (list of
    ``SimpleNamespace(started_at, ended_at)``) — plus ``subject_id`` /
    ``subject_ref`` when the caller needs subject grouping.  No full ORM entity
    is materialised, so stats/trends never drag in the whole session row.
    """

    __slots__ = (
        "start_time",
        "end_time",
        "actual_duration",
        "status",
        "subject_id",
        "subject_ref",
        "pause_intervals",
    )

    def __init__(
        self,
        start_time: datetime,
        end_time: datetime | None,
        actual_duration: int | None,
        status: str = "completed",
        subject_id: int | None = None,
        subject_ref=None,
        pause_intervals: list | None = None,
    ):
        self.start_time = start_time
        self.end_time = end_time
        self.actual_duration = actual_duration
        self.status = status
        self.subject_id = subject_id
        self.subject_ref = subject_ref
        self.pause_intervals = pause_intervals or []


def _chunks(seq, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


async def _load_overlapping_sessions(
    db: AsyncSession,
    user_id: int,
    period_start: datetime,
    period_end: datetime,
    *,
    with_subject: bool = False,
) -> list[_LiteSession]:
    """Load terminal focus sessions overlapping [period_start, period_end).

    Running/paused sessions are intentionally excluded. They remain available from
    the active-session endpoint and enter statistics only after a terminal action
    persists their final duration.

    Scenario-aware payload: ``with_subject=False`` (stats/trends) fetches only the
    attribution columns via one query plus one batched pause query (chunked IN, never
    an N+1); ``with_subject=True`` (daily-summary) additionally joins the subject.
    The window is always bounded (single user, overlapping a requested range) — never
    the user's full history.
    """
    overlap = (
        PomodoroSession.user_id == user_id,
        PomodoroSession.status.in_(POMODORO_STATS_STATUSES),
        PomodoroSession.start_time < period_end,
        PomodoroSession.end_time > period_start,
    )
    if with_subject:
        result = await db.execute(
            select(PomodoroSession)
            .options(
                joinedload(PomodoroSession.subject_ref),
                selectinload(PomodoroSession.pause_intervals),
            )
            .where(*overlap)
        )
        out: list[_LiteSession] = []
        for s in result.scalars().all():
            ref = s.subject_ref
            pause_intervals = [
                SimpleNamespace(started_at=i.started_at, ended_at=i.ended_at)
                for i in s.pause_intervals
            ]
            out.append(
                _LiteSession(
                    start_time=s.start_time,
                    end_time=s.end_time,
                    actual_duration=s.actual_duration,
                    status=s.status,
                    subject_id=s.subject_id,
                    subject_ref=(
                        SimpleNamespace(
                            code=ref.code or "",
                            name=ref.name or "",
                            is_active=ref.is_active,
                        )
                        if ref is not None
                        else None
                    ),
                    pause_intervals=pause_intervals,
                )
            )
        return out

    result = await db.execute(
        select(
            PomodoroSession.id,
            PomodoroSession.start_time,
            PomodoroSession.end_time,
            PomodoroSession.actual_duration,
            PomodoroSession.status,
        ).where(*overlap)
    )
    rows = result.all()
    if not rows:
        return []
    pauses: dict[int, list] = {}
    for chunk in _chunks([r.id for r in rows], 500):
        presult = await db.execute(
            select(
                PomodoroPauseInterval.session_id,
                PomodoroPauseInterval.started_at,
                PomodoroPauseInterval.ended_at,
            ).where(PomodoroPauseInterval.session_id.in_(chunk))
        )
        for sid, started_at, ended_at in presult.all():
            pauses.setdefault(sid, []).append(
                SimpleNamespace(started_at=started_at, ended_at=ended_at)
            )
    return [
        _LiteSession(
            start_time=r.start_time,
            end_time=r.end_time,
            actual_duration=r.actual_duration,
            status=r.status,
            pause_intervals=pauses.get(r.id, []),
        )
        for r in rows
    ]


async def _load_overlapping_practice_sessions(
    db: AsyncSession,
    user_id: int,
    period_start: datetime,
    period_end: datetime,
    *,
    with_subject: bool = False,
) -> list[_LiteSession]:
    """Load completed practice + today-review sessions overlapping the half-open range.

    Practice sessions never pause, so ``pause_intervals`` is empty; the row's
    wall clock ``[started_at, finished_at)`` is the raw learning window and
    ``duration_sec`` is the authoritative learning time.  ``duration_sec`` may
    be less than the wall span (foreground-only client timing subtracts
    background time), so attribution must scale exclusion proportionally
    (:func:`split_duration_excluding_intervals`), never by flat wall overlap.

    ReviewSession (今日复习) shares the same column contract and counts toward
    刷题时长 exactly like PracticeSession; both tables are read in one UNION ALL
    statement so the snapshot query budget stays fixed.
    """

    def _cols(model):
        # Select only attribution columns. PracticeSession carries a potentially
        # large submission_response JSON used for idempotent result replay; loading
        # full ORM rows here would deserialize that payload for every stats query
        # even though attribution never reads it.
        return select(
            model.started_at.label("started_at"),
            model.finished_at.label("finished_at"),
            model.duration_sec.label("duration_sec"),
            model.subject_id.label("subject_id"),
        ).where(
            model.user_id == user_id,
            model.status == "completed",
            model.started_at < period_end,
            model.finished_at > period_start,
        )

    merged = _cols(PracticeSession).union_all(_cols(ReviewSession)).subquery()
    if not with_subject:
        result = await db.execute(
            select(merged.c.started_at, merged.c.finished_at, merged.c.duration_sec)
        )
        return [
            _LiteSession(
                start_time=r.started_at,
                end_time=r.finished_at,
                actual_duration=r.duration_sec,
                pause_intervals=[],
            )
            for r in result.all()
        ]

    result = await db.execute(
        select(
            merged.c.started_at,
            merged.c.finished_at,
            merged.c.duration_sec,
            merged.c.subject_id,
            Subject.code,
            Subject.name,
            Subject.is_active,
        ).outerjoin(Subject, Subject.id == merged.c.subject_id)
    )
    out: list[_LiteSession] = []
    for row in result.all():
        has_subject = (
            row.code is not None or row.name is not None or row.is_active is not None
        )
        out.append(
            _LiteSession(
                start_time=row.started_at,
                end_time=row.finished_at,
                actual_duration=row.duration_sec,
                subject_id=row.subject_id,
                subject_ref=(
                    SimpleNamespace(
                        code=row.code or "",
                        name=row.name or "",
                        is_active=bool(row.is_active),
                    )
                    if has_subject
                    else None
                ),
                pause_intervals=[],
            )
        )
    return out


def _resolve_subject(session) -> tuple[int | None, str, str]:
    """Return (group_key, code, name) for a session's subject.

    Only active subjects render under their real id/name; inactive or orphaned
    (deleted) subjects merge into a single 未分类 group so no duration is lost and
    no duplicate 未分类 slices are produced.
    """
    ref = session.subject_ref
    if (
        session.subject_id is not None
        and ref is not None
        and is_study_subject_enabled(ref)
    ):
        return session.subject_id, ref.code or "", ref.name or ""
    return None, "", "未分类"


async def build_pomodoro_statistics_snapshot(
    db: AsyncSession,
    user_id: int,
    *,
    target_date: date | None = None,
    trends_days: int = 7,
    need_stats: bool = False,
    need_trends: bool = False,
    need_daily_summary: bool = False,
    range_start: date | None = None,
    range_end: date | None = None,
    need_range_summary: bool = False,
    range_include_subjects: bool = True,
) -> dict:
    """One bounded window load + one attribution pass → the requested stats dims.

    All pomodoro statistics endpoints share this single computation.  Sessions in
    the union of the requested windows are loaded once, attributed once per session,
    and each session's per-study-day split feeds stats / trends / daily-summary
    together — the statistics page never pays N overlapping window loads + N
    attribution runs.  ``pomodoro_attribution`` stays the single source of truth;
    SQL only fetches the bounded window.
    """
    settings = await get_pomodoro_settings(db, user_id)
    dsm = settings["day_start_minute"]
    today = current_study_day(dsm)
    target = target_date or today

    ranges: list[tuple[datetime, datetime]] = []
    if need_stats:
        today_start, today_end = study_day_utc_range(today, dsm)
        week_start, week_end = study_week_utc_range(dsm)
        ranges.append((min(today_start, week_start), max(today_end, week_end)))
    if need_trends:
        trend_start, _ = study_day_utc_range(
            today - timedelta(days=trends_days - 1), dsm
        )
        _, trend_end = study_day_utc_range(today, dsm)
        ranges.append((trend_start, trend_end))
    if need_daily_summary:
        ranges.append(study_day_utc_range(target, dsm))
    if need_range_summary:
        if range_start is None or range_end is None:
            raise ValueError("range_start and range_end are required for range summary")
        if range_end < range_start:
            raise ValueError("range_end must be on or after range_start")
        range_period_start, _ = study_day_utc_range(range_start, dsm)
        _, range_period_end = study_day_utc_range(range_end, dsm)
        ranges.append((range_period_start, range_period_end))

    if not ranges:
        return {}
    period_start = min(r[0] for r in ranges)
    period_end = max(r[1] for r in ranges)
    pomodoro_sessions = await _load_overlapping_sessions(
        db,
        user_id,
        period_start,
        period_end,
        with_subject=(
            need_daily_summary or (need_range_summary and range_include_subjects)
        ),
    )
    # 今日复习（ReviewSession）与刷题会话同口径并入：仅补充时长，不计番茄次数。
    practice_sessions = await _load_overlapping_practice_sessions(
        db,
        user_id,
        period_start,
        period_end,
        with_subject=(
            need_daily_summary or (need_range_summary and range_include_subjects)
        ),
    )

    week_start_date = study_day_for_utc(study_week_utc_range(dsm)[0], dsm)
    week_end_date = week_start_date + timedelta(days=7)

    if need_stats:
        today_sessions = 0
        today_duration = 0
        week_sessions = 0
        week_duration = 0
    if need_trends:
        trend_agg = {
            today - timedelta(days=trends_days - 1 - i): {
                "sessions": 0,
                "duration_sec": 0,
            }
            for i in range(trends_days)
        }
    if need_daily_summary:
        target_groups: dict[int | None, dict] = {}
        target_sessions = 0
        target_duration = 0
    if need_range_summary:
        range_groups: dict[int | None, dict] = {}
        range_sessions = 0
        range_duration = 0
        range_active_day_set: set[date] = set()

    # 已被计时的"占用"墙钟区间（用于刷题去重）：
    #  - 所有 Pomodoro 的 active（非暂停）区间
    # Practice 仅补充没有被这些区间覆盖的部分，避免学习总时长 double count。
    # 刷题会话业务上互斥（同一时间只能进行一组刷题），因此不把已处理的刷题
    # 窗口回填进 counted_spans —— 若两刷题会话异常重叠，各自按原时长计入即可，
    # 不做顺序依赖的去重（顺序依赖会产生与遍历次序相关的欠计）。
    counted_spans: list[tuple[datetime, datetime]] = []

    # ── PomodoroSession：时长 + 次数（sessions 系番茄专注次数，不并入刷题）──
    for s in pomodoro_sessions:
        counted_spans.extend(active_intervals_for_session(s))
        start_day = study_day_for_utc(s.start_time, dsm)
        split = split_session_duration_by_study_day(s, s.pause_intervals, dsm)
        is_terminal = s.status in POMODORO_STATS_TERMINAL_STATUSES
        if need_stats:
            if is_terminal and start_day == today:
                today_sessions += 1
            if is_terminal and week_start_date <= start_day < week_end_date:
                week_sessions += 1
            for day, sec in split.items():
                if day == today:
                    today_duration += sec
                if week_start_date <= day < week_end_date:
                    week_duration += sec
        if need_range_summary:
            if is_terminal and range_start <= start_day <= range_end:
                range_sessions += 1
            range_contrib = 0
            for day, sec in split.items():
                if range_start <= day <= range_end:
                    range_contrib += sec
                    range_duration += sec
                    if sec > 0:
                        range_active_day_set.add(day)
            if range_include_subjects and range_contrib > 0:
                key, code, name = _resolve_subject(s)
                g = range_groups.setdefault(
                    key,
                    {
                        "subject_id": key,
                        "subject_code": code,
                        "subject_name": name,
                        "duration_sec": 0,
                        "sessions": 0,
                    },
                )
                g["duration_sec"] += range_contrib
                if is_terminal and range_start <= start_day <= range_end:
                    g["sessions"] += 1
        if need_trends:
            if is_terminal and start_day in trend_agg:
                trend_agg[start_day]["sessions"] += 1
            for day, sec in split.items():
                if day in trend_agg:
                    trend_agg[day]["duration_sec"] += sec
        if need_daily_summary:
            day_contrib = split.get(target, 0)
            if day_contrib <= 0 and start_day != target:
                continue
            if is_terminal and start_day == target:
                target_sessions += 1
            target_duration += day_contrib
            if day_contrib <= 0:
                # 本日无时长贡献：仍计入总次数/总时长，但不生成 0% 科目切片
                continue
            key, code, name = _resolve_subject(s)
            g = target_groups.setdefault(
                key,
                {
                    "subject_id": key,
                    "subject_code": code,
                    "subject_name": name,
                    "duration_sec": 0,
                    "sessions": 0,
                },
            )
            g["duration_sec"] += day_contrib
            if is_terminal and start_day == target:
                g["sessions"] += 1

    # ── PracticeSession：仅补充时长（与 Pomodoro 重叠部分被排除）──
    # 顶层 sessions（stats/trends/daily_summary.sessions）保持番茄次数；
    # 科目级 subjects[].sessions 定义成"当天开始的该科目学习记录数"，含刷题，
    # 供前端跨统计日渗透判断使用（普通当天刷题不会被误判为渗透）。
    for s in practice_sessions:
        start_day = study_day_for_utc(s.start_time, dsm)
        split = split_duration_excluding_intervals(
            s.start_time,
            s.end_time,
            s.actual_duration,
            counted_spans,
            dsm,
        )
        if need_stats:
            for day, sec in split.items():
                if day == today:
                    today_duration += sec
                if week_start_date <= day < week_end_date:
                    week_duration += sec
        if need_range_summary:
            range_contrib = 0
            for day, sec in split.items():
                if range_start <= day <= range_end:
                    range_contrib += sec
                    range_duration += sec
                    if sec > 0:
                        range_active_day_set.add(day)
            if range_include_subjects and range_contrib > 0:
                key, code, name = _resolve_subject(s)
                g = range_groups.setdefault(
                    key,
                    {
                        "subject_id": key,
                        "subject_code": code,
                        "subject_name": name,
                        "duration_sec": 0,
                        "sessions": 0,
                    },
                )
                g["duration_sec"] += range_contrib
                if range_start <= start_day <= range_end:
                    g["sessions"] += 1
        if need_trends:
            for day, sec in split.items():
                if day in trend_agg:
                    trend_agg[day]["duration_sec"] += sec
        if need_daily_summary:
            day_contrib = split.get(target, 0)
            if day_contrib <= 0:
                # 刷题 session 不生成 0% 科目切片，也不计入顶层 sessions
                continue
            target_duration += day_contrib
            key, code, name = _resolve_subject(s)
            g = target_groups.setdefault(
                key,
                {
                    "subject_id": key,
                    "subject_code": code,
                    "subject_name": name,
                    "duration_sec": 0,
                    "sessions": 0,
                },
            )
            g["duration_sec"] += day_contrib
            if start_day == target:
                g["sessions"] += 1

    result: dict = {}
    if need_stats:
        result["stats"] = {
            "today_sessions": today_sessions,
            "today_duration_sec": today_duration,
            "week_sessions": week_sessions,
            "week_duration_sec": week_duration,
            "today_date": today.isoformat(),
            "week_start_date": week_start_date.isoformat(),
            "day_start_minute": dsm,
            "day_start_time": settings["day_start_time"],
        }
    if need_trends:
        result["trends"] = [
            {
                "date": d.isoformat(),
                "sessions": trend_agg[d]["sessions"],
                "duration_sec": trend_agg[d]["duration_sec"],
            }
            for d in sorted(trend_agg)
        ]
    if need_daily_summary:
        subjects = [
            {
                "subject_id": key,
                "subject_code": g["subject_code"],
                "subject_name": g["subject_name"],
                "sessions": g["sessions"],
                "duration_sec": g["duration_sec"],
            }
            for key, g in target_groups.items()
        ]
        subjects.sort(key=lambda r: r["duration_sec"], reverse=True)
        result["daily_summary"] = {
            "date": target.isoformat(),
            "timezone": "Asia/Shanghai",
            "day_start_minute": dsm,
            "day_start_time": settings["day_start_time"],
            "sessions": target_sessions,
            "duration_sec": target_duration,
            "subjects": subjects,
        }
    if need_range_summary:
        range_subjects = [
            {
                "subject_id": key,
                "subject_code": g["subject_code"],
                "subject_name": g["subject_name"],
                "sessions": g["sessions"],
                "duration_sec": g["duration_sec"],
            }
            for key, g in range_groups.items()
        ]
        range_subjects.sort(key=lambda r: r["duration_sec"], reverse=True)
        result["range_summary"] = {
            "start_date": range_start.isoformat(),
            "end_date": range_end.isoformat(),
            "timezone": "Asia/Shanghai",
            "day_start_minute": dsm,
            "day_start_time": settings["day_start_time"],
            "sessions": range_sessions,
            "duration_sec": range_duration,
            "active_days": len(range_active_day_set),
            "subjects": range_subjects,
        }
    return result


async def get_stats(db: AsyncSession, user_id: int) -> dict:
    snapshot = await build_pomodoro_statistics_snapshot(db, user_id, need_stats=True)
    return snapshot["stats"]


async def get_trends(db: AsyncSession, user_id: int, days: int = 7) -> list[dict]:
    snapshot = await build_pomodoro_statistics_snapshot(
        db, user_id, trends_days=days, need_trends=True
    )
    return snapshot["trends"]


async def get_subject_breakdown(
    db: AsyncSession,
    user_id: int,
    filter_date: date | None = None,
) -> list[dict]:
    snapshot = await build_pomodoro_statistics_snapshot(
        db, user_id, target_date=filter_date, need_daily_summary=True
    )
    return snapshot["daily_summary"]["subjects"]


async def get_daily_summary(
    db: AsyncSession,
    user_id: int,
    filter_date: date | None = None,
) -> dict:
    snapshot = await build_pomodoro_statistics_snapshot(
        db, user_id, target_date=filter_date, need_daily_summary=True
    )
    return snapshot["daily_summary"]


async def get_range_summary(
    db: AsyncSession,
    user_id: int,
    start_date: date,
    end_date: date,
) -> dict:
    snapshot = await build_pomodoro_statistics_snapshot(
        db,
        user_id,
        range_start=start_date,
        range_end=end_date,
        need_range_summary=True,
    )
    return snapshot["range_summary"]


async def get_lifetime_summary(db: AsyncSession, user_id: int) -> dict:
    """Return a compact focus roll-up from the first recorded study day.

    Terminal completed/interrupted focus uses the same attribution path as day/range
    views, so the cumulative card stays consistent with the other statistics
    surfaces. Active sessions are deliberately excluded until they are finished.
    """
    settings = await get_pomodoro_settings(db, user_id)
    dsm = settings["day_start_minute"]
    today = current_study_day(dsm)

    pomo_first = await db.scalar(
        select(func.min(PomodoroSession.start_time)).where(
            PomodoroSession.user_id == user_id,
            PomodoroSession.status.in_(POMODORO_STATS_STATUSES),
        )
    )
    practice_first = await db.scalar(
        select(func.min(PracticeSession.started_at)).where(
            PracticeSession.user_id == user_id,
            PracticeSession.status == "completed",
        )
    )
    review_first = await db.scalar(
        select(func.min(ReviewSession.started_at)).where(
            ReviewSession.user_id == user_id,
            ReviewSession.status == "completed",
        )
    )
    first_candidates = [
        value
        for value in (pomo_first, practice_first, review_first)
        if value is not None
    ]
    start_date = (
        study_day_for_utc(min(first_candidates), dsm) if first_candidates else today
    )

    snapshot = await build_pomodoro_statistics_snapshot(
        db,
        user_id,
        range_start=start_date,
        range_end=today,
        need_range_summary=True,
        range_include_subjects=False,
    )
    summary = snapshot["range_summary"]
    return {
        "start_date": start_date.isoformat(),
        "end_date": today.isoformat(),
        "sessions": summary["sessions"],
        "duration_sec": summary["duration_sec"],
        "active_days": summary["active_days"],
    }


async def get_history(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    filter_date: date | None = None,
) -> tuple[list[dict], int]:
    """统计页统一学习记录 history — PomodoroSession + PracticeSession + ReviewSession 混排。

    - 各来源统一按 start_time DESC 排序后做全局 offset/limit（UNION 子查询），
      保证分页与 total 严格正确，不存在"各来源各自取 N 条再拼接"丢页问题。
    - 按 start_time / started_at 对应的统计日过滤（遵守用户 day_start_minute）。
    - 每条记录带唯一 record_key（``pomodoro:<id>`` / ``practice:<id>`` / ``review:<id>``）。
    """
    pomo_where = [
        PomodoroSession.user_id == user_id,
        ~PomodoroSession.status.in_(["running", "paused"]),
    ]
    practice_where = [
        PracticeSession.user_id == user_id,
        PracticeSession.status == "completed",
    ]
    review_where = [
        ReviewSession.user_id == user_id,
        ReviewSession.status == "completed",
    ]
    if filter_date is not None:
        dsm = (await get_pomodoro_settings(db, user_id))["day_start_minute"]
        start_utc, end_utc = study_day_utc_range(filter_date, dsm)
        pomo_where.extend(
            [
                PomodoroSession.start_time >= start_utc,
                PomodoroSession.start_time < end_utc,
            ]
        )
        practice_where.extend(
            [
                PracticeSession.started_at >= start_utc,
                PracticeSession.started_at < end_utc,
            ]
        )
        review_where.extend(
            [
                ReviewSession.started_at >= start_utc,
                ReviewSession.started_at < end_utc,
            ]
        )

    pomo_cols = select(
        literal("pomodoro").label("record_type"),
        PomodoroSession.id.label("id"),
        PomodoroSession.user_id.label("user_id"),
        PomodoroSession.subject_id.label("subject_id"),
        PomodoroSession.start_time.label("start_time"),
        PomodoroSession.end_time.label("end_time"),
        PomodoroSession.actual_duration.label("actual_duration"),
        PomodoroSession.status.label("status"),
        PomodoroSession.preset.label("preset"),
    ).where(*pomo_where)

    practice_cols = select(
        literal("practice").label("record_type"),
        PracticeSession.id.label("id"),
        PracticeSession.user_id.label("user_id"),
        PracticeSession.subject_id.label("subject_id"),
        PracticeSession.started_at.label("start_time"),
        PracticeSession.finished_at.label("end_time"),
        PracticeSession.duration_sec.label("actual_duration"),
        PracticeSession.status.label("status"),
        null().label("preset"),
    ).where(*practice_where)

    review_cols = select(
        literal("review").label("record_type"),
        ReviewSession.id.label("id"),
        ReviewSession.user_id.label("user_id"),
        ReviewSession.subject_id.label("subject_id"),
        ReviewSession.started_at.label("start_time"),
        ReviewSession.finished_at.label("end_time"),
        ReviewSession.duration_sec.label("actual_duration"),
        ReviewSession.status.label("status"),
        null().label("preset"),
    ).where(*review_where)

    merged = pomo_cols.union_all(practice_cols, review_cols).subquery()

    total = (await db.execute(select(func.count()).select_from(merged))).scalar() or 0

    rows = (
        await db.execute(
            select(merged)
            .order_by(
                merged.c.start_time.desc(),
                merged.c.record_type.desc(),
                merged.c.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    subject_ids = {r.subject_id for r in rows if r.subject_id is not None}
    subject_map: dict[int, "Subject"] = {}
    if subject_ids:
        subj_result = await db.execute(
            select(Subject).where(Subject.id.in_(subject_ids))
        )
        subject_map = {s.id: s for s in subj_result.scalars().all()}

    items: list[dict] = []
    for r in rows:
        subj = subject_map.get(r.subject_id) if r.subject_id is not None else None
        items.append(
            {
                "record_key": f"{r.record_type}:{r.id}",
                "record_type": r.record_type,
                "id": r.id,
                "user_id": r.user_id,
                "subject_id": r.subject_id,
                "subject_code": subj.code if subj else "",
                "subject_name": subj.name if subj else "未分类",
                "start_time": r.start_time,
                "end_time": r.end_time,
                "actual_duration": r.actual_duration,
                "status": r.status,
                "preset": r.preset,
            }
        )
    return items, total
