"""Canary health decision tests."""
from __future__ import annotations

from app.features.ocr_canary import evaluate_canary_health


class TestCanaryHealthDecision:
    def test_healthy_by_default(self):
        decision = evaluate_canary_health()
        assert decision.healthy is True
        assert decision.stop_rollout is False
        assert decision.rollback_required is False
        assert decision.reason_codes == []

    def test_data_loss_triggers_rollback(self):
        decision = evaluate_canary_health(data_loss_detected=True)
        assert decision.healthy is False
        assert decision.stop_rollout is True
        assert decision.rollback_required is True
        assert "DATA_LOSS_DETECTED" in decision.reason_codes

    def test_exact_match_decrease_triggers_rollback(self):
        decision = evaluate_canary_health(exact_match_decrease=True)
        assert decision.rollback_required is True
        assert "EXACT_MATCH_DECREASED" in decision.reason_codes

    def test_option_key_mismatch_triggers_rollback(self):
        decision = evaluate_canary_health(option_key_mismatch_count=1)
        assert decision.rollback_required is True
        assert "OPTION_KEY_MISMATCH" in decision.reason_codes[0]

    def test_binding_lost_triggers_rollback(self):
        decision = evaluate_canary_health(binding_lost_count=1)
        assert decision.rollback_required is True

    def test_duplicate_import_triggers_rollback(self):
        decision = evaluate_canary_health(duplicate_import_count=1)
        assert decision.rollback_required is True

    def test_pipeline_crash_triggers_rollback(self):
        decision = evaluate_canary_health(pipeline_crash_count=1)
        assert decision.rollback_required is True

    def test_main_process_crash_triggers_rollback(self):
        decision = evaluate_canary_health(main_process_crash=True)
        assert decision.rollback_required is True

    def test_ir_fallback_rate_stop_rollout(self):
        """Fallback rate >1% should stop rollout but not require rollback."""
        decision = evaluate_canary_health(ir_fallback_rate=2.5)
        assert decision.stop_rollout is True
        assert decision.rollback_required is False  # statistical, not hard
        assert "IR_FALLBACK_RATE" in decision.reason_codes[0]

    def test_fallback_rate_under_threshold(self):
        decision = evaluate_canary_health(ir_fallback_rate=0.5)
        assert decision.healthy is True

    def test_question_count_mismatch_stop(self):
        """Any non-zero question count mismatch should stop."""
        decision = evaluate_canary_health(question_count_mismatch_rate=0.1)
        assert decision.stop_rollout is True

    def test_option_text_mismatch_over_threshold(self):
        decision = evaluate_canary_health(option_text_normalized_mismatch_rate=6.0)
        assert decision.stop_rollout is True

    def test_option_text_mismatch_under_threshold(self):
        decision = evaluate_canary_health(option_text_normalized_mismatch_rate=4.0)
        assert decision.healthy is True

    def test_p95_latency_increase_stop(self):
        decision = evaluate_canary_health(p95_latency_increase_pct=25.0)
        assert decision.stop_rollout is True

    def test_error_rate_increase_stop(self):
        decision = evaluate_canary_health(error_rate_increase_pct=1.0)
        assert decision.stop_rollout is True

    def test_artifact_size_increase_stop(self):
        decision = evaluate_canary_health(artifact_size_increase_pct=60.0)
        assert decision.stop_rollout is True

    def test_metrics_populated(self):
        decision = evaluate_canary_health(
            binding_lost_count=1,
            option_key_mismatch_count=2,
            ir_fallback_rate=3.0,
        )
        assert decision.metrics["binding_lost_count"] == 1.0
        assert decision.metrics["option_key_mismatch_count"] == 2.0
        assert decision.metrics["ir_fallback_rate"] == 3.0

    def test_combined_hard_and_stat(self):
        """Hard conditions should result in rollback even with statistical issues."""
        decision = evaluate_canary_health(
            data_loss_detected=True,
            p95_latency_increase_pct=30.0,
        )
        assert decision.rollback_required is True  # hard condition
        assert len(decision.reason_codes) == 2  # both reported

    def test_unrecoverable_cross_page_error(self):
        decision = evaluate_canary_health(unrecoverable_cross_page_error=True)
        assert decision.rollback_required is True
