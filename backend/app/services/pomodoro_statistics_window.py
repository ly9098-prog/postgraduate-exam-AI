"""Compute one bounded load window while preserving requested-dimension order."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

DateRange = tuple[datetime, datetime]


@dataclass(frozen=True, slots=True)
class StatisticsWindowRequest:
    day_start_minute: int
    today: date
    target: date
    trends_days: int
    need_stats: bool
    need_trends: bool
    need_daily_summary: bool
    range_start: date | None
    range_end: date | None
    need_range_summary: bool


def requested_statistics_period(
    request: StatisticsWindowRequest,
    *,
    day_range: Callable[[date, int], DateRange],
    week_range: Callable[[int], DateRange],
) -> DateRange | None:
    """Resolve dimension ranges in order without loading or attributing sessions."""
    dsm = request.day_start_minute
    ranges: list[DateRange] = []
    if request.need_stats:
        today_start, today_end = day_range(request.today, dsm)
        week_start, week_end = week_range(dsm)
        ranges.append((min(today_start, week_start), max(today_end, week_end)))
    if request.need_trends:
        trend_start, _ = day_range(
            request.today - timedelta(days=request.trends_days - 1), dsm
        )
        _, trend_end = day_range(request.today, dsm)
        ranges.append((trend_start, trend_end))
    if request.need_daily_summary:
        ranges.append(day_range(request.target, dsm))
    if request.need_range_summary:
        if request.range_start is None or request.range_end is None:
            raise ValueError("range_start and range_end are required for range summary")
        if request.range_end < request.range_start:
            raise ValueError("range_end must be on or after range_start")
        range_period_start, _ = day_range(request.range_start, dsm)
        _, range_period_end = day_range(request.range_end, dsm)
        ranges.append((range_period_start, range_period_end))
    if not ranges:
        return None
    return min(r[0] for r in ranges), max(r[1] for r in ranges)
