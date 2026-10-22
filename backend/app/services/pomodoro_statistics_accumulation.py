"""Accumulate focus and supplemental activity into caller-owned statistic state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class StatisticsAccumulationState:
    need_stats: bool
    need_trends: bool
    need_daily_summary: bool
    need_range_summary: bool
    range_include_subjects: bool
    today: date
    target: date
    range_start: date | None
    range_end: date | None
    week_start_date: date
    week_end_date: date
    trends: dict[date, dict[str, int]]
    stats: dict[str, int]
    daily: dict[str, Any]
    range: dict[str, Any]
    counted_spans: list[tuple[datetime, datetime]] = field(default_factory=list)


def _subject_group(subject_id, code, name) -> dict:
    return {
        "subject_id": subject_id,
        "subject_code": code,
        "subject_name": name,
        "duration_sec": 0,
        "sessions": 0,
        "participation_sessions": 0,
    }


def _add_range_duration(state, day, seconds):
    if state.range_start <= day <= state.range_end:
        state.range["duration_sec"] += seconds
        if seconds > 0:
            state.range["active_days_set"].add(day)
        return True
    return False


def _add_focus_range(
    state, session, start_day, split, is_terminal, resolve, key, allocate
):
    if is_terminal and state.range_start <= start_day <= state.range_end:
        state.range["sessions"] += 1
    contribution = 0
    for day, seconds in split.items():
        if _add_range_duration(state, day, seconds):
            contribution += seconds
    if not state.range_include_subjects or contribution <= 0:
        return
    allocations = resolve(session)
    by_subject = {key(row[0], row[1]): 0 for row in allocations}
    for day, seconds in split.items():
        if state.range_start <= day <= state.range_end:
            for row, allocated in zip(allocations, allocate(seconds, allocations)):
                by_subject[key(row[0], row[1])] += allocated
    for subject_id, code, name, _ in allocations:
        group_key = key(subject_id, code)
        group = state.range["groups"].setdefault(
            group_key, _subject_group(subject_id, code, name)
        )
        group["duration_sec"] += by_subject[group_key]
        if is_terminal and state.range_start <= start_day <= state.range_end:
            group["sessions"] += 1
            group["participation_sessions"] += 1


def accumulate_focus_sessions(
    sessions,
    state: StatisticsAccumulationState,
    *,
    day_start_minute: int,
    terminal_statuses,
    active_intervals,
    split_by_day,
    study_day_for_utc,
    resolve_allocations,
    allocation_group_key,
    allocate_seconds,
) -> None:
    """Apply terminal focus sessions before supplemental practice/review time."""
    for session in sessions:
        state.counted_spans.extend(active_intervals(session))
        start_day = study_day_for_utc(session.start_time, day_start_minute)
        split = split_by_day(session, session.pause_intervals, day_start_minute)
        terminal = session.status in terminal_statuses
        _accumulate_focus_dimensions(
            session,
            state,
            start_day,
            split,
            terminal,
            resolve_allocations,
            allocation_group_key,
            allocate_seconds,
        )


def _accumulate_focus_dimensions(
    session, state, start_day, split, terminal, resolve_allocations, key, allocate
):
    if state.need_stats:
        if terminal and start_day == state.today:
            state.stats["today_sessions"] += 1
        if terminal and state.week_start_date <= start_day < state.week_end_date:
            state.stats["week_sessions"] += 1
        for day, seconds in split.items():
            if day == state.today:
                state.stats["today_duration"] += seconds
            if state.week_start_date <= day < state.week_end_date:
                state.stats["week_duration"] += seconds
    if state.need_range_summary:
        _add_focus_range(
            state,
            session,
            start_day,
            split,
            terminal,
            resolve_allocations,
            key,
            allocate,
        )
    if state.need_trends:
        if terminal and start_day in state.trends:
            state.trends[start_day]["sessions"] += 1
        for day, seconds in split.items():
            if day in state.trends:
                state.trends[day]["duration_sec"] += seconds
    if state.need_daily_summary:
        _add_focus_daily(
            state,
            session,
            start_day,
            split,
            terminal,
            resolve_allocations,
            key,
            allocate,
        )


def _add_focus_daily(
    state,
    session,
    start_day,
    split,
    terminal,
    resolve_allocations,
    allocation_group_key,
    allocate_seconds,
):
    contribution = split.get(state.target, 0)
    if contribution <= 0 and start_day != state.target:
        return
    if terminal and start_day == state.target:
        state.daily["sessions"] += 1
    state.daily["duration_sec"] += contribution
    if contribution <= 0:
        return
    allocations = resolve_allocations(session)
    seconds = allocate_seconds(contribution, allocations)
    for (subject_id, code, name, _), allocated in zip(allocations, seconds):
        group_key = allocation_group_key(subject_id, code)
        group = state.daily["groups"].setdefault(
            group_key, _subject_group(subject_id, code, name)
        )
        group["duration_sec"] += allocated
        if terminal and start_day == state.target:
            group["sessions"] += 1
            group["participation_sessions"] += 1


def accumulate_supplemental_sessions(
    sessions,
    state: StatisticsAccumulationState,
    *,
    day_start_minute: int,
    split_excluding,
    study_day_for_utc,
    resolve_subject,
) -> None:
    """Add practice/review duration after excluding already-counted focus spans."""
    for session in sessions:
        start_day = study_day_for_utc(session.start_time, day_start_minute)
        split = split_excluding(
            session.start_time,
            session.end_time,
            session.actual_duration,
            state.counted_spans,
            day_start_minute,
        )
        if state.need_stats:
            for day, seconds in split.items():
                if day == state.today:
                    state.stats["today_duration"] += seconds
                if state.week_start_date <= day < state.week_end_date:
                    state.stats["week_duration"] += seconds
        if state.need_range_summary:
            _add_supplemental_range(state, session, start_day, split, resolve_subject)
        if state.need_trends:
            for day, seconds in split.items():
                if day in state.trends:
                    state.trends[day]["duration_sec"] += seconds
        if state.need_daily_summary:
            _add_supplemental_daily(state, session, start_day, split, resolve_subject)


def _add_supplemental_range(state, session, start_day, split, resolve_subject):
    contribution = 0
    for day, seconds in split.items():
        if _add_range_duration(state, day, seconds):
            contribution += seconds
    if not state.range_include_subjects or contribution <= 0:
        return
    key, code, name = resolve_subject(session)
    group = state.range["groups"].setdefault(key, _subject_group(key, code, name))
    group["duration_sec"] += contribution
    if state.range_start <= start_day <= state.range_end:
        group["sessions"] += 1


def _add_supplemental_daily(state, session, start_day, split, resolve_subject):
    contribution = split.get(state.target, 0)
    if contribution <= 0:
        return
    state.daily["duration_sec"] += contribution
    key, code, name = resolve_subject(session)
    group = state.daily["groups"].setdefault(key, _subject_group(key, code, name))
    group["duration_sec"] += contribution
    if start_day == state.target:
        group["sessions"] += 1
