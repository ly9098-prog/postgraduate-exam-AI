import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, literal, null, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

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
from app.models.user import User
from app.services.pomodoro_attribution import (
    active_intervals_for_session,
    split_duration_excluding_intervals,
    split_session_duration_by_study_day,
)

logger = logging.getLogger(__name__)

FREE_TIMER_MAX_DURATION_SEC = 5 * 60 * 60


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
        if i.started_at is None:
            continue
        end = i.ended_at if i.ended_at is not None else now
        if end > i.started_at:
            spans.append((i.started_at, end))
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
        (i for i in getattr(session, "pause_intervals", ()) or () if i.ended_at is None),
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
) -> datetime:
    """Clamp an optional client event timestamp to a safe session timeline.

    Offline clients may synchronize pause/resume/complete later. The timestamp is
    used only to reconstruct *when* the already-authorized user action happened;
    it can never move before session start / prior canonical events or beyond the
    current server time. Invalid values fall back to ``server_now``.
    """
    if client_action_at is None:
        candidate = server_now
    else:
        try:
            candidate = normalize_to_naive_utc(client_action_at)
        except (TypeError, ValueError):
            candidate = server_now

    lower = session.start_time
    if floor is not None and floor > lower:
        lower = floor
    if candidate < lower:
        candidate = lower
    if candidate > server_now:
        candidate = server_now
    # If a floor is microscopically newer than server_now (possible when closing
    # an interval created in the immediately preceding request), prefer the floor
    # so CHECK ended_at > started_at remains true.
    if candidate < lower:
        candidate = lower
    return candidate


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
    # The database also enforces one active (running/paused) session per user.
    # Keep the service-level pre-check for a friendly error, but use a SAVEPOINT
    # around INSERT so a concurrent start that loses the unique-index race does
    # not poison the outer request transaction.
    try:
        async with db.begin_nested():
            db.add(session)
            await db.flush()
    except IntegrityError as exc:
        # Do not blanket-convert unrelated integrity failures into an active-session
        # conflict. After the SAVEPOINT rollback, verify that the partial unique
        # index race really produced an active row; otherwise preserve the original
        # database error for observability.
        conflict = await get_active_session(db, user_id)
        if conflict is not None:
            logger.info(
                "pomodoro start_session: active-session uniqueness race for user %s",
                user_id,
            )
            raise ValueError("当前已有进行中的专注，请先结束后再开始") from exc
        raise

    await db.refresh(session)
    # Populate subject_ref for post-commit serialization
    session.subject_ref = subj
    return session


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
            PomodoroSession.status.in_(["running", "paused", "completed"]),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    # Completion is idempotent. Mobile clients may retry after a timeout even when
    # the first request committed successfully; returning the existing completed
    # row prevents a false 404 and makes local pending-sync retries safe.
    if session.status == "completed":
        return session

    now = utcnow()
    action_time = _resolve_client_action_time(
        session, client_action_at, now, floor=_closing_action_floor(session)
    )

    # Close any open pause interval at the client event time (clamped to the
    # canonical timeline) so delayed offline completion does not absorb wait time.
    if session.paused_at is not None:
        _close_open_pause_interval(session, action_time)
        session.paused_at = None

    # actual_duration is computed entirely server-side from timestamps + intervals
    # (§14); the client never overrides it. Delayed mobile retries must not inflate
    # a finished countdown: a 25-minute timer completed offline and synchronized
    # five minutes later is still a 25-minute focus session.
    paused_sec = _effective_paused_sec(session, action_time)
    actual_duration = _server_actual_duration(session, action_time)
    effective_end = action_time
    if session.preset == "free":
        # Free timer is a product-level maximum of five active hours.
        actual_duration = min(actual_duration, FREE_TIMER_MAX_DURATION_SEC)
        if actual_duration >= FREE_TIMER_MAX_DURATION_SEC:
            effective_end = min(
                action_time,
                session.start_time + timedelta(seconds=paused_sec + FREE_TIMER_MAX_DURATION_SEC),
            )
    else:
        # /complete represents natural countdown completion; early user termination
        # goes through /interrupt. Cap both duration and end_time to the configured
        # work duration so a delayed retry cannot include the offline delay.
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
    session.total_paused_sec = paused_sec  # derived cache
    session.status = "completed"
    if not session.notification_sent:
        session.notification_sent = True
        session.notification_sent_at = now
        if not session.notification_error:
            session.notification_error = "skipped: user completed before scheduler"
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
            PomodoroSession.status.in_(["running", "paused", "interrupted"]),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    # Idempotent for mobile retries: if the first interrupt committed but its
    # response was lost, return the already-interrupted session instead of 404.
    if session.status == "interrupted":
        return session

    now = utcnow()
    action_time = _resolve_client_action_time(
        session, client_action_at, now, floor=_closing_action_floor(session)
    )

    if session.paused_at is not None:
        _close_open_pause_interval(session, action_time)
        session.paused_at = None

    paused_sec = _effective_paused_sec(session, action_time)
    actual_duration = _server_actual_duration(session, action_time)
    effective_end = action_time
    # Interrupts are also retryable from the client. Bound old-client / delayed
    # requests to the product's maximum active duration even when no
    # client_action_at is available; current clients send the exact local action
    # timestamp, so this is mainly a defensive ceiling.
    if session.preset == "free":
        actual_duration = min(actual_duration, FREE_TIMER_MAX_DURATION_SEC)
        if actual_duration >= FREE_TIMER_MAX_DURATION_SEC:
            effective_end = min(
                action_time,
                session.start_time + timedelta(seconds=paused_sec + FREE_TIMER_MAX_DURATION_SEC),
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
    session.total_paused_sec = paused_sec  # derived cache
    session.status = "interrupted"
    if not session.notification_sent:
        session.notification_sent = True
        session.notification_sent_at = now
        if not session.notification_error:
            session.notification_error = "skipped: user interrupted"
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
        # Row lock so two concurrent pause requests cannot both see status="running"
        # and each append an open pause interval.  ``of=PomodoroSession`` locks only
        # the sessions row — a bare FOR UPDATE would also lock the outer-joined
        # subjects side, which PostgreSQL rejects (FeatureNotSupportedError).
        .with_for_update(of=PomodoroSession)
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    # Idempotent: already paused, just return current session
    if session.status == "paused":
        await db.refresh(session)
        return session
    now = utcnow()
    action_time = _resolve_client_action_time(
        session, client_action_at, now, floor=_latest_session_event_time(session)
    )
    # Record the pause interval so attribution can subtract exactly where the
    # pause fell.  Defensive: never create a second open interval (covers engines
    # without SELECT FOR UPDATE, e.g. SQLite, and double-tap races).
    if not any(i.ended_at is None for i in session.pause_intervals):
        session.pause_intervals.append(
            PomodoroPauseInterval(session_id=session.id, started_at=action_time, ended_at=None)
        )
    session.paused_at = action_time
    session.status = "paused"
    # The partial unique index is the final guard: on SQLite the row lock above
    # is a no-op, so two concurrent pause requests can both pass the defensive
    # check and race it.  Treat the loser as an idempotent re-pause — roll back
    # to a savepoint and return the session as-is (the winner already recorded
    # the open interval).
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        logger.warning(
            "pomodoro pause_session: concurrent open pause interval for session %s; treating as idempotent",
            session.id,
        )
        session.pause_intervals[:] = [i for i in session.pause_intervals if i.id is not None]
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
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    now = utcnow()
    open_interval = next((i for i in session.pause_intervals if i.ended_at is None), None)
    floor = _latest_session_event_time(session)
    if open_interval is not None:
        floor = max(floor, open_interval.started_at + timedelta(microseconds=1))
    action_time = _resolve_client_action_time(session, client_action_at, now, floor=floor)

    # Close any stray open pause interval regardless of status, so a running
    # session carrying a leftover open interval (migration artifact / pause race)
    # is repaired on resume too instead of being left on the completed session.
    if any(i.ended_at is None for i in session.pause_intervals):
        _close_open_pause_interval(session, action_time)

    if session.status == "paused" and session.paused_at is not None:
        session.paused_at = None
        session.status = "running"

    # Recompute the derived cache and the countdown end from canonical data —
    # idempotent: repeated resumes never double-extend the countdown.
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

class _LiteSession:
    """Duck-typed session row for attribution; keeps ``pomodoro_attribution`` untouched.

    Exposes only the fields the stats aggregators touch — ``start_time`` /
    ``end_time`` / ``actual_duration`` / ``pause_intervals`` (list of
    ``SimpleNamespace(started_at, ended_at)``) — plus ``subject_id`` /
    ``subject_ref`` when the caller needs subject grouping.  No full ORM entity
    is materialised, so stats/trends never drag in the whole session row.
    """

    __slots__ = ("start_time", "end_time", "actual_duration", "subject_id", "subject_ref", "pause_intervals")

    def __init__(
        self,
        start_time: datetime,
        end_time: datetime | None,
        actual_duration: int | None,
        subject_id: int | None = None,
        subject_ref=None,
        pause_intervals: list | None = None,
    ):
        self.start_time = start_time
        self.end_time = end_time
        self.actual_duration = actual_duration
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
    """Load completed sessions overlapping the half-open range [period_start, period_end).

    Scenario-aware payload: ``with_subject=False`` (stats/trends) fetches only the
    attribution columns via one query plus one batched pause query (chunked IN, never
    an N+1); ``with_subject=True`` (daily-summary) additionally joins the subject.
    The window is always bounded (single user, overlapping a requested range) — never
    the user's full history.
    """
    overlap = (
        PomodoroSession.user_id == user_id,
        PomodoroSession.status == "completed",
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
            out.append(
                _LiteSession(
                    start_time=s.start_time,
                    end_time=s.end_time,
                    actual_duration=s.actual_duration,
                    subject_id=s.subject_id,
                    subject_ref=(
                        SimpleNamespace(code=ref.code or "", name=ref.name or "", is_active=ref.is_active)
                        if ref is not None
                        else None
                    ),
                    pause_intervals=[
                        SimpleNamespace(started_at=i.started_at, ended_at=i.ended_at)
                        for i in s.pause_intervals
                    ],
                )
            )
        return out

    result = await db.execute(
        select(
            PomodoroSession.id,
            PomodoroSession.start_time,
            PomodoroSession.end_time,
            PomodoroSession.actual_duration,
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
    """Load completed practice sessions overlapping the half-open range.

    Practice sessions never pause, so ``pause_intervals`` is empty; the row's
    wall clock ``[started_at, finished_at)`` is the raw learning window and
    ``duration_sec`` is the authoritative learning time.  ``duration_sec`` may
    be less than the wall span (foreground-only client timing subtracts
    background time), so attribution must scale exclusion proportionally
    (:func:`split_duration_excluding_intervals`), never by flat wall overlap.
    """
    overlap = (
        PracticeSession.user_id == user_id,
        PracticeSession.status == "completed",
        PracticeSession.started_at < period_end,
        PracticeSession.finished_at > period_start,
    )
    if with_subject:
        result = await db.execute(
            select(PracticeSession)
            .options(joinedload(PracticeSession.subject_ref))
            .where(*overlap)
        )
        out: list[_LiteSession] = []
        for s in result.scalars().all():
            ref = s.subject_ref
            out.append(
                _LiteSession(
                    start_time=s.started_at,
                    end_time=s.finished_at,
                    actual_duration=s.duration_sec,
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
                    pause_intervals=[],
                )
            )
        return out

    result = await db.execute(
        select(
            PracticeSession.started_at,
            PracticeSession.finished_at,
            PracticeSession.duration_sec,
        ).where(*overlap)
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


async def build_pomodoro_statistics_snapshot(
    db: AsyncSession,
    user_id: int,
    *,
    target_date: date | None = None,
    trends_days: int = 7,
    need_stats: bool = False,
    need_trends: bool = False,
    need_daily_summary: bool = False,
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
        trend_start, _ = study_day_utc_range(today - timedelta(days=trends_days - 1), dsm)
        _, trend_end = study_day_utc_range(today, dsm)
        ranges.append((trend_start, trend_end))
    if need_daily_summary:
        ranges.append(study_day_utc_range(target, dsm))

    if not ranges:
        return {}
    period_start = min(r[0] for r in ranges)
    period_end = max(r[1] for r in ranges)
    pomodoro_sessions = await _load_overlapping_sessions(
        db, user_id, period_start, period_end, with_subject=need_daily_summary
    )
    practice_sessions = await _load_overlapping_practice_sessions(
        db, user_id, period_start, period_end, with_subject=need_daily_summary
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
            today - timedelta(days=trends_days - 1 - i): {"sessions": 0, "duration_sec": 0}
            for i in range(trends_days)
        }
    if need_daily_summary:
        target_groups: dict[int | None, dict] = {}
        target_sessions = 0
        target_duration = 0

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
        if need_stats:
            if start_day == today:
                today_sessions += 1
            if week_start_date <= start_day < week_end_date:
                week_sessions += 1
            for day, sec in split.items():
                if day == today:
                    today_duration += sec
                if week_start_date <= day < week_end_date:
                    week_duration += sec
        if need_trends:
            if start_day in trend_agg:
                trend_agg[start_day]["sessions"] += 1
            for day, sec in split.items():
                if day in trend_agg:
                    trend_agg[day]["duration_sec"] += sec
        if need_daily_summary:
            day_contrib = split.get(target, 0)
            if day_contrib <= 0 and start_day != target:
                continue
            if start_day == target:
                target_sessions += 1
            target_duration += day_contrib
            if day_contrib <= 0:
                # 本日无时长贡献：仍计入总次数/总时长，但不生成 0% 科目切片
                continue
            key, code, name = _resolve_subject(s)
            g = target_groups.setdefault(key, {
                "subject_id": key, "subject_code": code, "subject_name": name,
                "duration_sec": 0, "sessions": 0,
            })
            g["duration_sec"] += day_contrib
            if start_day == target:
                g["sessions"] += 1

    # ── PracticeSession：仅补充时长（与 Pomodoro 重叠部分被排除）──
    # 顶层 sessions（stats/trends/daily_summary.sessions）保持番茄次数；
    # 科目级 subjects[].sessions 定义成"当天开始的该科目学习记录数"，含刷题，
    # 供前端跨统计日渗透判断使用（普通当天刷题不会被误判为渗透）。
    for s in practice_sessions:
        start_day = study_day_for_utc(s.start_time, dsm)
        split = split_duration_excluding_intervals(
            s.start_time, s.end_time, s.actual_duration, counted_spans, dsm,
        )
        if need_stats:
            for day, sec in split.items():
                if day == today:
                    today_duration += sec
                if week_start_date <= day < week_end_date:
                    week_duration += sec
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
            g = target_groups.setdefault(key, {
                "subject_id": key, "subject_code": code, "subject_name": name,
                "duration_sec": 0, "sessions": 0,
            })
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


async def get_history(
    db: AsyncSession, user_id: int, page: int = 1, page_size: int = 20,
    filter_date: date | None = None,
) -> tuple[list[dict], int]:
    """统计页统一学习记录 history — PomodoroSession + PracticeSession 混排。

    - 两种来源统一按 start_time DESC 排序后做全局 offset/limit（UNION 子查询），
      保证分页与 total 严格正确，不存在"两来源各自取 N 条再拼接"丢页问题。
    - 按 start_time / started_at 对应的统计日过滤（遵守用户 day_start_minute）。
    - 每条记录带唯一 record_key（``pomodoro:<id>`` / ``practice:<id>``）。
    """
    pomo_where = [
        PomodoroSession.user_id == user_id,
        ~PomodoroSession.status.in_(["running", "paused"]),
    ]
    practice_where = [
        PracticeSession.user_id == user_id,
        PracticeSession.status == "completed",
    ]
    if filter_date is not None:
        dsm = (await get_pomodoro_settings(db, user_id))["day_start_minute"]
        start_utc, end_utc = study_day_utc_range(filter_date, dsm)
        pomo_where.extend([
            PomodoroSession.start_time >= start_utc,
            PomodoroSession.start_time < end_utc,
        ])
        practice_where.extend([
            PracticeSession.started_at >= start_utc,
            PracticeSession.started_at < end_utc,
        ])

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

    merged = pomo_cols.union_all(practice_cols).subquery()

    total = (await db.execute(
        select(func.count()).select_from(merged)
    )).scalar() or 0

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
        items.append({
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
        })
    return items, total
