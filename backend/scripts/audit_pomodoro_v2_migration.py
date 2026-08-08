"""Audit historical pomodoro data against the V2 canonical model (READ-ONLY).

Counts every pomodoro session by how it would be treated by the V2 backfill so the
operator can review the migration before applying it.  Never writes to the database
and never dumps private content — anomaly categories print a count plus a few
sample session ids.

Usage:
  python -m scripts.audit_pomodoro_v2_migration [--sample-size N]

Exit code 0 always (informational).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime

from sqlalchemy import text

from app.core.database import async_session
from app.services.pomodoro_normalization import (
    ACTION_CLAMP_ROUNDING,
    ACTION_CREATE_PAUSE,
    ACTION_INVALID,
    ACTION_NOOP,
    normalize_completed,
)

logger = logging.getLogger("audit_pomodoro_v2")


def _as_dt(value) -> datetime | None:
    """Coerce a raw-SQL column value (str from SQLite, datetime elsewhere) to datetime."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace(" ", "T"))


def _classify(has_intervals: bool, start, end, actual, total_paused_sec):
    """Return (primary, secondary) audit categories for a completed session row."""
    if has_intervals:
        return "already_canonical", None
    start_dt, end_dt = _as_dt(start), _as_dt(end)
    assert start_dt is not None  # start_time is NOT NULL
    norm = normalize_completed(start_dt, end_dt, actual)
    action = norm.action
    if action in (ACTION_NOOP, ACTION_CLAMP_ROUNDING):
        secondary = "actual_gt_wall" if action == ACTION_CLAMP_ROUNDING else None
        # zero-pause: no interval needed (rounding clamp still needs a repair write)
        return "requiring_zero_pause", secondary
    if action == ACTION_CREATE_PAUSE:
        return "requiring_reconstructed_pause", None
    if action == ACTION_INVALID:
        secondary = None
        if actual is None or end_dt is None:
            secondary = "missing_end_time" if end_dt is None else "missing_actual_duration"
        elif actual < 0:
            secondary = "negative_duration"
        elif end_dt is not None and start_dt is not None and end_dt < start_dt:
            secondary = "end_before_start"
        elif actual is not None and end_dt is not None and start_dt is not None and actual > max(0, int((end_dt - start_dt).total_seconds())):
            secondary = "actual_gt_wall"
        return "invalid", secondary
    return "requiring_reconstructed_pause", None


async def audit(sample_size: int = 5, session_factory=None) -> None:
    factory = session_factory or async_session
    async with factory() as db:
        totals = {
            "total_sessions": 0,
            "completed_sessions": 0,
            "running_sessions": 0,
            "paused_sessions": 0,
            "interrupted_sessions": 0,
            "sessions_with_pause_intervals": 0,
        }
        cat = {  # completed-session classification buckets
            "already_canonical": 0,
            "requiring_reconstruction": 0,
            "requiring_zero_pause": 0,
            "requiring_reconstructed_pause": 0,
            "invalid": 0,
        }
        anomalies = {  # secondary anomaly counters
            "actual_gt_wall": 0,
            "negative_duration": 0,
            "missing_end_time": 0,
            "missing_actual_duration": 0,
            "end_before_start": 0,
            "total_paused_mismatch": 0,
        }
        samples: dict[str, list[int]] = {k: [] for k in (*cat, *anomalies)}

        total = (await db.execute(text("SELECT COUNT(*) FROM pomodoro_sessions"))).scalar() or 0
        totals["total_sessions"] = total
        for status, key in (("completed", "completed_sessions"), ("running", "running_sessions"),
                            ("paused", "paused_sessions"), ("interrupted", "interrupted_sessions")):
            totals[key] = (await db.execute(
                text("SELECT COUNT(*) FROM pomodoro_sessions WHERE status = :s"), {"s": status}
            )).scalar() or 0
        totals["sessions_with_pause_intervals"] = (await db.execute(
            text("SELECT COUNT(DISTINCT session_id) FROM pomodoro_pause_intervals")
        )).scalar() or 0

        # Scan completed sessions with an interval-existence flag (paginated).
        last_id = 0
        while True:
            rows = (await db.execute(text(
                """
                SELECT s.id, s.start_time, s.end_time, s.actual_duration, s.total_paused_sec,
                       EXISTS(SELECT 1 FROM pomodoro_pause_intervals pi
                              WHERE pi.session_id = s.id) AS has_intervals
                FROM pomodoro_sessions s
                WHERE s.status = 'completed' AND s.id > :last_id
                ORDER BY s.id
                LIMIT :batch
                """
            ), {"last_id": last_id, "batch": 2000})).all()
            if not rows:
                break
            last_id = rows[-1][0]
            for r in rows:
                sid, start, end, actual, total_paused_sec, has_intervals = r
                primary, secondary = _classify(has_intervals, start, end, actual, total_paused_sec)

                if primary == "already_canonical":
                    cat["already_canonical"] += 1
                elif primary in ("requiring_zero_pause", "requiring_reconstructed_pause"):
                    cat["requiring_reconstruction"] += 1
                    cat[primary] += 1
                elif primary == "invalid":
                    cat["invalid"] += 1

                if secondary and len(samples[secondary]) < sample_size:
                    samples[secondary].append(sid)
                if primary == "invalid" and len(samples["invalid"]) < sample_size:
                    samples["invalid"].append(sid)

                # total_paused_sec vs wall - actual consistency check (§4)
                end_dt, start_dt = _as_dt(end), _as_dt(start)
                if end_dt is not None and start_dt is not None and actual is not None:
                    wall = int((end_dt - start_dt).total_seconds())
                    if abs((total_paused_sec or 0) - (wall - actual)) > 5:
                        anomalies["total_paused_mismatch"] += 1
                        if len(samples["total_paused_mismatch"]) < sample_size:
                            samples["total_paused_mismatch"].append(sid)
                if secondary:
                    anomalies[secondary] += 1

        logger.info("=== Pomodoro V2 migration audit (read-only) ===")
        logger.info("total sessions:              %d", totals["total_sessions"])
        logger.info("completed sessions:          %d", totals["completed_sessions"])
        logger.info("  running sessions:          %d", totals["running_sessions"])
        logger.info("  paused sessions:           %d", totals["paused_sessions"])
        logger.info("  interrupted sessions:      %d", totals["interrupted_sessions"])
        logger.info("sessions with pause data:    %d", totals["sessions_with_pause_intervals"])
        logger.info("")
        logger.info("Completed sessions by treatment:")
        logger.info("  already canonical:         %d", cat["already_canonical"])
        logger.info("  require reconstruction:    %d", cat["requiring_reconstruction"])
        logger.info("    requiring zero pause:    %d", cat["requiring_zero_pause"])
        logger.info("    requiring pause interval:%d", cat["requiring_reconstructed_pause"])
        logger.info("  invalid:                   %d", cat["invalid"])
        logger.info("")
        logger.info("Anomalies:")
        for key, label in (
            ("actual_gt_wall", "actual_duration > wall_duration"),
            ("negative_duration", "negative duration"),
            ("missing_end_time", "missing end_time"),
            ("missing_actual_duration", "missing actual_duration"),
            ("end_before_start", "end_time < start_time"),
            ("total_paused_mismatch", "total_paused_sec mismatch (>5s)"),
        ):
            count = anomalies[key]
            if count:
                logger.info("  %-28s %d  sample ids: %s", label, count, samples[key])
            else:
                logger.info("  %-28s 0", label)
        logger.info("")
        logger.info("Reconstructed pauses are deterministic approximations; actual_duration is preserved.")
        logger.info("Run scripts.migrate_pomodoro_sessions_v2 --dry-run to preview writes.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit pomodoro data against the V2 canonical model")
    parser.add_argument("--sample-size", type=int, default=5, help="max sample session ids per anomaly")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(audit(sample_size=args.sample_size))


if __name__ == "__main__":
    main()
