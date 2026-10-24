"""Compatibility baseline for v2 admin transition result handling."""

from __future__ import annotations

from app.services.task_queue_v2_admin_contract import (
    normalize_v2_admin_result,
    should_log_v2_cancel,
    v2_cancel_reason,
    v2_mark_corrupt_success,
)


def test_admin_result_preserves_integers_and_maps_nil_to_zero():
    assert normalize_v2_admin_result(1) == 1
    assert normalize_v2_admin_result("2") == 2
    assert normalize_v2_admin_result(None) == 0
    assert normalize_v2_admin_result("invalid") == 0
    assert normalize_v2_admin_result(None) == normalize_v2_admin_result([])


def test_cancel_reason_is_capped_at_200_characters():
    reason = "x" * 250
    assert v2_cancel_reason(reason) == "x" * 200
    assert v2_cancel_reason("stop") == "stop"


def test_cancel_logging_only_occurs_for_positive_transition_codes():
    assert should_log_v2_cancel(1)
    assert should_log_v2_cancel(4)
    assert not should_log_v2_cancel(0)
    assert not should_log_v2_cancel(-1)


def test_mark_corrupt_success_uses_historical_truthiness():
    assert v2_mark_corrupt_success(1)
    assert v2_mark_corrupt_success("1")
    assert not v2_mark_corrupt_success(0)
    assert not v2_mark_corrupt_success(None)
