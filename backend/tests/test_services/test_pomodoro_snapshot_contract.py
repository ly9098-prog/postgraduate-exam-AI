"""Exercise the real snapshot with controlled IO and real duration attribution."""

import asyncio
import itertools
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.time_utils import study_day_utc_range
from app.services import pomodoro_service as service

TODAY = date(2026, 10, 22)
MONDAY = date(2026, 10, 19)
FLAGS = ("need_stats", "need_trends", "need_daily_summary", "need_range_summary")
FULL_TRACE = [
    "get_pomodoro_settings",
    "current_study_day",
    "study_day_utc_range",
    "study_week_utc_range",
    "study_day_utc_range",
    "study_day_utc_range",
    "study_day_utc_range",
    "study_day_utc_range",
    "study_day_utc_range",
    "_load_overlapping_sessions",
    "_load_overlapping_practice_sessions",
    "study_week_utc_range",
    "active_intervals_for_session",
    "split_session_duration_by_study_day",
    "resolve_allocations",
    "allocate_seconds_by_weight",
    "resolve_allocations",
    "allocate_seconds_by_weight",
    "split_duration_excluding_intervals",
    "resolve_subject",
    "resolve_subject",
    "build_statistics_response",
]


class NoDatabaseIO:
    def __getattr__(self, name):
        raise AssertionError(f"snapshot bypassed its IO ports: {name}")


def _learning_session(start, subject_id, code, *, focus):
    pause = SimpleNamespace(
        started_at=start + timedelta(minutes=10), ended_at=start + timedelta(minutes=20)
    )
    return SimpleNamespace(
        start_time=start,
        end_time=start + timedelta(minutes=30 if focus else 20),
        actual_duration=1200,
        status="completed",
        subject_id=subject_id,
        subject_ref=SimpleNamespace(code=code, name=code, is_active=True),
        subject_allocations=[],
        pause_intervals=[pause] if focus else [],
    )


@pytest.fixture
def runtime(monkeypatch):
    events, day_calls, loads = [], [], []
    state = SimpleNamespace(dsm=0, empty=False)
    db = NoDatabaseIO()

    async def settings(actual_db, uid):
        events.append("get_pomodoro_settings")
        assert actual_db is db and uid == 37
        return {
            "day_start_minute": state.dsm,
            "day_start_time": "06:00" if state.dsm else "00:00",
        }

    def day_range(day, dsm):
        day_calls.append((day, dsm))
        return study_day_utc_range(day, dsm)

    def week_range(dsm):
        return study_day_utc_range(MONDAY, dsm)[0], study_day_utc_range(
            MONDAY + timedelta(days=7), dsm
        )[0]

    async def load(name, actual_db, uid, start, end, *, with_subject):
        events.append(name)
        loads.append((name, actual_db, uid, start, end, with_subject))
        if state.empty:
            return []
        beginning = study_day_utc_range(TODAY, state.dsm)[0] + timedelta(hours=1)
        focus = name == "_load_overlapping_sessions"
        return [
            _learning_session(
                beginning if focus else beginning + timedelta(minutes=5),
                7 if focus else 9,
                "data_structure" if focus else "english",
                focus=focus,
            )
        ]

    def wrap(name, operation):
        def run(*args, **kwargs):
            events.append(name)
            return operation(*args, **kwargs)

        return run

    monkeypatch.setattr(service, "get_pomodoro_settings", settings)
    for name, operation in {
        "current_study_day": lambda _dsm: TODAY,
        "study_day_utc_range": day_range,
        "study_week_utc_range": week_range,
        **{name: getattr(service, name) for name in FULL_TRACE[12:]},
    }.items():
        monkeypatch.setattr(service, name, wrap(name, operation))
    for name in ("_load_overlapping_sessions", "_load_overlapping_practice_sessions"):

        async def loader(*args, _name=name, **kwargs):
            return await load(_name, *args, **kwargs)

        monkeypatch.setattr(service, name, loader)
    return SimpleNamespace(
        state=state, events=events, day_calls=day_calls, loads=loads, db=db
    )


async def _snapshot(runtime, **overrides):
    arguments = dict(zip(FLAGS, [True] * 4))
    arguments.update(
        trends_days=3, range_start=TODAY - timedelta(days=1), range_end=TODAY
    )
    arguments.update(overrides)
    return await service.build_pomodoro_statistics_snapshot(runtime.db, 37, **arguments)


def _groups(empty):
    if empty:
        return []
    return [
        dict(
            subject_id=7,
            subject_code="data_structure",
            subject_name="data_structure",
            sessions=1,
            participation_sessions=1,
            duration_sec=1200,
        ),
        dict(
            subject_id=9,
            subject_code="english",
            subject_name="english",
            sessions=1,
            participation_sessions=0,
            duration_sec=600,
        ),
    ]


def _expected(dsm, empty):
    count, duration = (0, 0) if empty else (1, 1800)
    common = dict(day_start_minute=dsm, day_start_time="06:00" if dsm else "00:00")
    return {
        "stats": dict(
            today_sessions=count,
            today_duration_sec=duration,
            week_sessions=count,
            week_duration_sec=duration,
            today_date=TODAY.isoformat(),
            week_start_date=MONDAY.isoformat(),
            **common,
        ),
        "trends": [
            dict(
                date=(TODAY - timedelta(days=offset)).isoformat(),
                sessions=count if offset == 0 else 0,
                duration_sec=duration if offset == 0 else 0,
            )
            for offset in (2, 1, 0)
        ],
        "daily_summary": dict(
            date=TODAY.isoformat(),
            timezone="Asia/Shanghai",
            sessions=count,
            duration_sec=duration,
            subjects=_groups(empty),
            **common,
        ),
        "range_summary": dict(
            start_date=(TODAY - timedelta(days=1)).isoformat(),
            end_date=TODAY.isoformat(),
            timezone="Asia/Shanghai",
            sessions=count,
            duration_sec=duration,
            active_days=count,
            subjects=_groups(empty),
            **common,
        ),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("flags", list(itertools.product([False, True], repeat=4)))
@pytest.mark.parametrize("include_subjects", [False, True])
@pytest.mark.parametrize("dsm", [0, 360])
@pytest.mark.parametrize("empty", [False, True])
async def test_dimensions_outputs_window_and_single_load(
    runtime, flags, include_subjects, dsm, empty
):
    runtime.state.dsm, runtime.state.empty = dsm, empty
    result = await _snapshot(
        runtime, **dict(zip(FLAGS, flags)), range_include_subjects=include_subjects
    )
    expected = _expected(dsm, empty)
    if not include_subjects:
        expected["range_summary"]["subjects"] = []
    assert result == {
        key: value for enabled, (key, value) in zip(flags, expected.items()) if enabled
    }
    assert runtime.events[:2] == ["get_pomodoro_settings", "current_study_day"]
    if not any(flags):
        assert not runtime.loads and not runtime.day_calls and len(runtime.events) == 2
        return
    first = MONDAY if flags[0] else (TODAY - timedelta(days=2) if flags[1] else TODAY)
    if flags[3]:
        first = min(first, TODAY - timedelta(days=1))
    subject = flags[2] or (flags[3] and include_subjects)
    end = (
        study_day_utc_range(MONDAY + timedelta(days=7), dsm)[0]
        if flags[0]
        else study_day_utc_range(TODAY, dsm)[1]
    )
    assert runtime.loads == [
        (name, runtime.db, 37, study_day_utc_range(first, dsm)[0], end, subject)
        for name in (
            "_load_overlapping_sessions",
            "_load_overlapping_practice_sessions",
        )
    ]
    focus = runtime.events.index("_load_overlapping_sessions")
    assert runtime.events[focus + 1 : focus + 3] == [
        "_load_overlapping_practice_sessions",
        "study_week_utc_range",
    ]
    assert runtime.events.count("study_week_utc_range") == 1 + int(flags[0])


@pytest.mark.asyncio
async def test_all_dimensions_keep_complete_call_order(runtime):
    await _snapshot(runtime)
    assert runtime.events == FULL_TRACE


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_index", range(len(FULL_TRACE)))
@pytest.mark.parametrize("cancelled", [False, True])
async def test_error_identity_and_stop_at_every_stage(
    runtime, monkeypatch, failure_index, cancelled
):
    name = FULL_TRACE[failure_index]
    occurrence = FULL_TRACE[: failure_index + 1].count(name)
    original = getattr(service, name)
    error = (
        asyncio.CancelledError("cancelled")
        if cancelled
        else RuntimeError("synthetic failure")
    )
    calls = 0

    def fail_now():
        nonlocal calls
        calls += 1
        if calls == occurrence:
            runtime.events.append(name)
            raise error

    if name in {
        "get_pomodoro_settings",
        "_load_overlapping_sessions",
        "_load_overlapping_practice_sessions",
    }:

        async def invoke(*args, **kwargs):
            fail_now()
            return await original(*args, **kwargs)
    else:

        def invoke(*args, **kwargs):
            fail_now()
            return original(*args, **kwargs)

    monkeypatch.setattr(service, name, invoke)
    with pytest.raises(type(error)) as caught:
        await _snapshot(runtime)
    assert caught.value is error
    assert runtime.events == FULL_TRACE[: failure_index + 1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,end,message",
    [
        (None, TODAY, "are required"),
        (TODAY, None, "are required"),
        (TODAY, TODAY - timedelta(days=1), "on or after"),
    ],
)
async def test_invalid_range_keeps_prior_window_work_but_never_loads(
    runtime, start, end, message
):
    with pytest.raises(ValueError, match=message):
        await _snapshot(runtime, range_start=start, range_end=end)
    assert runtime.events == FULL_TRACE[:7]
    assert not runtime.loads


@pytest.mark.asyncio
async def test_disabled_range_ignores_invalid_dates(runtime):
    assert (
        await _snapshot(
            runtime, **dict.fromkeys(FLAGS, False), range_start=TODAY, range_end=None
        )
        == {}
    )
    assert runtime.events == FULL_TRACE[:2]


@pytest.mark.asyncio
async def test_disjoint_target_and_future_range_use_union_bounds(runtime):
    result = await _snapshot(
        runtime,
        need_stats=False,
        target_date=TODAY - timedelta(days=10),
        trends_days=4,
        range_start=TODAY + timedelta(days=2),
        range_end=TODAY + timedelta(days=5),
    )
    for load in runtime.loads:
        assert load[3:5] == (
            study_day_utc_range(TODAY - timedelta(days=10), 0)[0],
            study_day_utc_range(TODAY + timedelta(days=5), 0)[1],
        )
    assert (
        result["daily_summary"]["duration_sec"]
        == result["range_summary"]["duration_sec"]
        == 0
    )
    assert result["trends"][-1]["duration_sec"] == 1800


@pytest.mark.asyncio
async def test_zero_duration_counts_focus_without_subject_slices(runtime, monkeypatch):
    start = study_day_utc_range(TODAY, 0)[0] + timedelta(hours=1)
    focus = _learning_session(start, 7, "data_structure", focus=True)
    practice = _learning_session(start, 9, "english", focus=False)
    focus.actual_duration = practice.actual_duration = 0
    monkeypatch.setattr(
        service, "_load_overlapping_sessions", AsyncMock(return_value=[focus])
    )
    monkeypatch.setattr(
        service,
        "_load_overlapping_practice_sessions",
        AsyncMock(return_value=[practice]),
    )
    result = await _snapshot(runtime)
    assert result["stats"]["today_sessions"] == result["stats"]["week_sessions"] == 1
    assert (
        result["stats"]["today_duration_sec"]
        == result["stats"]["week_duration_sec"]
        == 0
    )
    assert result["trends"][-1] == dict(
        date=TODAY.isoformat(), sessions=1, duration_sec=0
    )
    for key in ("daily_summary", "range_summary"):
        assert result[key]["sessions"] == 1 and result[key]["duration_sec"] == 0
        assert result[key]["subjects"] == []
    assert result["range_summary"]["active_days"] == 0


@pytest.mark.asyncio
async def test_multi_source_cross_day_pause_overlap_and_ordering(runtime, monkeypatch):
    day_one = study_day_utc_range(TODAY - timedelta(days=1), 0)[0] + timedelta(hours=23)
    focus = _learning_session(day_one, 7, "data_structure", focus=True)
    focus.end_time = day_one + timedelta(hours=2)
    focus.actual_duration = 3600
    focus.pause_intervals = [
        SimpleNamespace(
            started_at=day_one + timedelta(minutes=30),
            ended_at=day_one + timedelta(minutes=90),
        )
    ]
    practice = _learning_session(
        day_one + timedelta(minutes=30), 9, "english", focus=False
    )
    practice.end_time = day_one + timedelta(hours=1, minutes=30)
    practice.actual_duration = 3600
    loaded = []

    async def focus_loader(*args, **kwargs):
        loaded.append("focus")
        return [focus]

    async def supplemental_loader(*args, **kwargs):
        loaded.append("supplemental")
        return [practice]

    monkeypatch.setattr(service, "_load_overlapping_sessions", focus_loader)
    monkeypatch.setattr(
        service, "_load_overlapping_practice_sessions", supplemental_loader
    )
    result = await _snapshot(
        runtime,
        trends_days=2,
        range_start=TODAY - timedelta(days=1),
        range_end=TODAY,
    )
    assert loaded == ["focus", "supplemental"]
    assert result["stats"]["today_sessions"] == 0
    assert result["stats"]["today_duration_sec"] == 3600
    assert result["trends"] == [
        dict(
            date=(TODAY - timedelta(days=1)).isoformat(),
            sessions=1,
            duration_sec=3600,
        ),
        dict(date=TODAY.isoformat(), sessions=0, duration_sec=3600),
    ]
    assert result["range_summary"]["duration_sec"] == 7200
    assert result["range_summary"]["active_days"] == 2
    assert result["daily_summary"]["duration_sec"] == 3600
    subjects = result["daily_summary"]["subjects"]
    assert [(row["subject_code"], row["duration_sec"]) for row in subjects] == [
        ("data_structure", 1800),
        ("english", 1800),
    ]
    assert [(row["sessions"], row["participation_sessions"]) for row in subjects] == [
        (0, 0),
        (0, 0),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("source", ["focus", "supplemental"])
async def test_source_attribution_error_or_cancel_has_identity_and_short_circuits(
    runtime, monkeypatch, cancelled, source
):
    error = (
        asyncio.CancelledError("cancelled")
        if cancelled
        else RuntimeError("attribution failed")
    )
    called = []

    def fail(*args, **kwargs):
        called.append("attribution")
        raise error

    monkeypatch.setattr(
        service,
        "active_intervals_for_session"
        if source == "focus"
        else "split_duration_excluding_intervals",
        fail,
    )
    with pytest.raises(type(error)) as caught:
        await _snapshot(runtime)
    assert caught.value is error
    assert called == ["attribution"]
    assert "build_statistics_response" not in runtime.events
