"""Production backfill: normalize legacy pomodoro sessions into the V2 canonical model.

For each legacy session (missing reconstructed pause data) this either:

* completed + no pause intervals + wall > actual  -> inserts ONE deterministically
  centered pause interval (wall - interval == actual exactly);
* completed + no pause intervals + actual > wall (<=2s rounding) -> clamps
  actual_duration to wall (zero pause) and records the repair;
* running/paused + no closed intervals + total_paused_sec > 0 -> inserts a closed
  interval for the past pause (centered in the elapsed window);
* paused + paused_at set + no open interval -> inserts the open interval at paused_at.

Invalid sessions (negative duration, missing end_time, actual > wall + 2s) are
skipped and reported; --repair-invalid opts into explicit repair.

Idempotent: every action is guarded by its precondition, so re-running changes 0
rows.  Each batch commits in its own transaction; a failure rolls back that batch
and aborts, leaving no half-applied batch.

Usage (dry-run is the default):
  python -m scripts.migrate_pomodoro_sessions_v2 --dry-run
  python -m scripts.migrate_pomodoro_sessions_v2 --user-id 12 --dry-run
  python -m scripts.migrate_pomodoro_sessions_v2 --apply --batch-size 200
  python -m scripts.migrate_pomodoro_sessions_v2 --apply --repair-invalid --report /tmp/pomo_migration.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.core.database import async_session
from app.core.time_utils import utcnow
from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
from app.services.pomodoro_normalization import (
    ACTION_CLAMP_ROUNDING,
    ACTION_CREATE_PAUSE,
    ACTION_INVALID,
    ACTION_REPAIR,
    active_past_pause_interval,
    normalize_completed,
)

logger = logging.getLogger("migrate_pomodoro_v2")

DEFAULT_BATCH_SIZE = 200


def _parse_cutoff(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise SystemExit(f"invalid --cutoff (use YYYY-MM-DDTHH:MM:SS UTC): {value}") from exc


def _as_dt(value) -> datetime | None:
    """Coerce a raw-SQL column value (str from SQLite, datetime elsewhere) to datetime."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace(" ", "T"))


async def _process_completed(
    db,
    *,
    apply: bool,
    batch_size: int,
    user_id: int | None,
    session_id: int | None,
    cutoff: datetime | None,
    repair_invalid: bool,
    limit: int,
) -> dict:
    counts = {
        "completed_processed": 0,
        "created_pause": 0,
        "clamped_rounding": 0,
        "repaired": 0,
        "invalid_skipped": 0,
    }
    filters = ["status = 'completed'",
               "NOT EXISTS (SELECT 1 FROM pomodoro_pause_intervals pi WHERE pi.session_id = pomodoro_sessions.id)"]
    params: dict = {}
    if user_id is not None:
        filters.append("user_id = :uid")
        params["uid"] = user_id
    if session_id is not None:
        filters.append("id = :sid")
        params["sid"] = session_id
    if cutoff is not None:
        filters.append("created_at < :cutoff")
        params["cutoff"] = cutoff
    where_sql = " AND ".join(filters)

    last_id = 0
    while True:
        rows = (await db.execute(text(
            f"""
            SELECT id, user_id, start_time, end_time, actual_duration
            FROM pomodoro_sessions
            WHERE {where_sql} AND id > :last_id
            ORDER BY id
            LIMIT :batch
            """
        ), {**params, "last_id": last_id, "batch": batch_size})).all()
        if not rows:
            break
        last_id = rows[-1][0]

        for r in rows:
            if limit and counts["completed_processed"] >= limit:
                return counts
            counts["completed_processed"] += 1
            sid, _uid, start, end, actual = r
            start_dt = _as_dt(start)
            assert start_dt is not None  # start_time is NOT NULL
            norm = normalize_completed(
                start_dt, _as_dt(end), actual, repair_invalid=repair_invalid
            )

            if norm.action == ACTION_CREATE_PAUSE and norm.interval is not None:
                counts["created_pause"] += 1
                if apply:
                    await db.execute(text(
                        "INSERT INTO pomodoro_pause_intervals (session_id, started_at, ended_at) "
                        "VALUES (:sid, :st, :en)"
                    ), {"sid": sid, "st": norm.interval[0], "en": norm.interval[1]})
            elif norm.action == ACTION_CLAMP_ROUNDING:
                counts["clamped_rounding"] += 1
                if apply:
                    await db.execute(text(
                        "UPDATE pomodoro_sessions SET actual_duration = :actual WHERE id = :sid"
                    ), {"actual": norm.corrected_actual, "sid": sid})
            elif norm.action == ACTION_REPAIR:
                counts["repaired"] += 1
                if apply:
                    if norm.corrected_actual is not None:
                        await db.execute(text(
                            "UPDATE pomodoro_sessions SET actual_duration = :actual WHERE id = :sid"
                        ), {"actual": norm.corrected_actual, "sid": sid})
                    if norm.interval is not None:
                        await db.execute(text(
                            "INSERT INTO pomodoro_pause_intervals (session_id, started_at, ended_at) "
                            "VALUES (:sid, :st, :en)"
                        ), {"sid": sid, "st": norm.interval[0], "en": norm.interval[1]})
            elif norm.action == ACTION_INVALID:
                counts["invalid_skipped"] += 1
                if counts["invalid_skipped"] <= 5:
                    logger.info("  skip invalid completed session id=%s", sid)

        if apply:
            await db.commit()
        else:
            await db.rollback()  # keep the connection clean for the next batch

    return counts


async def _process_active(
    db,
    *,
    apply: bool,
    batch_size: int,
    user_id: int | None,
    session_id: int | None,
    cutoff: datetime | None,
    limit: int,
    now: datetime,
) -> dict:
    counts = {"active_processed": 0, "active_past_pause": 0, "active_open_interval": 0}
    stmt = (
        select(PomodoroSession)
        .options(selectinload(PomodoroSession.pause_intervals))
        .where(PomodoroSession.status.in_(["running", "paused"]))
        .order_by(PomodoroSession.id)
    )
    if user_id is not None:
        stmt = stmt.where(PomodoroSession.user_id == user_id)
    if session_id is not None:
        stmt = stmt.where(PomodoroSession.id == session_id)
    if cutoff is not None:
        stmt = stmt.where(PomodoroSession.created_at < cutoff)

    offset = 0
    while True:
        if limit and counts["active_processed"] >= limit:
            break
        result = await db.execute(stmt.limit(batch_size).offset(offset))
        sessions = list(result.scalars().all())
        if not sessions:
            break
        offset += len(sessions)

        for s in sessions:
            if limit and counts["active_processed"] >= limit:
                return counts
            counts["active_processed"] += 1
            has_closed = any(i.ended_at is not None for i in s.pause_intervals)
            has_open = any(i.ended_at is None for i in s.pause_intervals)

            if not has_closed and (s.total_paused_sec or 0) > 0:
                iv = active_past_pause_interval(s.start_time, now, s.total_paused_sec or 0)
                if iv is not None:
                    counts["active_past_pause"] += 1
                    if apply:
                        db.add(PomodoroPauseInterval(session_id=s.id, started_at=iv[0], ended_at=iv[1]))

            if s.status == "paused" and s.paused_at is not None and not has_open:
                counts["active_open_interval"] += 1
                if apply:
                    db.add(PomodoroPauseInterval(session_id=s.id, started_at=s.paused_at, ended_at=None))

        if apply:
            await db.commit()
        else:
            await db.rollback()

    return counts


async def run_migration(
    *,
    apply: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    user_id: int | None = None,
    session_id: int | None = None,
    cutoff: datetime | None = None,
    repair_invalid: bool = False,
    limit: int = 0,
    report_path: str | None = None,
    session_factory=None,
) -> dict:
    factory = session_factory or async_session
    async with factory() as db:
        now = utcnow()
        logger.info("=== Pomodoro V2 backfill (%s) ===", "APPLY" if apply else "DRY-RUN")
        if cutoff:
            logger.info("cutoff (created_at <): %s", cutoff.isoformat())
        if user_id:
            logger.info("scoped to user_id: %s", user_id)
        if session_id:
            logger.info("scoped to session_id: %s", session_id)

        comp = await _process_completed(
            db, apply=apply, batch_size=batch_size, user_id=user_id,
            session_id=session_id, cutoff=cutoff, repair_invalid=repair_invalid, limit=limit,
        )
        if limit and comp["completed_processed"] >= limit:
            remaining = 0
        else:
            remaining = max(0, limit - comp["completed_processed"]) if limit else 0
        active = await _process_active(
            db, apply=apply, batch_size=batch_size, user_id=user_id,
            session_id=session_id, cutoff=cutoff, limit=remaining, now=now,
        )

        summary = {
            "mode": "apply" if apply else "dry-run",
            "timestamp": now.isoformat(),
            "completed_processed": comp["completed_processed"],
            "created_pause_intervals": comp["created_pause"],
            "clamped_rounding": comp["clamped_rounding"],
            "repaired": comp["repaired"],
            "invalid_skipped": comp["invalid_skipped"],
            "active_processed": active["active_processed"],
            "active_past_pause_intervals": active["active_past_pause"],
            "active_open_intervals": active["active_open_interval"],
            "total_rows_changed": comp["created_pause"] + comp["clamped_rounding"] + comp["repaired"]
            + active["active_past_pause"] + active["active_open_interval"],
        }
        logger.info("completed processed:      %d", comp["completed_processed"])
        logger.info("  pause intervals created:%d", comp["created_pause"])
        logger.info("  actual clamped (round): %d", comp["clamped_rounding"])
        logger.info("  explicit repairs:       %d", comp["repaired"])
        logger.info("  invalid skipped:        %d", comp["invalid_skipped"])
        logger.info("active (running/paused):  %d", active["active_processed"])
        logger.info("  past-pause intervals:   %d", active["active_past_pause"])
        logger.info("  open intervals created: %d", active["active_open_interval"])
        logger.info("total rows changed:       %d", summary["total_rows_changed"])
        if summary["invalid_skipped"]:
            logger.warning("invalid sessions skipped — run with --repair-invalid to auto-repair (after review)")
        if not apply:
            logger.info("dry-run: no writes made. Re-run with --apply to execute.")

        if report_path:
            with open(report_path, "w", encoding="utf-8") as fh:
                json.dump(summary, fh, ensure_ascii=False, indent=2)
            logger.info("report written to %s", report_path)
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill legacy pomodoro sessions to the V2 canonical model")
    parser.add_argument("--apply", action="store_true", help="execute writes")
    parser.add_argument("--dry-run", action="store_true", help="preview writes (default; overrides --apply)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--session-id", type=int, default=None)
    parser.add_argument("--cutoff", type=str, default=None, help="created_at cutoff (YYYY-MM-DDTHH:MM:SS UTC)")
    parser.add_argument("--repair-invalid", action="store_true", help="auto-repair invalid sessions")
    parser.add_argument("--limit", type=int, default=0, help="process at most N sessions (sampling)")
    parser.add_argument("--report", type=str, default=None, help="write JSON summary to this path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Dry-run is the default; --dry-run forces it even if --apply was passed.
    apply = args.apply and not args.dry_run
    asyncio.run(run_migration(
        apply=apply,
        batch_size=args.batch_size,
        user_id=args.user_id,
        session_id=args.session_id,
        cutoff=_parse_cutoff(args.cutoff),
        repair_invalid=args.repair_invalid,
        limit=args.limit,
        report_path=args.report,
    ))


if __name__ == "__main__":
    main()
