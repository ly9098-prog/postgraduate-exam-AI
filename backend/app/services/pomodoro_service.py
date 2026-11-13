import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, literal, null, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.core.subject_scope import (
    EXAM408_CORE_CODES,
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
    PomodoroSubjectAllocation,
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
from app.services.pomodoro_history_projection import build_history_item
from app.services.pomodoro_start_request import PomodoroStartRequest
from app.services.pomodoro_statistics_accumulation import (
    StatisticsAccumulationState,
    accumulate_focus_sessions,
    accumulate_supplemental_sessions,
)
from app.services.pomodoro_statistics_response import build_statistics_response
from app.services.pomodoro_statistics_window import (
    StatisticsWindowRequest,
    requested_statistics_period,
)
from app.services.pomodoro_subject_projection import (
    allocate_seconds_by_weight,
    allocation_group_key,
    resolve_allocations,
    resolve_subject,
)

logger = logging.getLogger(__name__)

FREE_TIMER_MAX_DURATION_SEC = 5 * 60 * 60
COUNTDOWN_COMPLETE_EARLY_TOLERANCE_SEC = 2
CLIENT_ACTION_FUTURE_TOLERANCE_SEC = 5
CLIENT_ACTION_PAST_TOLERANCE_SEC = 5
EQUAL_408_MODE = "equal_408_core_v1"

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


async def _refresh_session_state(db: AsyncSession, session: PomodoroSession) -> None:
    await db.refresh(session)
    rows = await db.execute(
        select(PomodoroSubjectAllocation)
        .where(PomodoroSubjectAllocation.session_id == session.id)
        .order_by(PomodoroSubjectAllocation.subject_code_snapshot)
    )
    set_committed_value(session, "subject_allocations", list(rows.scalars().all()))


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
    candidate, explicit_client_time = _normalize_explicit_action_time(
        client_action_at, server_now
    )
    _reject_implausible_client_time(
        session,
        candidate,
        server_now,
        explicit_client_time=explicit_client_time,
        reject_stale_before=reject_stale_before,
    )
    lower = session.start_time
    if floor is not None and floor > lower:
        lower = floor
    return max(lower, min(max(candidate, lower), server_now))


def _normalize_explicit_action_time(
    client_action_at: datetime | None, server_now: datetime
) -> tuple[datetime, bool]:
    if client_action_at is None:
        return server_now, False
    try:
        return normalize_to_naive_utc(client_action_at), True
    except (TypeError, ValueError):
        return server_now, False


def _reject_implausible_client_time(
    session,
    candidate: datetime,
    server_now: datetime,
    *,
    explicit_client_time: bool,
    reject_stale_before: datetime | None,
) -> None:
    if not explicit_client_time:
        return
    if candidate > server_now + timedelta(seconds=CLIENT_ACTION_FUTURE_TOLERANCE_SEC):
        raise PomodoroClockSkewError("POMODORO_CLOCK_SKEW")
    if candidate < session.start_time - timedelta(
        seconds=CLIENT_ACTION_PAST_TOLERANCE_SEC
    ):
        raise PomodoroClockSkewError("POMODORO_CLOCK_SKEW")
    if reject_stale_before is not None and candidate < reject_stale_before:
        raise PomodoroStaleActionError("POMODORO_STALE_ACTION")


async def _get_session_by_client_start_id(
    db: AsyncSession, user_id: int, client_start_id: str | None
) -> PomodoroSession | None:
    if not client_start_id:
        return None
    result = await db.execute(
        select(PomodoroSession)
        .options(
            joinedload(PomodoroSession.subject_ref),
            selectinload(PomodoroSession.subject_allocations),
        )
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
    allocation_mode: str = "single",
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
        and (len(getattr(session, "subject_allocations", []) or []) > 1)
        == (allocation_mode == EQUAL_408_MODE)
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
    allocation_mode: str = "single",
) -> PomodoroSession:
    if allocation_mode not in ("single", EQUAL_408_MODE):
        raise ValueError("不支持的科目分配模式")
    request = PomodoroStartRequest(
        subject_id=subject_id,
        chapter_id=chapter_id,
        preset=preset,
        work_duration=work_duration,
        break_duration=break_duration,
        notification_enabled=notification_enabled,
    )
    existing = await _get_session_by_client_start_id(db, user_id, client_start_id)
    if existing is not None:
        _require_matching_start_payload(existing, request, allocation_mode)
        return existing
    if await get_active_session(db, user_id) is not None:
        raise ValueError("当前已有进行中的专注，请先结束后再开始")
    return await _create_start_session(
        db,
        user_id=user_id,
        client_start_id=client_start_id,
        allocation_mode=allocation_mode,
        request=request,
    )


async def _create_start_session(
    db: AsyncSession,
    *,
    user_id: int,
    client_start_id: str | None,
    allocation_mode: str,
    request: PomodoroStartRequest,
) -> PomodoroSession:
    start_payload = await _prepare_new_start(db, user_id, request, allocation_mode)
    session = _new_pomodoro_session(
        client_start_id=client_start_id,
        allocation_mode=allocation_mode,
        start_payload=start_payload,
        request=request,
    )
    try:
        async with db.begin_nested():
            db.add(session)
            await db.flush()
    except IntegrityError as exc:
        return await _handle_start_integrity_race(
            db,
            user_id,
            request,
            client_start_id=client_start_id,
            allocation_mode=allocation_mode,
            exc=exc,
        )

    await db.refresh(session, attribute_names=["created_at"])
    session.subject_ref = start_payload["subject"]
    return session


async def _prepare_new_start(
    db: AsyncSession, user_id: int, request: PomodoroStartRequest, allocation_mode: str
):
    user_row = await db.execute(select(User.openid).where(User.id == user_id))
    openid_snapshot = user_row.scalar_one_or_none()
    work_duration, break_duration, notification_enabled = _normalize_start_preset(
        request.preset,
        request.work_duration,
        request.break_duration,
        request.notification_enabled,
    )
    start = utcnow()
    expected_end = _initial_expected_end(start, work_duration)
    subj, _, allocation_subjects = await _resolve_start_subjects(
        db, request.subject_id, allocation_mode
    )
    return {
        "openid_snapshot": openid_snapshot,
        "work_duration": work_duration,
        "break_duration": break_duration,
        "notification_enabled": notification_enabled,
        "start": start,
        "expected_end": expected_end,
        "subject": subj,
        "allocation_subjects": allocation_subjects,
        "user_id": user_id,
    }


def _require_matching_start_payload(
    existing: PomodoroSession,
    request: PomodoroStartRequest,
    allocation_mode: str,
) -> None:
    if not _start_payload_matches(
        existing,
        subject_id=request.subject_id,
        chapter_id=request.chapter_id,
        preset=request.preset,
        work_duration=request.work_duration,
        break_duration=request.break_duration,
        notification_enabled=request.notification_enabled,
        allocation_mode=allocation_mode,
    ):
        raise PomodoroStartIdempotencyConflictError(
            "POMODORO_START_IDEMPOTENCY_CONFLICT"
        )


def _normalize_start_preset(
    preset: str, work_duration: int, break_duration: int, notification_enabled: bool
):
    # Free timer overrides: no countdown, no notification.
    if preset == "free":
        return 0, 0, False
    if work_duration <= 0:
        raise ValueError("非自由计时模式需要设置学习时长")
    return work_duration, break_duration, notification_enabled


def _initial_expected_end(start: datetime, work_duration: int) -> datetime | None:
    if work_duration <= 0:
        return None
    return start + timedelta(minutes=max(0, work_duration))


async def _resolve_start_subjects(
    db: AsyncSession, subject_id: int, allocation_mode: str
):
    subj = await db.get(Subject, subject_id)
    if subj is None:
        raise ValueError(f"科目不存在: subject_id={subject_id}")
    if not is_study_subject_enabled(subj):
        raise ValueError(f"科目不可用: {subj.name}")
    all_subjects = list((await db.execute(select(Subject))).scalars().all())
    enabled_ids = {item.id for item in select_study_subject_records(all_subjects)}
    if subject_id not in enabled_ids:
        raise ValueError(f"科目不可用: {subj.name}")
    if allocation_mode == EQUAL_408_MODE:
        allocation_subjects = _equal_408_subjects(subj, all_subjects, enabled_ids)
    else:
        allocation_subjects = _single_start_subjects(
            subj, all_subjects, enabled_ids, subject_id
        )
    return subj, all_subjects, allocation_subjects


def _equal_408_subjects(
    subj: Subject, all_subjects: list[Subject], enabled_ids: set[int]
) -> list[Subject]:
    if subj.code != "exam408":
        raise ValueError("四科均分模式只能选择 408 父级科目")
    children_by_code = {
        item.code: item
        for item in all_subjects
        if item.parent_id == subj.id
        and item.code in EXAM408_CORE_CODES
        and item.id in enabled_ids
    }
    if set(children_by_code) != set(EXAM408_CORE_CODES):
        raise ValueError("408 四科配置不完整或不可用，暂不能使用四科均分")
    allocation_subjects = [children_by_code[code] for code in EXAM408_CORE_CODES]
    if any(
        item.parent_id != subj.id
        or any(
            child.parent_id == item.id and child.id in enabled_ids
            for child in all_subjects
        )
        for item in allocation_subjects
    ):
        raise ValueError("408 四科配置无效，暂不能使用四科均分")
    return allocation_subjects


def _single_start_subjects(
    subj: Subject,
    all_subjects: list[Subject],
    enabled_ids: set[int],
    subject_id: int,
) -> list[Subject]:
    if any(
        item.parent_id == subject_id and item.id in enabled_ids for item in all_subjects
    ):
        raise ValueError(f"请选择具体子科目，不能选择父级科目: {subj.name}")
    return [subj]


def _new_pomodoro_session(
    *,
    client_start_id: str | None,
    allocation_mode: str,
    start_payload: dict,
    request: PomodoroStartRequest,
) -> PomodoroSession:
    session = PomodoroSession(
        user_id=start_payload["user_id"],
        subject_id=request.subject_id,
        chapter_id=request.chapter_id,
        client_start_id=client_start_id,
        preset=request.preset,
        work_duration=start_payload["work_duration"],
        break_duration=start_payload["break_duration"],
        start_time=start_payload["start"],
        expected_end_time=start_payload["expected_end"],
        status="running",
        notification_enabled=bool(start_payload["notification_enabled"]),
        notification_sent=False,
        openid_snapshot=start_payload["openid_snapshot"],
    )
    session.subject_allocations = [
        PomodoroSubjectAllocation(
            subject_id=item.id,
            weight_basis_points=2500 if allocation_mode == EQUAL_408_MODE else 10000,
            subject_code_snapshot=item.code,
            subject_name_snapshot=item.name,
        )
        for item in start_payload["allocation_subjects"]
    ]
    return session


async def _handle_start_integrity_race(
    db: AsyncSession,
    user_id: int,
    request: PomodoroStartRequest,
    *,
    client_start_id: str | None,
    allocation_mode: str,
    exc: IntegrityError,
):
    # First check the idempotency key: concurrent retries with the same key can
    # lose either the client-key index race or the one-active-session race.
    existing = await _get_session_by_client_start_id(db, user_id, client_start_id)
    if existing is not None:
        _require_matching_start_payload(existing, request, allocation_mode)
        return existing

    conflict = await get_active_session(db, user_id)
    if conflict is not None:
        logger.info(
            "pomodoro start_session: active-session uniqueness race for user %s",
            user_id,
        )
        raise ValueError("当前已有进行中的专注，请先结束后再开始") from exc
    raise


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
    session = await _locked_session_with_state(
        db,
        session_id,
        user_id,
        ["running", "paused", "completed", "interrupted"],
    )
    if not session:
        return None
    return await _apply_completed_terminal_action(db, session, client_action_at)


async def _apply_completed_terminal_action(
    db: AsyncSession, session: PomodoroSession, client_action_at: datetime | None
) -> PomodoroSession | None:
    now = utcnow()
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
    await _refresh_session_state(db, session)
    return session


async def _locked_session_with_state(
    db: AsyncSession, session_id: int, user_id: int, statuses: list[str]
) -> PomodoroSession | None:
    result = await db.execute(
        select(PomodoroSession)
        .options(
            joinedload(PomodoroSession.subject_ref),
            selectinload(PomodoroSession.pause_intervals),
            selectinload(PomodoroSession.subject_allocations),
        )
        .where(
            PomodoroSession.id == session_id,
            PomodoroSession.user_id == user_id,
            PomodoroSession.status.in_(statuses),
        )
        .with_for_update(of=PomodoroSession)
    )
    return result.scalar_one_or_none()


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
            selectinload(PomodoroSession.subject_allocations),
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
    await _refresh_session_state(db, session)
    return session


async def pause_session(
    db: AsyncSession,
    session_id: int,
    user_id: int,
    client_action_at: datetime | None = None,
) -> PomodoroSession | None:
    session = await _locked_session_with_state(
        db, session_id, user_id, ["running", "paused"]
    )
    if not session:
        return None
    if session.status == "paused":
        return await _repair_delayed_pause(db, session, client_action_at, utcnow())
    return await _open_new_pause_interval(db, session, client_action_at, utcnow())


async def _repair_delayed_pause(
    db: AsyncSession,
    session: PomodoroSession,
    client_action_at: datetime | None,
    now: datetime,
) -> PomodoroSession:
    # State-idempotent is not timeline-idempotent. If an earlier pause from
    # another device arrives after a later pause already committed, move the
    # open interval back so those seconds are not falsely counted as focus.
    open_interval = next(
        (i for i in session.pause_intervals if i.ended_at is None), None
    )
    if client_action_at is None or open_interval is None:
        await _refresh_session_state(db, session)
        return session

    prior_latest = _prior_event_time(session, excluded=open_interval)
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
        await _refresh_session_state(db, session)
    return session


async def _open_new_pause_interval(
    db: AsyncSession,
    session: PomodoroSession,
    client_action_at: datetime | None,
    now: datetime,
) -> PomodoroSession:
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
        return await _rollback_concurrent_pause(db, session)
    return session


async def _rollback_concurrent_pause(
    db: AsyncSession, session: PomodoroSession
) -> PomodoroSession:
    logger.warning(
        "pomodoro pause_session: concurrent open pause interval for session %s; treating as idempotent",
        session.id,
    )
    session.pause_intervals[:] = [
        i for i in session.pause_intervals if i.id is not None
    ]
    session.paused_at = None
    session.status = "running"
    await _refresh_session_state(db, session)
    return session


def _prior_event_time(session, excluded=None) -> datetime:
    prior_latest = session.start_time
    for interval in session.pause_intervals:
        if interval is excluded:
            continue
        if interval.started_at is not None:
            prior_latest = max(prior_latest, interval.started_at)
        if interval.ended_at is not None:
            prior_latest = max(prior_latest, interval.ended_at)
    return prior_latest


async def resume_session(
    db: AsyncSession,
    session_id: int,
    user_id: int,
    client_action_at: datetime | None = None,
) -> PomodoroSession | None:
    session = await _locked_session_with_state(
        db, session_id, user_id, ["running", "paused"]
    )
    if not session:
        return None
    now = utcnow()
    open_interval = next(
        (i for i in session.pause_intervals if i.ended_at is None), None
    )
    if session.status == "running" and open_interval is None:
        return await _repair_delayed_resume(db, session, client_action_at, now)
    return await _resume_open_pause(db, session, open_interval, client_action_at, now)


async def _repair_delayed_resume(
    db: AsyncSession,
    session: PomodoroSession,
    client_action_at: datetime | None,
    now: datetime,
) -> PomodoroSession:
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
        _shorten_latest_closed_pause(session, latest_closed, client_action_at, now)
    elif client_action_at is not None:
        # Validate obvious future skew; a duplicate resume with no pause history
        # has no timeline effect and can remain idempotent.
        _resolve_client_action_time(
            session, client_action_at, now, floor=session.start_time
        )
    return await _recompute_running_state(db, session, now)


def _shorten_latest_closed_pause(
    session: PomodoroSession,
    latest_closed,
    client_action_at: datetime | None,
    now: datetime,
) -> None:
    prior_latest = _prior_event_time(session, excluded=latest_closed)
    if latest_closed.started_at is not None:
        prior_latest = max(prior_latest, latest_closed.started_at)
    floor = max(prior_latest, latest_closed.started_at + timedelta(microseconds=1))
    action_time = _resolve_client_action_time(
        session,
        client_action_at,
        now,
        floor=floor,
        reject_stale_before=prior_latest,
    )
    if action_time < latest_closed.ended_at:
        latest_closed.ended_at = action_time


async def _resume_open_pause(
    db: AsyncSession,
    session: PomodoroSession,
    open_interval,
    client_action_at: datetime | None,
    now: datetime,
) -> PomodoroSession:
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
    _extend_expected_end(session)
    await db.flush()
    await _refresh_session_state(db, session)
    return session


async def _recompute_running_state(
    db: AsyncSession, session: PomodoroSession, now: datetime
) -> PomodoroSession:
    session.total_paused_sec = _effective_paused_sec(session, now)
    _extend_expected_end(session)
    await db.flush()
    await _refresh_session_state(db, session)
    return session


def _extend_expected_end(session: PomodoroSession) -> None:
    if session.status == "running" and session.expected_end_time is not None:
        session.expected_end_time = (
            session.start_time
            + timedelta(minutes=session.work_duration)
            + timedelta(seconds=session.total_paused_sec)
        )


async def get_active_session(
    db: AsyncSession, user_id: int, *, include_allocations: bool = False
) -> PomodoroSession | None:
    options = [joinedload(PomodoroSession.subject_ref)]
    if include_allocations:
        options.append(selectinload(PomodoroSession.subject_allocations))
    result = await db.execute(
        select(PomodoroSession)
        .options(*options)
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
        "subject_allocations",
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
        subject_allocations: list | None = None,
    ):
        self.start_time = start_time
        self.end_time = end_time
        self.actual_duration = actual_duration
        self.status = status
        self.subject_id = subject_id
        self.subject_ref = subject_ref
        self.pause_intervals = pause_intervals or []
        self.subject_allocations = subject_allocations or []


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
        return await _load_sessions_with_subject(db, overlap)

    return await _load_sessions_without_subject(db, overlap)


async def _load_sessions_with_subject(db: AsyncSession, overlap) -> list[_LiteSession]:
    result = await db.execute(
        select(PomodoroSession)
        .options(
            joinedload(PomodoroSession.subject_ref),
            joinedload(PomodoroSession.subject_allocations),
            selectinload(PomodoroSession.pause_intervals),
        )
        .where(*overlap)
    )
    return [_subject_lite_session(s) for s in result.unique().scalars().all()]


def _subject_lite_session(s: PomodoroSession) -> _LiteSession:
    ref = s.subject_ref
    return _LiteSession(
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
        pause_intervals=[
            SimpleNamespace(started_at=i.started_at, ended_at=i.ended_at)
            for i in s.pause_intervals
        ],
        subject_allocations=[
            SimpleNamespace(
                subject_id=a.subject_id,
                subject_code=a.subject_code_snapshot,
                subject_name=a.subject_name_snapshot,
                weight_basis_points=a.weight_basis_points,
            )
            for a in (s.subject_allocations or [])
        ],
    )


async def _load_sessions_without_subject(db, overlap) -> list[_LiteSession]:

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
    pauses = await _load_chunked_pauses(db, [r.id for r in rows])
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


async def _load_chunked_pauses(
    db: AsyncSession, session_ids: list[int]
) -> dict[int, list]:
    pauses: dict[int, list] = {}
    for chunk in _chunks(session_ids, 500):
        result = await db.execute(
            select(
                PomodoroPauseInterval.session_id,
                PomodoroPauseInterval.started_at,
                PomodoroPauseInterval.ended_at,
            ).where(PomodoroPauseInterval.session_id.in_(chunk))
        )
        for sid, started_at, ended_at in result.all():
            pauses.setdefault(sid, []).append(
                SimpleNamespace(started_at=started_at, ended_at=ended_at)
            )
    return pauses


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

    merged = _merged_practice_review_subquery(user_id, period_start, period_end)
    if not with_subject:
        return await _load_practice_lite_sessions(db, merged)

    return await _load_practice_subject_sessions(db, merged)


def _merged_practice_review_subquery(
    user_id: int, period_start: datetime, period_end: datetime
):
    # Select only attribution columns. PracticeSession carries a potentially
    # large submission_response JSON used for idempotent result replay; loading
    # full ORM rows here would deserialize that payload for every stats query
    # even though attribution never reads it.
    def cols(model):
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

    return cols(PracticeSession).union_all(cols(ReviewSession)).subquery()


async def _load_practice_lite_sessions(db: AsyncSession, merged) -> list[_LiteSession]:
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


async def _load_practice_subject_sessions(
    db: AsyncSession, merged
) -> list[_LiteSession]:
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
    return [_practice_subject_lite_session(row) for row in result.all()]


def _practice_subject_lite_session(row) -> _LiteSession:
    has_subject = (
        row.code is not None or row.name is not None or row.is_active is not None
    )
    return _LiteSession(
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
    """One bounded window load and one attribution pass for requested dimensions."""
    settings, today, target, needs, sessions, state = await _build_snapshot_state(
        db,
        user_id,
        target_date=target_date,
        trends_days=trends_days,
        need_stats=need_stats,
        need_trends=need_trends,
        need_daily_summary=need_daily_summary,
        need_range_summary=need_range_summary,
        range_start=range_start,
        range_end=range_end,
        range_include_subjects=range_include_subjects,
    )
    if state is None:
        return {}
    _accumulate_snapshot_sessions(state, sessions, settings["day_start_minute"])
    return _snapshot_response(
        settings=settings,
        state=state,
        needs=needs,
        today=today,
        target=target,
        range_start=range_start,
        range_end=range_end,
    )


async def _build_snapshot_state(
    db: AsyncSession,
    user_id: int,
    *,
    target_date: date | None,
    trends_days: int,
    need_stats: bool,
    need_trends: bool,
    need_daily_summary: bool,
    need_range_summary: bool,
    range_start: date | None,
    range_end: date | None,
    range_include_subjects: bool,
):
    settings = await get_pomodoro_settings(db, user_id)
    today, target = _snapshot_dates(settings, target_date)
    needs = (need_stats, need_trends, need_daily_summary, need_range_summary)
    period = _snapshot_period(
        settings=settings,
        today=today,
        target=target,
        trends_days=trends_days,
        needs=needs,
        range_start=range_start,
        range_end=range_end,
    )
    if period is None:
        return settings, today, target, needs, None, None
    sessions, state = await _prepare_snapshot_state(
        db,
        user_id,
        settings=settings,
        today=today,
        target=target,
        trends_days=trends_days,
        needs=needs,
        period=period,
        range_include_subjects=range_include_subjects,
        range_start=range_start,
        range_end=range_end,
        need_stats=need_stats,
        need_trends=need_trends,
        need_daily_summary=need_daily_summary,
        need_range_summary=need_range_summary,
    )
    return settings, today, target, needs, sessions, state


def _snapshot_dates(settings, target_date: date | None) -> tuple[date, date]:
    today = current_study_day(settings["day_start_minute"])
    return today, target_date or today


def _snapshot_with_subject(needs, range_include_subjects: bool) -> bool:
    _, _, need_daily_summary, need_range_summary = needs
    return need_daily_summary or (need_range_summary and range_include_subjects)


def _snapshot_period(
    *,
    settings,
    today,
    target,
    trends_days,
    needs,
    range_start,
    range_end,
):
    need_stats, need_trends, need_daily_summary, need_range_summary = needs
    return _requested_snapshot_period(
        dsm=settings["day_start_minute"],
        today=today,
        target=target,
        trends_days=trends_days,
        need_stats=need_stats,
        need_trends=need_trends,
        need_daily_summary=need_daily_summary,
        range_start=range_start,
        range_end=range_end,
        need_range_summary=need_range_summary,
    )


def _snapshot_accumulation_state(
    *,
    settings,
    today,
    target,
    trends_days,
    need_stats,
    need_trends,
    need_daily_summary,
    need_range_summary,
    range_include_subjects,
    range_start,
    range_end,
) -> StatisticsAccumulationState:
    state, _, _, _ = _initial_snapshot_state(
        dsm=settings["day_start_minute"],
        today=today,
        target=target,
        trends_days=trends_days,
        need_stats=need_stats,
        need_trends=need_trends,
        need_daily_summary=need_daily_summary,
        need_range_summary=need_range_summary,
        range_include_subjects=range_include_subjects,
        range_start=range_start,
        range_end=range_end,
    )
    return state


async def _load_snapshot_sessions(
    db: AsyncSession,
    user_id: int,
    period_start: datetime,
    period_end: datetime,
    *,
    needs,
    range_include_subjects: bool,
) -> tuple[list[_LiteSession], list[_LiteSession]]:
    with_subject = _snapshot_with_subject(needs, range_include_subjects)
    pomodoro_sessions = await _load_overlapping_sessions(
        db, user_id, period_start, period_end, with_subject=with_subject
    )
    # 今日复习（ReviewSession）与刷题会话同口径并入：仅补充时长，不计番茄次数。
    practice_sessions = await _load_overlapping_practice_sessions(
        db, user_id, period_start, period_end, with_subject=with_subject
    )
    return pomodoro_sessions, practice_sessions


async def _prepare_snapshot_state(
    db: AsyncSession,
    user_id: int,
    *,
    settings,
    today,
    target,
    trends_days: int,
    needs,
    period,
    range_include_subjects: bool,
    range_start,
    range_end,
    need_stats: bool,
    need_trends: bool,
    need_daily_summary: bool,
    need_range_summary: bool,
) -> tuple[tuple[list[_LiteSession], list[_LiteSession]], StatisticsAccumulationState]:
    period_start, period_end = period
    sessions = await _load_snapshot_sessions(
        db,
        user_id,
        period_start,
        period_end,
        needs=needs,
        range_include_subjects=range_include_subjects,
    )
    state = _snapshot_accumulation_state(
        settings=settings,
        today=today,
        target=target,
        trends_days=trends_days,
        need_stats=need_stats,
        need_trends=need_trends,
        need_daily_summary=need_daily_summary,
        need_range_summary=need_range_summary,
        range_include_subjects=range_include_subjects,
        range_start=range_start,
        range_end=range_end,
    )
    return sessions, state


def _initial_snapshot_state(
    *,
    dsm: int,
    today: date,
    target: date,
    trends_days: int,
    need_stats: bool,
    need_trends: bool,
    need_daily_summary: bool,
    need_range_summary: bool,
    range_include_subjects: bool,
    range_start: date | None,
    range_end: date | None,
) -> tuple[StatisticsAccumulationState, dict[date, dict[str, int]], date, date]:
    week_start_date, week_end_date = _statistics_week_dates(dsm)
    trend_agg = _initial_trends(today, trends_days) if need_trends else {}
    state = _initial_accumulation_state(
        need_stats=need_stats,
        need_trends=need_trends,
        need_daily_summary=need_daily_summary,
        need_range_summary=need_range_summary,
        range_include_subjects=range_include_subjects,
        today=today,
        target=target,
        range_start=range_start,
        range_end=range_end,
        week_start_date=week_start_date,
        week_end_date=week_end_date,
        trends=trend_agg,
    )
    return state, trend_agg, week_start_date, week_end_date


def _accumulate_snapshot_sessions(
    state: StatisticsAccumulationState,
    sessions: tuple[list[_LiteSession], list[_LiteSession]],
    dsm: int,
) -> None:
    pomodoro_sessions, practice_sessions = sessions
    accumulate_focus_sessions(
        pomodoro_sessions,
        state,
        day_start_minute=dsm,
        terminal_statuses=POMODORO_STATS_TERMINAL_STATUSES,
        active_intervals=active_intervals_for_session,
        split_by_day=split_session_duration_by_study_day,
        study_day_for_utc=study_day_for_utc,
        resolve_allocations=resolve_allocations,
        allocation_group_key=allocation_group_key,
        allocate_seconds=allocate_seconds_by_weight,
    )
    accumulate_supplemental_sessions(
        practice_sessions,
        state,
        day_start_minute=dsm,
        split_excluding=split_duration_excluding_intervals,
        study_day_for_utc=study_day_for_utc,
        resolve_subject=resolve_subject,
    )


def _snapshot_response(
    *,
    settings,
    state,
    needs,
    today,
    target,
    range_start,
    range_end,
):
    need_stats, need_trends, need_daily_summary, need_range_summary = needs
    week_start_date = state.week_start_date
    trend_agg = state.trends if need_trends else None
    return _statistics_response(
        settings=settings,
        state=state,
        need_stats=need_stats,
        need_trends=need_trends,
        need_daily_summary=need_daily_summary,
        need_range_summary=need_range_summary,
        today=today,
        week_start_date=week_start_date,
        target=target,
        trend_agg=trend_agg,
        range_start=range_start,
        range_end=range_end,
    )


def _statistics_response(
    *,
    settings,
    state,
    need_stats,
    need_trends,
    need_daily_summary,
    need_range_summary,
    today,
    week_start_date,
    target,
    trend_agg,
    range_start,
    range_end,
):
    return build_statistics_response(
        need_stats=need_stats,
        need_trends=need_trends,
        need_daily_summary=need_daily_summary,
        need_range_summary=need_range_summary,
        today=today,
        week_start_date=week_start_date,
        target=target,
        day_start_minute=settings["day_start_minute"],
        day_start_time=settings["day_start_time"],
        trends=trend_agg if need_trends else None,
        stats_values={**state.stats},
        daily_values={**state.daily},
        range_values={
            "start_date": range_start,
            "end_date": range_end,
            "sessions": state.range["sessions"],
            "duration_sec": state.range["duration_sec"],
            "active_days": len(state.range["active_days_set"]),
            "groups": state.range["groups"],
        },
    )


def _requested_snapshot_period(
    *,
    dsm: int,
    today: date,
    target: date,
    trends_days: int,
    need_stats: bool,
    need_trends: bool,
    need_daily_summary: bool,
    range_start: date | None,
    range_end: date | None,
    need_range_summary: bool,
):
    return requested_statistics_period(
        StatisticsWindowRequest(
            day_start_minute=dsm,
            today=today,
            target=target,
            trends_days=trends_days,
            need_stats=need_stats,
            need_trends=need_trends,
            need_daily_summary=need_daily_summary,
            range_start=range_start,
            range_end=range_end,
            need_range_summary=need_range_summary,
        ),
        day_range=study_day_utc_range,
        week_range=study_week_utc_range,
    )


def _statistics_week_dates(dsm: int) -> tuple[date, date]:
    week_start_date = study_day_for_utc(study_week_utc_range(dsm)[0], dsm)
    return week_start_date, week_start_date + timedelta(days=7)


def _initial_trends(today: date, trends_days: int) -> dict[date, dict[str, int]]:
    return {
        today - timedelta(days=trends_days - 1 - i): {
            "sessions": 0,
            "duration_sec": 0,
        }
        for i in range(trends_days)
    }


def _initial_accumulation_state(
    *,
    need_stats: bool,
    need_trends: bool,
    need_daily_summary: bool,
    need_range_summary: bool,
    range_include_subjects: bool,
    today: date,
    target: date,
    range_start: date | None,
    range_end: date | None,
    week_start_date: date,
    week_end_date: date,
    trends: dict[date, dict[str, int]],
) -> StatisticsAccumulationState:
    return StatisticsAccumulationState(
        need_stats=need_stats,
        need_trends=need_trends,
        need_daily_summary=need_daily_summary,
        need_range_summary=need_range_summary,
        range_include_subjects=range_include_subjects,
        today=today,
        target=target,
        range_start=range_start,
        range_end=range_end,
        week_start_date=week_start_date,
        week_end_date=week_end_date,
        trends=trends,
        stats={
            "today_sessions": 0,
            "today_duration": 0,
            "week_sessions": 0,
            "week_duration": 0,
        },
        daily={"sessions": 0, "duration_sec": 0, "groups": {}},
        range={
            "sessions": 0,
            "duration_sec": 0,
            "groups": {},
            "active_days_set": set(),
        },
    )


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
    start_date = await _first_lifetime_study_day(db, user_id, dsm, today)

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


async def _first_lifetime_study_day(
    db: AsyncSession, user_id: int, dsm: int, today: date
) -> date:
    pomo_first = await _min_session_start(db, PomodoroSession, user_id)
    practice_first = await _min_session_start(db, PracticeSession, user_id)
    review_first = await _min_session_start(db, ReviewSession, user_id)
    first_candidates = [
        value
        for value in (pomo_first, practice_first, review_first)
        if value is not None
    ]
    return study_day_for_utc(min(first_candidates), dsm) if first_candidates else today


async def _min_session_start(db: AsyncSession, model, user_id: int):
    return await db.scalar(
        select(
            func.min(
                model.started_at if model is not PomodoroSession else model.start_time
            )
        ).where(
            model.user_id == user_id,
            model.status.in_(
                POMODORO_STATS_STATUSES if model is PomodoroSession else ["completed"]
            ),
        )
    )


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
    pomo_where, practice_where, review_where = await _history_where_clauses(
        db, user_id, filter_date
    )

    merged = _merged_history_subquery(pomo_where, practice_where, review_where)

    total, rows = await _load_history_page(db, merged, page, page_size)

    subject_map = await _history_subject_map(db, rows)
    allocation_map = await _history_allocation_map(db, rows)

    items: list[dict] = []
    for r in rows:
        subj = subject_map.get(r.subject_id) if r.subject_id is not None else None
        items.append(
            build_history_item(
                row=r,
                subject=subj,
                allocations=allocation_map.get(r.id, []),
                equal_408_mode=EQUAL_408_MODE,
            )
        )
    return items, total


def _merged_history_subquery(pomo_where, practice_where, review_where):
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
    return pomo_cols.union_all(practice_cols, review_cols).subquery()


async def _load_history_page(db: AsyncSession, merged, page: int, page_size: int):
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
    return total, rows


async def _history_subject_map(db: AsyncSession, rows) -> dict[int, "Subject"]:
    subject_ids = {r.subject_id for r in rows if r.subject_id is not None}
    if not subject_ids:
        return {}
    result = await db.execute(select(Subject).where(Subject.id.in_(subject_ids)))
    return {s.id: s for s in result.scalars().all()}


async def _history_allocation_map(db: AsyncSession, rows) -> dict[int, list[dict]]:
    pomodoro_ids = [r.id for r in rows if r.record_type == "pomodoro"]
    if not pomodoro_ids:
        return {}
    allocation_rows = (
        await db.execute(
            select(
                PomodoroSubjectAllocation.session_id,
                PomodoroSubjectAllocation.subject_id,
                PomodoroSubjectAllocation.subject_code_snapshot,
                PomodoroSubjectAllocation.subject_name_snapshot,
                PomodoroSubjectAllocation.weight_basis_points,
            )
            .where(PomodoroSubjectAllocation.session_id.in_(pomodoro_ids))
            .order_by(
                PomodoroSubjectAllocation.session_id,
                PomodoroSubjectAllocation.subject_code_snapshot,
            )
        )
    ).all()
    allocation_map: dict[int, list[dict]] = {}
    for allocation in allocation_rows:
        allocation_map.setdefault(allocation.session_id, []).append(
            {
                "subject_id": allocation.subject_id,
                "subject_code": allocation.subject_code_snapshot,
                "subject_name": allocation.subject_name_snapshot,
                "weight_basis_points": allocation.weight_basis_points,
            }
        )
    return allocation_map


async def _history_where_clauses(db: AsyncSession, user_id: int, filter_date):
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
    if filter_date is None:
        return pomo_where, practice_where, review_where
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
    return pomo_where, practice_where, review_where
