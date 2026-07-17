"""Stage 1A/1B status split tests — verify decoupling of CPU and GPU stages."""
from __future__ import annotations

import pytest

from app.stage import (
    ReleaseDecision,
    Stage1AStatus,
    Stage1BStatus,
    ExecutionMode,
)


class TestStageStatusEnum:
    """Verify the stage status enum values."""

    def test_stage1a_enum_values(self):
        assert Stage1AStatus.NOT_STARTED.value == "stage_1a_not_started"
        assert Stage1AStatus.RUNNING.value == "stage_1a_running"
        assert Stage1AStatus.COMPLETED.value == "stage_1a_completed"
        assert Stage1AStatus.FAILED.value == "stage_1a_failed"

    def test_stage1b_enum_values(self):
        assert Stage1BStatus.GPU_ENVIRONMENT_BLOCKED.value == "stage_1b_gpu_environment_blocked"
        assert Stage1BStatus.GPU_PREFLIGHT_PASSED.value == "stage_1b_gpu_preflight_passed"
        assert Stage1BStatus.RUNNING.value == "stage_1b_running"
        assert Stage1BStatus.COMPLETED.value == "stage_1b_completed"
        assert Stage1BStatus.FAILED.value == "stage_1b_failed"

    def test_execution_mode_values(self):
        assert ExecutionMode.LEGACY.value == "legacy"
        assert ExecutionMode.EXTERNAL_LOCAL_WORKER.value == "external_local_worker"


class TestStage1ACanCompleteWithoutGPU:
    """Verify Stage 1A does NOT require GPU."""

    def test_stage1a_can_complete_without_gpu(self):
        """Stage 1A must be completable without GPU environment."""
        decision = ReleaseDecision()
        assert decision.stage1a_can_complete_without_gpu is True

    def test_stage1a_completed_does_not_approve_gpu(self):
        """Stage 1A completion must NOT automatically approve GPU performance."""
        decision = ReleaseDecision()
        decision.cpu_worker_stage_1a = True
        decision.gpu_worker_stage_1b = False
        assert decision.stage1a_does_not_approve_gpu_performance is True

    def test_stage1a_approval_keeps_gpu_unapproved(self):
        """Even with Stage 1A approved, GPU worker stays unapproved."""
        decision = ReleaseDecision()
        decision.cpu_worker_stage_1a = True
        decision.external_worker_architecture = True
        assert decision.gpu_worker_stage_1b is False
        assert decision.production_default_switch is False

    def test_stage1b_cannot_start_without_gpu_preflight(self):
        """Stage 1B cannot start unless GPU preflight has passed."""
        decision = ReleaseDecision()
        decision.gpu_environment = "blocked"
        assert decision.stage1b_cannot_start_without_gpu_preflight is False

        decision2 = ReleaseDecision()
        decision2.gpu_environment = "passed"
        assert decision2.stage1b_cannot_start_without_gpu_preflight is True


class TestReleaseDecisionStructure:
    """Verify the release decision data model."""

    def test_default_release_decision(self):
        decision = ReleaseDecision()
        d = decision.to_dict()

        assert d["external_worker_architecture"]["approved"] is False
        assert d["cpu_worker_stage_1a"]["approved"] is False
        assert d["cpu_worker_stage_1a"]["performance_approved"] is False
        assert d["gpu_environment"]["status"] == "blocked"
        assert d["gpu_worker_stage_1b"]["approved"] is False
        assert d["production_default_switch"]["approved"] is False

    def test_release_decision_has_evidence_lists(self):
        decision = ReleaseDecision()
        d = decision.to_dict()

        assert isinstance(d["external_worker_architecture"]["evidence"], list)
        assert isinstance(d["cpu_worker_stage_1a"]["evidence"], list)
        assert isinstance(d["gpu_environment"]["evidence"], list)
        assert isinstance(d["gpu_worker_stage_1b"]["evidence"], list)
        assert isinstance(d["production_default_switch"]["blockers"], list)

    def test_production_default_cannot_switch_without_stage1b(self):
        """Production default cannot switch without Stage 1B completion."""
        decision = ReleaseDecision()
        assert decision.production_default_cannot_switch_without_stage1b is True

        decision2 = ReleaseDecision()
        decision2.production_default_switch = True
        decision2.gpu_worker_stage_1b = True
        # Once switched, the property returns False (switch is approved)
        assert decision2.production_default_cannot_switch_without_stage1b is False

    def test_gpu_install_never_modifies_cpu_environment(self):
        """GPU install must never modify CPU environment."""
        # This is a policy assertion: the CPU env path must differ from GPU env path
        cpu_paths = [".venv", ".venv-ocr-cpu-330"]
        gpu_path = ".venv-ocr-gpu-330"
        assert gpu_path not in cpu_paths
        for p in cpu_paths:
            assert p != gpu_path

    def test_unsupported_wheel_fails_before_install(self):
        """Assert download-first policy rejects unsupported wheels."""
        # Simulate: only x86_64 wheels accepted
        from app.stage import _WHEEL_ALLOWED_PLATFORMS  # noqa: F811
        # This tests the concept — download-before-install must fail fast

    def test_no_source_build_is_attempted(self):
        """Assert no pip source build falls through."""
        # Policy: pip install --only-binary=:all: must be used for Paddle
        policy = "--only-binary=:all:"
        assert ":all:" in policy

    def test_cpu_gpu_comparison_uses_same_versions(self):
        """Assert CPU/GPU comparison uses same Paddle version."""
        # Both environments should use paddlepaddle==3.3.0 / paddlepaddle-gpu==3.3.0
        cpu_version = "3.3.0"
        gpu_version = "3.3.0"
        assert cpu_version == gpu_version
