"""Deterministic normalization of legacy pomodoro sessions into the V2 canonical model.

Before this one-time migration, historical sessions recorded only
``start_time`` / ``end_time`` / ``actual_duration`` (plus a possibly-drifting
``total_paused_sec`` cache).  Exact pause positions were unavailable, so the
pause intervals produced here are *reconstructed*, not historical facts.  The
reconstruction is deterministic and centered on the wall clock so it does not
systematically bias cross-study-day statistics.

Product-accepted trade-off (documented in docs/pomodoro_v2_migration.md):

    Exact historical pause positions were unavailable.  Historical sessions were
    deterministically normalized while preserving actual_duration.  Post-migration
    sessions contain precise server-recorded pause intervals.

After the migration the runtime never needs to know a pause interval was
reconstructed — canonical sessions are indistinguishable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# Completed-session anomaly thresholds (spec §10): actual_duration exceeding the
# wall clock by up to this many seconds is treated as historical rounding.
ROUNDING_TOLERANCE_SEC = 2

ACTION_NOOP = "noop"                    # already canonical, nothing to change
ACTION_CREATE_PAUSE = "create_pause"    # reconstruct one centered pause interval
ACTION_CLAMP_ROUNDING = "clamp_rounding"  # actual > wall (<=2s): clamp to wall, no pause
ACTION_REPAIR = "repair"                # explicit --repair-invalid handling
ACTION_INVALID = "invalid"              # invalid data: skipped unless --repair-invalid


@dataclass(frozen=True)
class Normalization:
    """Outcome of normalizing one legacy session.

    ``interval`` is the ``(started_at, ended_at)`` pause interval to insert
    (closed, so it is always safe to insert).  ``corrected_actual`` is a new
    ``actual_duration`` value the session must be updated to (None = keep).
    """

    action: str
    interval: tuple[datetime, datetime] | None = None
    corrected_actual: int | None = None


def centered_pause_interval(start: datetime, end: datetime, actual_duration: int) -> tuple[datetime, datetime]:
    """Reconstruct the pause as a single interval centered on the active timeline.

    Places ``wall - actual`` seconds starting at ``start + floor(actual/2)`` so that
    ``wall_sec - interval_duration == actual_duration`` holds exactly (deterministic,
    integer seconds).  The interval always fits inside ``[start, end]``.
    """
    wall = max(0, int((end - start).total_seconds()))
    pause_sec = max(0, wall - actual_duration)
    mid = start + timedelta(seconds=actual_duration // 2)
    return mid, mid + timedelta(seconds=pause_sec)


def normalize_completed(
    start: datetime,
    end: datetime | None,
    actual_duration: int | None,
    repair_invalid: bool = False,
) -> Normalization:
    """Decide how to normalize one legacy completed session.

    ``actual_duration`` is preserved unless it is provably inconsistent with the
    wall clock (rounding <= ``ROUNDING_TOLERANCE_SEC`` is auto-clamped; larger
    anomalies and negative durations are ``ACTION_INVALID`` unless
    ``repair_invalid`` opts into ``ACTION_REPAIR``).
    """
    if start is None or end is None or actual_duration is None:
        # Missing end_time / actual_duration: cannot normalize without the facts.
        return Normalization(ACTION_INVALID)

    wall = int((end - start).total_seconds())
    if wall < 0:
        return Normalization(ACTION_INVALID)

    if actual_duration < 0:
        if not repair_invalid:
            return Normalization(ACTION_INVALID)
        # Repair: 0 active time -> the whole wall clock is one pause interval.
        return Normalization(ACTION_REPAIR, interval=(start, end), corrected_actual=0)

    if actual_duration > wall:
        diff = actual_duration - wall
        if diff <= ROUNDING_TOLERANCE_SEC:
            # Historical rounding: canonical actual == wall, zero pause.
            return Normalization(ACTION_CLAMP_ROUNDING, corrected_actual=wall)
        if not repair_invalid:
            return Normalization(ACTION_INVALID)
        return Normalization(ACTION_REPAIR, corrected_actual=wall)

    pause_sec = wall - actual_duration
    if pause_sec <= 0:
        return Normalization(ACTION_NOOP)

    return Normalization(ACTION_CREATE_PAUSE, interval=centered_pause_interval(start, end, actual_duration))


def active_past_pause_interval(
    start: datetime,
    now: datetime,
    total_paused_sec: int,
) -> tuple[datetime, datetime] | None:
    """Reconstruct a closed interval for a still-active session's past pauses.

    ``total_paused_sec`` (the accumulated cache at resume points) is the only truth
    available for a session whose end is unknown.  The interval is centered in the
    elapsed window so far; ``wall - interval == actual`` then holds exactly when the
    session completes.  Returns None when there is nothing to reconstruct.
    """
    if total_paused_sec <= 0:
        return None
    elapsed = int((now - start).total_seconds())
    if elapsed <= 0:
        # Nothing to center an interval in (clock skew / future start); skip.
        return None
    pause = min(total_paused_sec, elapsed)  # clamp impossible pause > elapsed
    mid = start + timedelta(seconds=max(0, elapsed - pause) // 2)
    return mid, mid + timedelta(seconds=pause)
