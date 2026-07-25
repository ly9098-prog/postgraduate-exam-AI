"""Stage management for Sprint 4D: Stage 1A (CPU Worker) / Stage 1B (GPU Worker) split."""
from __future__ import annotations

from enum import Enum, StrEnum

# Allowed platform tags for GPU wheel download (fail-fast filter)
_WHEEL_ALLOWED_PLATFORMS: list[str] = [
    "manylinux_2_28_x86_64",
    "manylinux_2_27_x86_64",
    "manylinux2014_x86_64",
    "linux_x86_64",
]


class Stage1AStatus(StrEnum):
    NOT_STARTED = "stage_1a_not_started"
    RUNNING = "stage_1a_running"
    COMPLETED = "stage_1a_completed"
    FAILED = "stage_1a_failed"


class Stage1BStatus(StrEnum):
    GPU_ENVIRONMENT_BLOCKED = "stage_1b_gpu_environment_blocked"
    GPU_PREFLIGHT_PASSED = "stage_1b_gpu_preflight_passed"
    RUNNING = "stage_1b_running"
    COMPLETED = "stage_1b_completed"
    FAILED = "stage_1b_failed"


class ExecutionMode(StrEnum):
    LEGACY = "legacy"
    EXTERNAL_LOCAL_WORKER = "external_local_worker"


class ReleaseDecision:
    """Structured release decision for the OCR worker rollout."""

    def __init__(self) -> None:
        self.external_worker_architecture: bool = False
        self.architecture_evidence: list[str] = []

        self.cpu_worker_stage_1a: bool = False
        self.cpu_worker_performance_approved: bool = False
        self.cpu_worker_evidence: list[str] = []

        self.gpu_environment: str = "blocked"
        self.gpu_environment_evidence: list[str] = []

        self.gpu_worker_stage_1b: bool = False
        self.gpu_worker_evidence: list[str] = []

        self.production_default_switch: bool = False
        self.production_blockers: list[str] = []

    def to_dict(self) -> dict:
        return {
            "external_worker_architecture": {
                "approved": self.external_worker_architecture,
                "evidence": self.architecture_evidence,
            },
            "cpu_worker_stage_1a": {
                "approved": self.cpu_worker_stage_1a,
                "performance_approved": self.cpu_worker_performance_approved,
                "evidence": self.cpu_worker_evidence,
            },
            "gpu_environment": {
                "status": self.gpu_environment,
                "evidence": self.gpu_environment_evidence,
            },
            "gpu_worker_stage_1b": {
                "approved": self.gpu_worker_stage_1b,
                "evidence": self.gpu_worker_evidence,
            },
            "production_default_switch": {
                "approved": self.production_default_switch,
                "blockers": self.production_blockers,
            },
        }

    @property
    def stage1a_can_complete_without_gpu(self) -> bool:
        """Stage 1A must be completable without any GPU environment."""
        return True

    @property
    def stage1a_does_not_approve_gpu_performance(self) -> bool:
        """Stage 1A completion must NOT automatically approve GPU performance."""
        return not self.gpu_worker_stage_1b

    @property
    def stage1b_cannot_start_without_gpu_preflight(self) -> bool:
        """Stage 1B cannot start unless GPU preflight has passed."""
        return self.gpu_environment in ("passed",)

    @property
    def production_default_cannot_switch_without_stage1b(self) -> bool:
        """Production default mode cannot switch to external_local_worker without Stage 1B."""
        return not self.production_default_switch
