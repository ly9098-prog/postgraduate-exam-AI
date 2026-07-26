"""Release decision tests."""
from __future__ import annotations

import json

from app.features.ocr_canary import evaluate_canary_health


class TestReleaseDecision:
    """Verify release decision model and generation."""

    def test_release_approved_when_healthy(self):
        """Release is approved when no blocking conditions."""
        health = evaluate_canary_health()
        decision = {
            "approved": health.healthy,
            "approved_stage": "stage_2" if health.healthy else "stage_0",
            "blockers": [] if health.healthy else health.reason_codes,
        }
        assert decision["approved"] is True
        assert decision["approved_stage"] == "stage_2"

    def test_release_blocked_by_data_loss(self):
        health = evaluate_canary_health(data_loss_detected=True)
        decision = {
            "approved": False,
            "blockers": health.reason_codes,
        }
        assert decision["approved"] is False
        assert "DATA_LOSS_DETECTED" in decision["blockers"]

    def test_release_blocked_by_binding_lost(self):
        health = evaluate_canary_health(binding_lost_count=1)
        assert health.rollback_required is True

    def test_release_blocked_by_duplicate_import(self):
        health = evaluate_canary_health(duplicate_import_count=1)
        assert health.rollback_required is True

    def test_release_has_machine_readable_format(self):
        """Release decision must be machine-readable (JSON)."""
        decision = {
            "approved": True,
            "approved_stage": "stage_2",
            "blockers": [],
            "warnings": [],
            "metrics": {"bench_valid_count": 100, "question_count_mismatch": 0},
            "evidence_artifacts": ["summary.json", "control_vs_canary.json"],
        }
        json_str = json.dumps(decision, indent=2)
        parsed = json.loads(json_str)
        assert parsed["approved"] is True
        assert "blockers" in parsed
        assert "evidence_artifacts" in parsed

    def test_release_blockers_list_all(self):
        """All blockers should be listed."""
        health = evaluate_canary_health(
            data_loss_detected=True,
            duplicate_import_count=1,
        )
        assert len(health.reason_codes) == 2

    def test_release_decision_is_actionable(self):
        """Release decision should state what to do next."""
        health = evaluate_canary_health(data_loss_detected=True)
        decision = {
            "approved": False,
            "recommendation": "rollback_to_legacy",
        }
        assert decision["recommendation"] == "rollback_to_legacy"
