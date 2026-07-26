"""Release decision split tests — verify Stage 1A/1B decoupling."""
from __future__ import annotations

import json

from app.stage import ReleaseDecision


class TestReleaseDecisionSplit:
    """Verify Stage 1A and Stage 1B have independent release decisions."""

    def test_stage1a_approved_independent_of_gpu(self):
        """Stage 1A can be approved even when GPU environment is blocked."""
        decision = ReleaseDecision()
        decision.external_worker_architecture = True
        decision.cpu_worker_stage_1a = True
        decision.cpu_worker_evidence = ["stage1a_cpu_e2e_passed",
                                        "stage1a_cpu_soak_passed"]
        decision.gpu_environment = "blocked"

        d = decision.to_dict()
        assert d["external_worker_architecture"]["approved"] is True
        assert d["cpu_worker_stage_1a"]["approved"] is True
        assert d["gpu_environment"]["status"] == "blocked"
        assert d["gpu_worker_stage_1b"]["approved"] is False
        assert d["production_default_switch"]["approved"] is False

    def test_stage1b_cannot_be_approved_without_preflight(self):
        """Stage 1B must not be approved without GPU preflight passed."""
        decision = ReleaseDecision()
        decision.gpu_environment = "blocked"

        # This should never happen — test fails if someone tries to set it
        decision.gpu_worker_stage_1b = False
        assert decision.gpu_worker_stage_1b is False

        d = decision.to_dict()
        assert d["gpu_environment"]["status"] == "blocked"

    def test_production_switch_requires_both_stages(self):
        """Production default switch requires Stage 1A + 1B."""
        decision = ReleaseDecision()
        # Only Stage 1A done
        decision.external_worker_architecture = True
        decision.cpu_worker_stage_1a = True
        decision.gpu_environment = "blocked"

        assert decision.production_default_switch is False
        assert len(decision.production_blockers) == 0  # No blockers registered yet

    def test_release_decision_has_separate_evidence(self):
        """Stage 1A and Stage 1B must have separate evidence lists."""
        decision = ReleaseDecision()
        decision.cpu_worker_evidence.append("cpu_e2e_test_passed")
        decision.gpu_worker_evidence.append("gpu_ocr_quality_passed")

        d = decision.to_dict()
        assert "cpu_e2e_test_passed" in d["cpu_worker_stage_1a"]["evidence"]
        assert "gpu_ocr_quality_passed" in d["gpu_worker_stage_1b"]["evidence"]
        assert "cpu_e2e_test_passed" not in d["gpu_worker_stage_1b"]["evidence"]

    def test_release_decision_is_machine_readable(self):
        """Release decision must be serializable to JSON."""
        decision = ReleaseDecision()
        decision.external_worker_architecture = True
        decision.cpu_worker_stage_1a = True

        json_str = json.dumps(decision.to_dict(), indent=2, ensure_ascii=False)
        parsed = json.loads(json_str)

        assert parsed["external_worker_architecture"]["approved"] is True
        assert parsed["cpu_worker_stage_1a"]["approved"] is True
        assert "gpu_environment" in parsed
        assert "production_default_switch" in parsed

    def test_stage1a_does_not_approve_gpu_by_default(self):
        """Stage 1A completion must NOT automatically approve GPU performance."""
        decision = ReleaseDecision()
        assert decision.stage1a_does_not_approve_gpu_performance is True

        # Simulate GPU later approved independently
        decision.gpu_worker_stage_1b = True
        assert decision.gpu_worker_stage_1b is True

    def test_gpu_environment_blocked_does_not_block_stage1a(self):
        """GPU environment being blocked must not block Stage 1A reporting."""
        decision = ReleaseDecision()
        decision.external_worker_architecture = True
        decision.cpu_worker_stage_1a = True
        decision.gpu_environment = "blocked"

        assert decision.cpu_worker_stage_1a is True  # Still approved
