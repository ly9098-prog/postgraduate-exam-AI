"""Compatibility baseline for mixed learning-history response projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.pomodoro_history_projection import (
    build_history_allocation_fallback,
    build_history_item,
)


@dataclass
class Subject:
    code: str
    name: str


@dataclass
class HistoryRow:
    record_type: str
    id: int
    user_id: int
    subject_id: int | None
    start_time: str
    end_time: str
    actual_duration: int
    status: str
    preset: str | None


def row(record_type: str, subject_id: int | None = 1) -> HistoryRow:
    return HistoryRow(
        record_type=record_type,
        id=7,
        user_id=11,
        subject_id=subject_id,
        start_time="2026-10-25 10:00:00",
        end_time="2026-10-25 10:25:00",
        actual_duration=1500,
        status="completed",
        preset="focus" if record_type == "pomodoro" else None,
    )


def test_pomodoro_without_allocations_uses_single_subject_fallback():
    item = build_history_item(
        row=row("pomodoro"),
        subject=Subject("data_structure", "数据结构"),
        allocations=[],
        equal_408_mode="equal_408_core_v1",
    )

    assert item["record_key"] == "pomodoro:7"
    assert item["allocation_mode"] == "single"
    assert item["subject_allocations"] == [
        {
            "subject_id": 1,
            "subject_code": "data_structure",
            "subject_name": "数据结构",
            "weight_basis_points": 10000,
        }
    ]


def test_pomodoro_with_multiple_allocations_preserves_snapshot_and_mode():
    allocations: list[dict[str, Any]] = [
        {"subject_id": 1, "subject_code": "a", "weight_basis_points": 2500},
        {"subject_id": 2, "subject_code": "b", "weight_basis_points": 7500},
    ]
    before = [dict(allocation) for allocation in allocations]
    item = build_history_item(
        row=row("pomodoro"),
        subject=Subject("exam408", "计算机综合"),
        allocations=allocations,
        equal_408_mode="equal_408_core_v1",
    )

    assert item["allocation_mode"] == "equal_408_core_v1"
    assert item["subject_allocations"] == allocations
    assert allocations == before


def test_non_pomodoro_records_do_not_inherit_allocations():
    allocations = [{"subject_id": 1, "subject_code": "a"}]
    for record_type in ("practice", "review"):
        item = build_history_item(
            row=row(record_type),
            subject=Subject("data_structure", "数据结构"),
            allocations=allocations,
            equal_408_mode="equal_408_core_v1",
        )

        assert item["record_key"] == f"{record_type}:7"
        assert item["allocation_mode"] is None
        assert item["subject_allocations"] == []


def test_missing_subject_is_unclassified_and_fallback_helper_is_pomodoro_only():
    item = build_history_item(
        row=row("pomodoro", subject_id=None),
        subject=None,
        allocations=[],
        equal_408_mode="equal_408_core_v1",
    )

    assert item["subject_code"] == ""
    assert item["subject_name"] == "未分类"
    assert item["subject_allocations"][0]["subject_id"] is None
    assert build_history_allocation_fallback(
        record_type="practice",
        subject_id=1,
        subject_code="a",
        subject_name="A",
    ) == []
