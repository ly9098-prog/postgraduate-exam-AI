"""Canary auto-stop conditions tests."""
from __future__ import annotations

import os
from unittest.mock import patch

from app.features.ocr_canary import (
    ENV_CANARY_ENABLED,
    ENV_IR_CANARY_PERCENT,
    evaluate_canary_health,
    is_canary_globally_disabled,
    is_ir_canary_disabled,
)


class TestAutoStop:
    def test_global_disable_switch(self):
        """OCR_CANARY_ENABLED=false should disable all canary logic."""
        with patch.dict(os.environ, {ENV_CANARY_ENABLED: "false"}, clear=True):
            assert is_canary_globally_disabled() is True

    def test_global_enable_switch(self):
        with patch.dict(os.environ, {ENV_CANARY_ENABLED: "true"}, clear=True):
            assert is_canary_globally_disabled() is False

    def test_ir_canary_disabled_at_zero(self):
        with patch.dict(os.environ, {ENV_IR_CANARY_PERCENT: "0"}, clear=True):
            assert is_ir_canary_disabled() is True

    def test_ir_canary_disabled_at_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_ir_canary_disabled() is True

    def test_ir_canary_enabled(self):
        with patch.dict(os.environ, {ENV_IR_CANARY_PERCENT: "1.0"}, clear=True):
            assert is_ir_canary_disabled() is False

    def test_ir_canary_disabled_bad_value(self):
        with patch.dict(os.environ, {ENV_IR_CANARY_PERCENT: "bad"}, clear=True):
            assert is_ir_canary_disabled() is True

    def test_stop_conditions_hard_data_loss(self):
        """Hard stop: data loss should raise alert."""
        decision = evaluate_canary_health(data_loss_detected=True)
        assert decision.stop_rollout is True
        assert decision.rollback_required is True

    def test_stop_conditions_statistical_latency(self):
        """Statistical stop: latency increase >20%."""
        decision = evaluate_canary_health(p95_latency_increase_pct=25.0)
        assert decision.stop_rollout is True
        assert decision.rollback_required is False  # not hard

    def test_multiple_statistical_reasons(self):
        """Multiple statistical thresholds should all be reported."""
        decision = evaluate_canary_health(
            p95_latency_increase_pct=25.0,
            error_rate_increase_pct=2.0,
            artifact_size_increase_pct=60.0,
        )
        assert len(decision.reason_codes) == 3

    def test_no_stop_when_below_thresholds(self):
        """Below all statistical thresholds → no stop needed."""
        decision = evaluate_canary_health(
            ir_fallback_rate=0.5,
            question_count_mismatch_rate=0.0,
            option_text_normalized_mismatch_rate=3.0,
            p95_latency_increase_pct=5.0,
            error_rate_increase_pct=0.1,
            review_rejection_rate=10.0,
            artifact_size_increase_pct=10.0,
        )
        assert decision.healthy is True
        assert decision.stop_rollout is False

    def test_review_rejection_rate_stop(self):
        decision = evaluate_canary_health(review_rejection_rate=60.0)
        assert decision.stop_rollout is True
