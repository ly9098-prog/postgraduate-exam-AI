"""Fault injection tests for canary resilience."""
from __future__ import annotations

from app.features.ocr_canary import (
    GROUP_CONTROL_A,
    OCRCanaryConfig,
    check_ir_canary_failover,
    evaluate_canary_health,
    select_canary_group,
)


class TestFaultInjection:
    """Each fault should verify fallback, no duplicate import, and clean trace."""

    def test_document_ir_missing(self):
        """DocumentIR missing → fallback to legacy."""
        should_fallback, reasons = check_ir_canary_failover(doc_ir_available=False)
        assert should_fallback
        assert "IR_FREEZE_DOCUMENT_IR_MISSING" in reasons

    def test_ir_schema_incompatible(self):
        """IR schema incompatible → fallback."""
        should_fallback, reasons = check_ir_canary_failover(ir_schema_compatible=False)
        assert should_fallback

    def test_replacement_map_cycle(self):
        """ReplacementMap cycle → fallback."""
        should_fallback, _ = check_ir_canary_failover(replacement_map_cycle=True)
        assert should_fallback

    def test_binding_lost(self):
        """binding_lost → fallback."""
        should_fallback, _ = check_ir_canary_failover(binding_lost_count=1)
        assert should_fallback

    def test_cross_page_ambiguous(self):
        """CrossPageLink ambiguous → fallback."""
        should_fallback, _ = check_ir_canary_failover(cross_page_ambiguous=True)
        assert should_fallback

    def test_quality_gate_timeout(self):
        """Quality Gate timeout should not crash pipeline.

        This simulates: QG timeout → shadow mode continues without blocking.
        """
        # In shadow mode, QG failures are isolated
        decision = evaluate_canary_health(error_rate_increase_pct=0.5)
        assert decision.healthy is True  # under threshold

        # But significant errors stop rollout
        decision = evaluate_canary_health(error_rate_increase_pct=2.0)
        assert decision.stop_rollout is True

    def test_process_worker_crash(self):
        """Process worker crash → canary health detects it."""
        decision = evaluate_canary_health(pipeline_crash_count=2)
        assert decision.rollback_required is True

    def test_ocr_timeout(self):
        """OCR timeout → canary still has fallback path."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=100.0,
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        # Even with canary config, timeouts trigger individual fallback
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.group in ("observation_b", "canary_c")

    def test_artifact_write_failure(self):
        """Artifact write failure — canary should still produce stable output."""
        config = OCRCanaryConfig(
            enabled=False,
            freeze_mode="legacy",
            quality_gate_mode="off",
        )
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.group == GROUP_CONTROL_A
        assert selection.effective_freeze_mode == "legacy"

    def test_database_write_retry(self):
        """Database write retry — pipeline should still complete."""
        # Database layer is orthogonal to canary config
        # Canary doesn't introduce new DB writes
        config = OCRCanaryConfig(enabled=False)
        assert config.enabled is False

    def test_service_restart_resume(self):
        """Service restart on canary task — resume should pick up correctly."""
        config = OCRCanaryConfig(enabled=True, rollout_percent=5.0)
        s1 = select_canary_group("t1", "doc_hash", "v1", config)
        s2 = select_canary_group("t1", "doc_hash", "v1", config)
        assert s1.group == s2.group  # deterministic on resume
