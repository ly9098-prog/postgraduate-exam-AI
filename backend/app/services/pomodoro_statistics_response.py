"""Map accumulated focus statistics into their stable public response shapes."""

from datetime import date
from typing import Any


def _subject_rows(groups: dict[Any, dict]) -> list[dict]:
    rows = [
        {
            "subject_id": group["subject_id"],
            "subject_code": group["subject_code"],
            "subject_name": group["subject_name"],
            "sessions": group["sessions"],
            "participation_sessions": group["participation_sessions"],
            "duration_sec": group["duration_sec"],
        }
        for group in groups.values()
    ]
    rows.sort(key=lambda row: row["duration_sec"], reverse=True)
    return rows


def _daily_response(
    target: date, day_start_minute: int, day_start_time: str, values: dict[str, Any]
) -> dict:
    return {
        "date": target.isoformat(),
        "timezone": "Asia/Shanghai",
        "day_start_minute": day_start_minute,
        "day_start_time": day_start_time,
        "sessions": values["sessions"],
        "duration_sec": values["duration_sec"],
        "subjects": _subject_rows(values["groups"]),
    }


def _range_response(
    day_start_minute: int, day_start_time: str, values: dict[str, Any]
) -> dict:
    return {
        "start_date": values["start_date"].isoformat(),
        "end_date": values["end_date"].isoformat(),
        "timezone": "Asia/Shanghai",
        "day_start_minute": day_start_minute,
        "day_start_time": day_start_time,
        "sessions": values["sessions"],
        "duration_sec": values["duration_sec"],
        "active_days": values["active_days"],
        "subjects": _subject_rows(values["groups"]),
    }


def build_statistics_response(
    *,
    need_stats: bool,
    need_trends: bool,
    need_daily_summary: bool,
    need_range_summary: bool,
    today: date,
    week_start_date: date,
    target: date,
    day_start_minute: int,
    day_start_time: str,
    trends: dict[date, dict] | None,
    stats_values: dict[str, int],
    daily_values: dict[str, Any],
    range_values: dict[str, Any],
) -> dict:
    """Build only requested public dimensions without touching database state."""
    response: dict[str, Any] = {}
    if need_stats:
        response["stats"] = {
            "today_sessions": stats_values["today_sessions"],
            "today_duration_sec": stats_values["today_duration"],
            "week_sessions": stats_values["week_sessions"],
            "week_duration_sec": stats_values["week_duration"],
            "today_date": today.isoformat(),
            "week_start_date": week_start_date.isoformat(),
            "day_start_minute": day_start_minute,
            "day_start_time": day_start_time,
        }
    if need_trends:
        response["trends"] = [
            {
                "date": day.isoformat(),
                "sessions": trends[day]["sessions"],
                "duration_sec": trends[day]["duration_sec"],
            }
            for day in sorted(trends)
        ]
    if need_daily_summary:
        response["daily_summary"] = _daily_response(
            target, day_start_minute, day_start_time, daily_values
        )
    if need_range_summary:
        response["range_summary"] = _range_response(
            day_start_minute, day_start_time, range_values
        )
    return response
