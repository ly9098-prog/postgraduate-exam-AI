"""Post-migration verifier for the pomodoro V2 canonical model.

Checks every completed session satisfies the canonical invariants (§9):

  1. start_time <= end_time
  2. every pause interval: started_at < ended_at (and closed for completed sessions)
  3. every pause interval lies within [start_time, end_time]
  4. a session's pause intervals do not overlap
  5. abs(wall_duration - pause_duration - actual_duration) <= 1 second
  6. no completed session still requires the legacy fallback (a completed session
     whose pause is not fully explained by its intervals)

Plus the paused-session invariant (§13): status == "paused" implies exactly one
open pause interval.

Exits non-zero when any invariant fails, so a production release pipeline can gate
deployment on a clean run.

Usage:
  python -m scripts.verify_pomodoro_v2_migration [--strict]
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import async_session
from app.models.pomodoro import PomodoroSession

logger = logging.getLogger("verify_pomodoro_v2")

TOLERANCE_SEC = 1  # invariant 5


async def _check_completed(db, failures: dict[str, list[int]], samples: int) -> None:
    last_id = 0
    while True:
        result = await db.execute(
            select(PomodoroSession)
            .options(selectinload(PomodoroSession.pause_intervals))
            .where(PomodoroSession.status == "completed", PomodoroSession.id > last_id)
            .order_by(PomodoroSession.id)
            .limit(2000)
        )
        sessions = list(result.scalars().all())
        if not sessions:
            break
        last_id = sessions[-1].id

        for s in sessions:
            sid = s.id
            start, end = s.start_time, s.end_time
            actual = s.actual_duration
            intervals = sorted(
                [(i.started_at, i.ended_at) for i in s.pause_intervals if i.started_at is not None],
                key=lambda iv: iv[0],
            )

            # 1. start <= end
            if end is None or start is None or end < start:
                _record(failures, "start_gt_end", sid, samples)
                continue
            wall = int((end - start).total_seconds())

            # 2 + 3: each interval valid & inside window
            pause_sum = 0
            valid = True
            for iv_start, iv_end in intervals:
                if iv_end is None:  # open interval on a completed session = anomaly
                    _record(failures, "open_interval_on_completed", sid, samples)
                    valid = False
                    continue
                if iv_end <= iv_start:
                    _record(failures, "pause_not_increasing", sid, samples)
                    valid = False
                    continue
                if iv_start < start or iv_end > end:
                    _record(failures, "pause_outside_window", sid, samples)
                    valid = False
                    continue
                pause_sum += int((iv_end - iv_start).total_seconds())

            # 4. no overlap (intervals sorted by start)
            for i in range(1, len(intervals)):
                if intervals[i - 1][1] is not None and intervals[i][0] < intervals[i - 1][1]:
                    _record(failures, "pause_overlap", sid, samples)
                    break

            if not valid:
                continue

            # 5. wall - pause - actual within tolerance
            if abs(wall - pause_sum - (actual or 0)) > TOLERANCE_SEC:
                _record(failures, "wall_pause_actual_mismatch", sid, samples)

            # 6. no legacy fallback needed: pause must be explained by intervals
            if (wall - (actual or 0)) > TOLERANCE_SEC and not intervals:
                _record(failures, "needs_legacy_fallback", sid, samples)


async def _check_paused(db, failures: dict[str, list[int]], samples: int) -> None:
    result = await db.execute(
        select(PomodoroSession)
        .options(selectinload(PomodoroSession.pause_intervals))
        .where(PomodoroSession.status == "paused")
    )
    for s in result.scalars().all():
        open_count = sum(1 for i in s.pause_intervals if i.ended_at is None)
        if open_count != 1:
            _record(failures, "paused_open_interval", s.id, samples)


def _record(failures: dict[str, list[int]], key: str, sid: int, samples: int) -> None:
    if len(failures[key]) < samples:
        failures[key].append(sid)


async def verify(samples: int = 5, session_factory=None) -> bool:
    failures: dict[str, list[int]] = {
        "start_gt_end": [],
        "open_interval_on_completed": [],
        "pause_not_increasing": [],
        "pause_outside_window": [],
        "pause_overlap": [],
        "wall_pause_actual_mismatch": [],
        "needs_legacy_fallback": [],
        "paused_open_interval": [],
    }
    factory = session_factory or async_session
    async with factory() as db:
        await _check_completed(db, failures, samples)
        await _check_paused(db, failures, samples)

    total = sum(len(v) for v in failures.values())
    logger.info("=== Pomodoro V2 migration verification ===")
    if total == 0:
        logger.info("ALL canonical invariants hold for completed + paused sessions.")
        return True
    for key, label in (
        ("start_gt_end", "1. start_time <= end_time"),
        ("open_interval_on_completed", "2. completed sessions have no open interval"),
        ("pause_not_increasing", "2. started_at < ended_at"),
        ("pause_outside_window", "3. pause inside [start, end]"),
        ("pause_overlap", "4. pauses do not overlap"),
        ("wall_pause_actual_mismatch", "5. wall - pause - actual <= 1s"),
        ("needs_legacy_fallback", "6. no session needs legacy fallback"),
        ("paused_open_interval", "paused -> exactly one open interval"),
    ):
        ids = failures[key]
        if ids:
            logger.error("  FAIL %-32s %d  sample ids: %s", label, len(ids), ids)
    logger.error("TOTAL VIOLATIONS: %d", total)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify pomodoro V2 canonical invariants")
    parser.add_argument("--sample-size", type=int, default=5)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ok = asyncio.run(verify(samples=args.sample_size))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
