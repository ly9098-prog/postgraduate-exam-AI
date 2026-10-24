"""Real compatibility baseline for study plan allocation and phase logic.

Exercises the pure allocation and phase functions against real inputs.
No database needed — these are deterministic pure functions.
"""

from __future__ import annotations

import pytest

from app.services.study_plan_service import (
    CATEGORIES,
    _allocate_integer,
    _ceil_minutes,
    _phase_for_days,
)


class TestPhaseForDays:
    @pytest.mark.parametrize(
        "days,code,label",
        [
            (0, "target_day", "目标日"),
            (-1, "target_day", "目标日"),
            (1, "sprint", "冲刺阶段"),
            (45, "sprint", "冲刺阶段"),
            (46, "steady", "强化阶段"),
            (180, "steady", "强化阶段"),
            (181, "foundation", "基础阶段"),
            (365, "foundation", "基础阶段"),
        ],
    )
    def test_phase_boundaries(self, days, code, label):
        result = _phase_for_days(days)
        assert result == (code, label)


class TestAllocateInteger:
    def test_zero_total_returns_all_zeros(self):
        result = _allocate_integer(0, {"review": 1, "weakness": 1, "new": 1, "exam": 1})
        assert all(v == 0 for v in result.values())

    def test_zero_weights_returns_all_zeros(self):
        result = _allocate_integer(100, {"review": 0, "weakness": 0, "new": 0, "exam": 0})
        assert all(v == 0 for v in result.values())

    def test_equal_weights_sum_to_total(self):
        total = 100
        weights = {k: 1.0 for k in CATEGORIES}
        result = _allocate_integer(total, weights)
        assert sum(result.values()) == total

    def test_single_category_gets_all(self):
        result = _allocate_integer(60, {"review": 1, "weakness": 0, "new": 0, "exam": 0})
        assert result["review"] == 60
        assert result["weakness"] == 0
        assert result["new"] == 0
        assert result["exam"] == 0

    def test_result_keys_are_exactly_categories(self):
        result = _allocate_integer(30, {"review": 0.5, "weakness": 0.5})
        assert set(result.keys()) == set(CATEGORIES)

    def test_negative_weights_treated_as_zero(self):
        result = _allocate_integer(50, {"review": -1, "weakness": 1, "new": 1, "exam": 1})
        assert result["review"] == 0
        assert sum(result.values()) == 50

    def test_remainder_distributed_by_largest_fractional(self):
        """3 units across 4 equal categories → 3 get +1, 1 gets 0."""
        result = _allocate_integer(3, {k: 1.0 for k in CATEGORIES})
        assert sum(result.values()) == 3
        assert sum(1 for v in result.values() if v == 1) == 3
        assert sum(1 for v in result.values() if v == 0) == 1


class TestCeilMinutes:
    def test_zero(self):
        assert _ceil_minutes(0) == 0

    def test_none(self):
        assert _ceil_minutes(None) == 0

    def test_rounds_up(self):
        assert _ceil_minutes(90) == 2  # 90 seconds = 1.5 min → ceil = 2

    def test_exact_minute(self):
        assert _ceil_minutes(120) == 2

    def test_negative_treated_as_zero(self):
        assert _ceil_minutes(-60) == 0
