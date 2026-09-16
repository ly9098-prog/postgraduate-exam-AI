"""Duration attribution engine: split a completed session's actual_duration across
China study days.

Facts and statistics are separated — sessions never store a study date.  All
partitioning happens here, application-side, using the user's day_start_minute, so
historical stats immediately follow any day_start change.

Algorithms:

* Sessions with ``pomodoro_pause_intervals``: subtract the pause intervals from the
  wall clock ``[start_time, end_time)`` to obtain the real active intervals, then
  measure each interval's overlap with every study-day window.
* Sessions with no pause intervals: a zero-pause session — the whole wall clock is
  active, so the wall-clock overlap is exact.

Post-migration every completed session falls into exactly one of these two cases;
there is no legacy path.  In both cases the raw overlaps are used as weights and the
final integer seconds are assigned proportionally to ``actual_duration`` with a
largest-remainder pass, so ``sum(contribution_sec) == actual_duration`` always holds.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.core.time_utils import study_day_for_utc, study_day_utc_range

logger = logging.getLogger(__name__)


def _active_intervals(
    start: datetime,
    end: datetime,
    pause_intervals: list[tuple[datetime, datetime | None]],
) -> list[tuple[datetime, datetime]]:
    """Return merged active (non-paused) intervals within ``[start, end)``.

    Open pause intervals (``ended_at is None``) are clamped to ``end``.  Pause
    segments outside the session window are ignored.
    """
    pauses: list[tuple[datetime, datetime]] = []
    for p_start, p_end in pause_intervals:
        ps = max(start, p_start)
        pe = min(end, p_end) if p_end is not None else end
        if pe > ps:
            pauses.append((ps, pe))
    pauses.sort()

    merged: list[tuple[datetime, datetime]] = []
    for s, e in pauses:
        if merged and s < merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))

    active: list[tuple[datetime, datetime]] = []
    cursor = start
    for s, e in merged:
        if s > cursor:
            active.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < end:
        active.append((cursor, end))
    return active


def _raw_overlap_by_study_day(
    start: datetime,
    end: datetime,
    pause_intervals: list[tuple[datetime, datetime | None]],
    day_start_minute: int,
) -> dict[date, float]:
    """Wall-clock active seconds (float) per study day (as date keys) for [start, end).

    Fractions of a second are kept (not int()-floored) so a sub-second split across a
    study-day boundary still yields a nonzero weight for both days; integer seconds
    are produced only by :func:`_normalize`.
    """
    raw: dict[date, float] = {}
    for a_start, a_end in _active_intervals(start, end, pause_intervals):
        cursor = a_start
        day = study_day_for_utc(cursor, day_start_minute)
        while cursor < a_end:
            _, w_end = study_day_utc_range(day, day_start_minute)
            overlap_end = min(a_end, w_end)
            if overlap_end > cursor:
                raw[day] = raw.get(day, 0) + (overlap_end - cursor).total_seconds()
            day = day + timedelta(days=1)
            cursor = overlap_end
    return raw


def _normalize(
    raw_overlap: dict[date, float],
    actual_duration: int,
    start: datetime,
    day_start_minute: int,
) -> dict[date, int]:
    """Distribute ``actual_duration`` proportionally to ``raw_overlap``.

    Guarantees the contributions sum exactly to ``actual_duration`` (largest
    remainder, deterministic tie-break by earlier date).  Zero or degenerate raw
    overlap falls back to the session's start study day so no seconds are lost.
    """
    if not raw_overlap:
        # No active overlap (e.g. pauses cover the whole wall clock).  Fall back
        # to the start study day so no seconds are lost, but surface the anomaly
        # instead of silently attributing focus time that never happened.
        if actual_duration > 0:
            logger.warning(
                "pomodoro attribution: no active overlap for start=%s; attributing %ds to start study day",
                start,
                actual_duration,
            )
        return {study_day_for_utc(start, day_start_minute): actual_duration}
    if actual_duration <= 0:
        return {study_day_for_utc(start, day_start_minute): actual_duration}
    total_raw = sum(raw_overlap.values())
    if total_raw <= 0:
        logger.warning(
            "pomodoro attribution: raw overlap 0 for start=%s; attributing %ds to start study day",
            start,
            actual_duration,
        )
        return {study_day_for_utc(start, day_start_minute): actual_duration}

    days = sorted(raw_overlap)
    exact = {d: actual_duration * raw_overlap[d] / total_raw for d in days}
    floors = {d: int(exact[d]) for d in days}
    remainder = actual_duration - sum(floors.values())
    # Largest remainder; equal fractions break by earlier date (deterministic).
    order = sorted(days, key=lambda d: (-(exact[d] - floors[d]), d))
    for i in range(remainder):
        floors[order[i]] += 1
    return floors


def split_session_duration_by_study_day(
    session,
    pause_intervals,
    day_start_minute: int,
) -> dict[date, int]:
    """Return ``{study_day_date: contribution_sec}`` for a session.

    ``session`` exposes ``start_time``, ``end_time`` and ``actual_duration``.
    ``pause_intervals`` is an iterable of objects with ``started_at`` and
    ``ended_at`` (naive-UTC datetimes; ``ended_at`` may be ``None``).
    """
    start = session.start_time
    end = session.end_time or start
    actual_duration = max(0, int(session.actual_duration or 0))
    if end <= start:
        return {study_day_for_utc(start, day_start_minute): actual_duration}

    intervals = [
        (i.started_at, i.ended_at)
        for i in (pause_intervals or [])
        if getattr(i, "started_at", None) is not None
    ]
    raw = _raw_overlap_by_study_day(start, end, intervals, day_start_minute)
    return _normalize(raw, actual_duration, start, day_start_minute)


def split_session_duration_excluding_intervals(
    session,
    pause_intervals,
    excluded_intervals: list[tuple[datetime, datetime | None]],
    day_start_minute: int,
) -> dict[date, int]:
    """Attribute a pausable session after excluding already-counted wall spans.

    This is the pausable counterpart of :func:`split_duration_excluding_intervals`.
    The session's own pause intervals are removed first, then external intervals
    (for example practice/exam windows) remove only the remaining active wall time.
    ``actual_duration`` is scaled by the fraction of active wall time that remains,
    so a pause is never subtracted twice and the returned total never exceeds the
    persisted session duration.

    The function intentionally returns ``{}`` when all active focus time is covered
    by the external intervals.  Callers can therefore use the result as a pure
    supplement to another authoritative activity clock without double counting.
    """
    start = session.start_time
    end = session.end_time or start
    actual_duration = max(0, int(session.actual_duration or 0))
    if end <= start or actual_duration <= 0:
        return {}

    pauses = [
        (i.started_at, i.ended_at)
        for i in (pause_intervals or [])
        if getattr(i, "started_at", None) is not None
    ]
    active_raw = _raw_overlap_by_study_day(start, end, pauses, day_start_minute)
    active_raw_total = sum(active_raw.values())
    if active_raw_total <= 0:
        return {}

    combined_exclusions = pauses + [
        (s, e)
        for s, e in (excluded_intervals or [])
        if s is not None and e is not None and e > s
    ]
    uncovered_raw = _raw_overlap_by_study_day(
        start,
        end,
        combined_exclusions,
        day_start_minute,
    )
    uncovered_raw_total = sum(uncovered_raw.values())
    if uncovered_raw_total <= 0:
        return {}

    # Scale against *active* wall time (after the session's own pauses), not the
    # full wall span.  Otherwise a 25-minute active session with a 5-minute pause
    # would lose the pause twice when external exclusions are applied.
    effective_duration = int(
        actual_duration * min(1.0, uncovered_raw_total / active_raw_total)
    )
    if effective_duration <= 0:
        return {}
    return _normalize(
        uncovered_raw,
        effective_duration,
        start,
        day_start_minute,
    )


def active_intervals_for_session(session) -> list[tuple[datetime, datetime]]:
    """Merged active (non-paused) wall-clock intervals for a session.

    Reuses the same pause-subtraction logic as attribution, so the "already
    counted" pomodoro active time used to exclude overlapping practice time is
    exactly what pomodoro itself counts.
    """
    start = session.start_time
    end = session.end_time or start
    intervals = [
        (i.started_at, i.ended_at)
        for i in (session.pause_intervals or [])
        if getattr(i, "started_at", None) is not None
    ]
    return _active_intervals(start, end, intervals)


def split_duration_excluding_intervals(
    start: datetime,
    end: datetime,
    target_duration: int,
    excluded_intervals: list[tuple[datetime, datetime | None]],
    day_start_minute: int,
) -> dict[date, int]:
    """Attribute a session's ``target_duration`` across study days, excluding the
    wall-clock time already counted by ``excluded_intervals`` (merged — e.g.
    pomodoro active intervals, so overlapping practice time is not double
    counted).

    ``target_duration`` is distributed over the session's wall span and each
    day's non-excluded wall overlap keeps its proportional share, so no day
    boundary is lost and ``sum(contributions) <= target_duration`` always holds.

    Exclusion is proportional, not a flat wall-clock subtraction: when a session
    reports less study time than its wall span (``target_duration < wall_sec`` —
    e.g. a foreground-only duration), subtracting the raw wall overlap would
    over-exclude already-counted pomodoro time and undercount real practice.
    Scaling by ``non_excluded / wall`` instead never excludes more than the
    session's share of the overlapped window.  When ``target_duration ==
    wall_sec`` this reduces exactly to the flat subtraction.

    Returns ``{}`` when the whole window is excluded or ``target_duration <= 0``
    (fully overlapped practice contributes nothing — it does NOT fall back to
    the start study day like :func:`split_session_duration_by_study_day`).
    """
    raw = _raw_overlap_by_study_day(start, end, excluded_intervals, day_start_minute)
    if not raw or (target_duration or 0) <= 0:
        return {}
    wall_sec = max(0, int((end - start).total_seconds()))
    if wall_sec <= 0:
        return {}
    non_excluded_raw = sum(raw.values())
    if non_excluded_raw <= 0:
        return {}
    # Effective total = the session's share of the non-excluded window.  Floor it
    # once, then a largest-remainder pass distributes only the rounding fraction
    # (never the proportional loss), so ``sum(contributions) <= target_duration``.
    effective = target_duration * non_excluded_raw / wall_sec
    eff_int = int(effective)
    days = sorted(raw)
    exact = {d: eff_int * raw[d] / non_excluded_raw for d in days}
    floors = {d: int(exact[d]) for d in days}
    remainder = eff_int - sum(floors.values())
    order = sorted(days, key=lambda d: (-(exact[d] - floors[d]), d))
    for i in range(remainder):
        floors[order[i]] += 1
    return {d: floors[d] for d in days if floors[d] > 0}
