"""Compatibility baseline for v2 reaper result handling."""

from __future__ import annotations

import pytest

from app.services.task_queue_v2_reaper_contract import (
    apply_v1_reaper_result,
    apply_v2_reaper_result,
    normalize_v1_reaper_result,
    normalize_v2_reaper_result,
)


def test_reaper_result_preserves_counts_and_maps_nil_to_zero():
    assert normalize_v2_reaper_result(0) == 0
    assert normalize_v2_reaper_result(3) == 3
    assert normalize_v2_reaper_result("2") == 2
    assert normalize_v2_reaper_result(None) == 0


def test_reaper_result_rejects_invalid_values_like_the_historical_int_call():
    with pytest.raises((TypeError, ValueError)):
        normalize_v2_reaper_result("invalid")


def test_positive_reclaims_are_actionable():
    assert apply_v2_reaper_result(1)
    assert apply_v2_reaper_result(100)
    assert not apply_v2_reaper_result(0)
    assert not apply_v2_reaper_result(-1)


def test_v1_reaper_result_preserves_historical_contract():
    assert normalize_v1_reaper_result(None) == 0
    assert normalize_v1_reaper_result(0) == 0
    assert normalize_v1_reaper_result(5) == 5
    assert apply_v1_reaper_result(1)
    assert not apply_v1_reaper_result(0)
    assert not apply_v1_reaper_result(-1)
