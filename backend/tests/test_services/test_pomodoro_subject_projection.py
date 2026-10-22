"""Characterize subject projection before changing its dependency boundary."""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import pomodoro_subject_projection as projection

CODES = (
    "data_structure",
    "computer_organization",
    "operating_system",
    "computer_network",
)


def _session(code="data_structure", *, active=True, subject_id=4):
    return SimpleNamespace(
        subject_id=subject_id,
        subject_ref=SimpleNamespace(code=code, name="current", is_active=active),
        subject_allocations=[],
    )


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        (_session(), (4, "data_structure", "current")),
        (_session(active=False), (None, "", "未分类")),
        (_session(subject_id=None), (None, "", "未分类")),
        (_session(code="unrecognized"), (None, "", "未分类")),
        (_session(code="english", active=False), (4, "english", "current")),
        (SimpleNamespace(subject_id=4, subject_ref=None), (None, "", "未分类")),
    ],
)
def test_legacy_subject_uses_product_availability(session, expected):
    assert projection.resolve_subject(session) == expected
    assert projection.resolve_allocations(session) == [(*expected, 10000)]


def test_persisted_snapshots_keep_names_ids_and_weights_in_canonical_order():
    rows = [
        SimpleNamespace(
            subject_id=index + 10,
            subject_code_snapshot=code,
            subject_name_snapshot=f"snapshot-{index}",
            weight_basis_points=1000 + index,
        )
        for index, code in reversed(list(enumerate(CODES)))
    ]
    session = _session(active=False)
    session.subject_allocations = rows
    before = list(rows)
    assert projection.resolve_allocations(session) == [
        (index + 10, code, f"snapshot-{index}", 1000 + index)
        for index, code in enumerate(CODES)
    ]
    assert session.subject_allocations == before


def test_lite_projection_keeps_deleted_subject_snapshots_separate():
    session = _session()
    session.subject_allocations = [
        SimpleNamespace(
            subject_id=None,
            subject_code="z",
            subject_name="old-z",
            weight_basis_points=2000,
        ),
        SimpleNamespace(
            subject_id=None,
            subject_code="a",
            subject_name="old-a",
            weight_basis_points=8000,
        ),
    ]
    assert projection.resolve_allocations(session) == [
        (None, "a", "old-a", 8000),
        (None, "z", "old-z", 2000),
    ]
    assert projection.allocation_group_key(None, "a") == ("deleted-subject", "a")
    assert projection.allocation_group_key(None, "z") == ("deleted-subject", "z")
    assert projection.allocation_group_key(None, "") is None
    assert projection.allocation_group_key(4, "a") == 4


def test_snapshot_fields_take_precedence_even_when_empty():
    session = _session()
    session.subject_allocations = [
        SimpleNamespace(
            subject_id=4,
            subject_code_snapshot="",
            subject_name_snapshot="",
            subject_code="data_structure",
            subject_name="lite-name",
            weight_basis_points=10000,
        )
    ]
    assert projection.resolve_allocations(session) == [(4, "", "", 10000)]


@pytest.mark.parametrize(
    ("seconds", "weights", "expected"),
    [
        (3, [2500, 2500, 2500, 2500], [1, 1, 1, 0]),
        (3601, [2500, 2500, 2500, 2500], [901, 900, 900, 900]),
        (7, [1, 2, 4], [1, 2, 4]),
        (1, [1, 1], [1, 0]),
        (1.9, [1, 1], [1, 0]),
        (-2, [1, 1], [0, 0]),
        (2, [-1, 2], [0, 2]),
        (9, [], []),
    ],
)
def test_integer_allocation_preserves_order_and_input_coercion(
    seconds, weights, expected
):
    rows = [(index, "", "", weight) for index, weight in enumerate(weights)]
    assert projection.allocate_seconds_by_weight(seconds, rows) == expected


@pytest.mark.parametrize("weights", [[0], [-1, 0], ["0", 0]])
def test_nonpositive_total_weight_is_rejected_even_for_zero_seconds(weights):
    rows = [(index, "", "", weight) for index, weight in enumerate(weights)]
    with pytest.raises(ValueError, match="科目分配权重无效"):
        projection.allocate_seconds_by_weight(0, rows)


def test_range_must_allocate_each_day_before_summing_subjects():
    rows = [(index, code, code, 2500) for index, code in enumerate(CODES)]
    first = projection.allocate_seconds_by_weight(1, rows)
    second = projection.allocate_seconds_by_weight(1, rows)
    assert [a + b for a, b in zip(first, second)] == [2, 0, 0, 0]
    assert projection.allocate_seconds_by_weight(2, rows) == [1, 1, 0, 0]


@pytest.mark.asyncio
async def test_real_snapshot_preserves_per_day_rounding_and_start_day_count(
    monkeypatch,
):
    from app.services import pomodoro_service as service

    session = _session()
    session.start_time = datetime(2026, 10, 20, 15, 59, 59)
    session.end_time = datetime(2026, 10, 20, 16, 0, 1)
    session.actual_duration = 2
    session.status = "completed"
    session.pause_intervals = []
    session.subject_allocations = [
        SimpleNamespace(
            subject_id=index + 1,
            subject_code=code,
            subject_name=code,
            weight_basis_points=2500,
        )
        for index, code in enumerate(CODES)
    ]
    monkeypatch.setattr(
        service,
        "get_pomodoro_settings",
        AsyncMock(return_value={"day_start_minute": 0, "day_start_time": "00:00"}),
    )
    focus = AsyncMock(return_value=[session])
    practice = AsyncMock(return_value=[])
    monkeypatch.setattr(service, "_load_overlapping_sessions", focus)
    monkeypatch.setattr(service, "_load_overlapping_practice_sessions", practice)
    db = object()
    result = await service.build_pomodoro_statistics_snapshot(
        db,
        42,
        target_date=date(2026, 10, 21),
        need_daily_summary=True,
        need_range_summary=True,
        range_start=date(2026, 10, 20),
        range_end=date(2026, 10, 21),
    )
    daily, period = result["daily_summary"], result["range_summary"]
    assert daily["duration_sec"] == 1 and daily["sessions"] == 0
    assert period["duration_sec"] == 2 and period["sessions"] == 1
    assert period["active_days"] == 2
    assert [row["duration_sec"] for row in period["subjects"]] == [2, 0, 0, 0]
    assert [row["participation_sessions"] for row in period["subjects"]] == [1] * 4
    assert [row["duration_sec"] for row in daily["subjects"]] == [1, 0, 0, 0]
    for loader in (focus, practice):
        loader.assert_awaited_once_with(
            db,
            42,
            datetime(2026, 10, 19, 16),
            datetime(2026, 10, 21, 16),
            with_subject=True,
        )
