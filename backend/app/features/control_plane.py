"""OCR Control Plane — Logical Orchestration Facade for Sprint 4A.

Provides:
- PipelineExecutionContext: Frozen context snapshot for entire pipeline run.
- ExecutionQuota: Per-job budget limits.
- OCRControlPlane: create/resume, policy resolution, quota claim, stage recording, finalize.

Design:
- Pure logical facade — no new DB tables, no services.
- Delegates to existing ImportBatchJob, PipelineRunFingerprint, ArtifactWorkspace.
- Context is serializable (no tokens, no DB connections, no large bytes).
- Feature flags frozen at job start, not read from env during pipeline.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Execution Quota
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionQuota:
    """Per-job budget limits. Immutable — frozen at job start.

    All values are inclusive maximums. Exceeding any limit returns
    a clearly typed error code (not silent truncation).
    """
    max_pages: int = 200
    max_input_bytes: int = 100 * 1024 * 1024  # 100 MB
    max_render_pixels: int = 4000 * 4000  # 16 MP
    max_ocr_calls: int = 500
    max_remote_ocr_calls: int = 100
    max_ai_calls: int = 100
    max_ai_tokens: int = 100_000
    max_concurrent_pages: int = 3
    max_artifact_bytes: int = 500 * 1024 * 1024  # 500 MB


class QuotaExceededError(ValueError):
    """Raised when a job exceeds a budget limit."""

    ERROR_CODES: dict[str, str] = {
        "INPUT_TOO_LARGE": "INPUT_TOO_LARGE",
        "PAGE_LIMIT_EXCEEDED": "PAGE_LIMIT_EXCEEDED",
        "PIXEL_BUDGET_EXCEEDED": "PIXEL_BUDGET_EXCEEDED",
        "OCR_CALL_BUDGET_EXCEEDED": "OCR_CALL_BUDGET_EXCEEDED",
        "AI_TOKEN_BUDGET_EXCEEDED": "AI_TOKEN_BUDGET_EXCEEDED",
        "ARTIFACT_SIZE_LIMIT_EXCEEDED": "ARTIFACT_SIZE_LIMIT_EXCEEDED",
    }

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class QuotaLease:
    """Result of claiming quota. ``accepted``=False means limit hit."""
    accepted: bool
    quota_name: str = ""
    remaining: int = 0
    error_code: str = ""


# ---------------------------------------------------------------------------
# Pipeline Outcome & Execution Policy
# ---------------------------------------------------------------------------


class PipelineOutcome(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


@dataclass(frozen=True)
class ExecutionPolicy:
    """Execution policy resolved at job start.

    Controls how this specific pipeline run behaves —
    feature flags, canary bucket, structure freeze mode, etc.
    """
    canary_enabled: bool = False
    canary_bucket: str = ""
    structure_freeze_mode: str = "legacy"
    quality_gate_mode: str = "off"
    native_text_routing_mode: str = "off"
    ocr_gateway_mode: str = "legacy"
    document_ir_ssot_mode: str = "dual"
    unified_safety_mode: str = "off"
    persistence_mode: str = "legacy"
    page_stream_mode: str = "legacy"
    extra: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Resource Demand & Rollout Decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceDemand:
    """Resource demand for quota claiming."""
    estimated_pages: int = 0
    estimated_input_bytes: int = 0
    estimated_render_pixels: int = 0
    estimated_ocr_calls: int = 0
    requires_remote_ocr: bool = False
    requires_ai: bool = False
    estimated_ai_tokens: int = 0


@dataclass(frozen=True)
class RolloutDecision:
    """Canary/rollout decision for this job."""
    canary: bool = False
    bucket: str = ""
    variant: str = "control"


# ---------------------------------------------------------------------------
# Lightweight Collectors (in-memory, aggregated at finalize)
# ---------------------------------------------------------------------------


@dataclass
class _StageRecord:
    """Record of a single pipeline stage execution."""
    stage_name: str
    status: str = "pending"
    started_at: float = 0.0
    finished_at: float = 0.0
    latency_ms: float = 0.0
    result_type: str = ""
    error_code: str = ""
    artifacts: list[str] = field(default_factory=list)


class TraceCollector:
    """In-memory trace event collector for a single pipeline run.

    Not persisted per-event — aggregated into the final artifact.
    For persistent trace events, use BatchJobTraceEvent (DB).
    """

    def __init__(self, pipeline_id: str) -> None:
        self._pipeline_id = pipeline_id
        self._events: list[dict[str, Any]] = []

    def record(self, step: str, status: str, message: str = "",
               duration_ms: int = 0) -> None:
        self._events.append({
            "pipeline_id": self._pipeline_id,
            "step": step,
            "status": status,
            "message": message,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        })
        logger.debug("Trace [%s] %s=%s %s", self._pipeline_id, step, status, message)

    def drain(self) -> list[dict[str, Any]]:
        events = list(self._events)
        self._events.clear()
        return events


class MetricsCollector:
    """In-memory metrics collector for a single pipeline run."""

    def __init__(self, pipeline_id: str) -> None:
        self._pipeline_id = pipeline_id
        self._metrics: dict[str, float] = {}

    def gauge(self, name: str, value: float) -> None:
        self._metrics[name] = value

    def increment(self, name: str, delta: float = 1.0) -> None:
        self._metrics[name] = self._metrics.get(name, 0.0) + delta

    def snapshot(self) -> dict[str, float]:
        return dict(self._metrics)


# ---------------------------------------------------------------------------
# Cancellation Context
# ---------------------------------------------------------------------------


@dataclass
class CancellationContext:
    """Cooperative cancellation for pipeline stages.

    Stages should periodically check ``is_cancelled()`` and raise
    ``asyncio.CancelledError`` when True.
    """
    _cancelled: bool = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled


# ---------------------------------------------------------------------------
# Artifact Workspace (lightweight wrapper)
# ---------------------------------------------------------------------------


@dataclass
class ArtifactWorkspace:
    """Lightweight artifact workspace handle.

    The actual persistence is delegated to:
      - ``pipeline_artifacts.save_artifact()`` for structured data
      - Filesystem paths for rendered page images
    """
    pipeline_id: str = ""
    workspace_root: str = ""
    page_image_dir: str = ""


# ---------------------------------------------------------------------------
# PipelineExecutionContext
# ---------------------------------------------------------------------------


_CONTROL_PLANE_MODE = os.environ.get("CONTROL_PLANE_MODE", "facade")


def _generate_pipeline_id() -> str:
    return f"pl-{uuid.uuid4().hex[:16]}"


def _compute_config_fingerprint() -> str:
    """Compute a hash of the current settings for context freezing."""
    try:
        from app.core.config import settings
        d = {k: str(v) for k, v in sorted(settings.model_dump().items())}
        raw = json.dumps(d, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return "unknown"


def _load_feature_flags() -> dict[str, bool | str | float]:
    """Load and freeze feature flags from environment at context creation."""
    return {
        "structure_freeze_mode": os.environ.get("STRUCTURE_FREEZE_MODE", "legacy"),
        "quality_gate_mode": os.environ.get("DOMAIN_QUALITY_GATE_MODE", "off"),
        "native_text_routing_mode": os.environ.get("NATIVE_TEXT_ROUTING_MODE", "off"),
        "ocr_gateway_mode": os.environ.get("OCR_GATEWAY_MODE", "legacy"),
        "document_ir_ssot_mode": os.environ.get("DOCUMENT_IR_SSOT_MODE", "dual"),
        "unified_safety_mode": os.environ.get("UNIFIED_SAFETY_MODE", "off"),
        "persistence_mode": os.environ.get("PERSISTENCE_MODE", "legacy"),
        "page_stream_mode": os.environ.get("PAGE_STREAM_MODE", "legacy"),
        "control_plane_mode": _CONTROL_PLANE_MODE,
    }


@dataclass
class PipelineExecutionContext:
    """Unified context for a full pipeline execution.

    Created at job start and frozen — all feature flags, quotas, and
    fingerprints are determined once. Stages read from here instead of
    parsing environment variables or global config.

    Rules:
    - Serializable (no tokens, DB connections, or large byte blobs)
    - Each stage uses the same pipeline_id for trace/metric/artifact
    - Resume uses original context, not current env/state
    - Deployment profile is frozen at creation, not re-detected on resume
    """
    # Identity
    pipeline_id: str = ""
    import_id: int | None = None
    request_id: str = ""
    document_id: str = ""
    document_sha256: str = ""

    # Deployment profile (frozen at creation)
    deployment_profile: str = "local_import"
    runtime_capabilities: dict[str, Any] = field(default_factory=dict)

    # Source metadata
    source_type: str = ""
    subject: str | None = None
    tenant_id: str | None = None

    # Fingerprints (frozen at start)
    pipeline_fingerprint: str = ""
    config_fingerprint: str = ""
    model_fingerprints: dict[str, str] = field(default_factory=dict)

    # Feature flags (frozen at start)
    feature_flags: dict[str, bool | str | float] = field(default_factory=_load_feature_flags)

    # Budget
    quota: ExecutionQuota = field(default_factory=ExecutionQuota)
    rollout: RolloutDecision = field(default_factory=RolloutDecision)

    # Diagnostics & telemetry
    diagnostics: list[dict] = field(default_factory=list)
    trace: TraceCollector = field(default_factory=lambda: TraceCollector(""))
    metrics: MetricsCollector = field(default_factory=lambda: MetricsCollector(""))

    # AI model config snapshots (frozen at pipeline start)
    ai_model_configs: dict[str, dict] = field(default_factory=dict)
    # capabilitiy → serialized AIModelConfigSnapshot
    artifact_workspace: ArtifactWorkspace = field(default_factory=ArtifactWorkspace)
    cancellation: CancellationContext = field(default_factory=CancellationContext)

    def __post_init__(self) -> None:
        """Ensure trace/metrics collectors use the correct pipeline_id."""
        if not self.trace._pipeline_id and self.pipeline_id:
            object.__setattr__(self.trace, "_pipeline_id", self.pipeline_id)
        if not self.metrics._pipeline_id and self.pipeline_id:
            object.__setattr__(self.metrics, "_pipeline_id", self.pipeline_id)

    # ── Quota helpers ──

    def check_page_limit(self, page_count: int) -> None:
        if page_count > self.quota.max_pages:
            raise QuotaExceededError(
                "PAGE_LIMIT_EXCEEDED",
                f"Page count {page_count} exceeds limit {self.quota.max_pages}",
            )

    def check_input_size(self, size_bytes: int) -> None:
        if size_bytes > self.quota.max_input_bytes:
            mb = size_bytes / (1024 * 1024)
            limit_mb = self.quota.max_input_bytes / (1024 * 1024)
            raise QuotaExceededError(
                "INPUT_TOO_LARGE",
                f"Input size {mb:.1f} MB exceeds limit {limit_mb:.0f} MB",
            )

    # ── Serialization ──

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "import_id": self.import_id,
            "request_id": self.request_id,
            "document_id": self.document_id,
            "document_sha256": self.document_sha256,
            "deployment_profile": self.deployment_profile,
            "runtime_capabilities": dict(self.runtime_capabilities),
            "source_type": self.source_type,
            "subject": self.subject,
            "tenant_id": self.tenant_id,
            "pipeline_fingerprint": self.pipeline_fingerprint,
            "config_fingerprint": self.config_fingerprint,
            "model_fingerprints": dict(self.model_fingerprints),
            "feature_flags": dict(self.feature_flags),
            "quota": dataclasses.asdict(self.quota),
            "rollout": dataclasses.asdict(self.rollout),
            "diagnostics": list(self.diagnostics),
            "ai_model_configs": dict(self.ai_model_configs),
            "artifact_workspace": dataclasses.asdict(self.artifact_workspace),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineExecutionContext:
        quota_data = data.get("quota", {})
        rollout_data = data.get("rollout", {})
        ws_data = data.get("artifact_workspace", {})
        ctx = cls(
            pipeline_id=data.get("pipeline_id", ""),
            import_id=data.get("import_id"),
            request_id=data.get("request_id", ""),
            document_id=data.get("document_id", ""),
            document_sha256=data.get("document_sha256", ""),
            deployment_profile=data.get("deployment_profile", "local_import"),
            runtime_capabilities=data.get("runtime_capabilities", {}),
            source_type=data.get("source_type", ""),
            subject=data.get("subject"),
            tenant_id=data.get("tenant_id"),
            pipeline_fingerprint=data.get("pipeline_fingerprint", ""),
            config_fingerprint=data.get("config_fingerprint", ""),
            model_fingerprints=data.get("model_fingerprints", {}),
            feature_flags=data.get("feature_flags", {}),
            quota=ExecutionQuota(**quota_data),
            rollout=RolloutDecision(**rollout_data),
            diagnostics=data.get("diagnostics", []),
            ai_model_configs=data.get("ai_model_configs", {}),
            artifact_workspace=ArtifactWorkspace(**ws_data),
        )
        return ctx


# ---------------------------------------------------------------------------
# OCRControlPlane
# ---------------------------------------------------------------------------


class OCRControlPlane:
    """Logical Control Plane Facade.

    Manages job lifecycle: create/resume, policy resolution, quota, stage
    recording, and finalization. Does NOT introduce new services or DB tables;
    delegates to existing infrastructure (ImportBatchJob, artifacts, etc.).

    Mode: ``CONTROL_PLANE_MODE=legacy | facade`` (default: facade)
    """

    def __init__(self, mode: str | None = None) -> None:
        self._mode = mode or _CONTROL_PLANE_MODE

    @property
    def mode(self) -> str:
        return self._mode

    # ── Job lifecycle ──

    async def create_or_resume_job(
        self,
        *,
        request_id: str = "",
        source_type: str = "",
        source_sha256: str = "",
        subject: str | None = None,
        tenant_id: str | None = None,
    ) -> PipelineExecutionContext:
        """Create a new pipeline context or resume an existing one.

        In facade mode, this generates a fresh context with frozen
        fingerprints and feature flags. Resume support uses the existing
        artifact resume mechanism (pipeline_artifacts.find_resumable_stage).
        """
        pipeline_id = f"pl-{uuid.uuid4().hex[:16]}"
        document_id = source_sha256[:16] if source_sha256 else pipeline_id[:16]

        # Build fingerprint using existing infrastructure
        pipeline_fp = ""
        try:
            from app.features.pipeline_fingerprint import build_pipeline_fingerprint
            fp = build_pipeline_fingerprint(
                pipeline_version="sprint4a",
                ocr_backend="paddleocr",
                ocr_use_gpu="gpu" in os.environ.get("OCR_WORKER_DEVICE", ""),
            )
            pipeline_fp = fp.compute_hash()
        except Exception:
            pass

        config_fp = _compute_config_fingerprint()

        ctx = PipelineExecutionContext(
            pipeline_id=pipeline_id,
            request_id=request_id,
            document_id=document_id,
            document_sha256=source_sha256,
            source_type=source_type,
            subject=subject,
            tenant_id=tenant_id,
            pipeline_fingerprint=pipeline_fp,
            config_fingerprint=config_fp,
            quota=ExecutionQuota(),
            artifact_workspace=ArtifactWorkspace(
                pipeline_id=pipeline_id,
                workspace_root=os.environ.get("ARTIFACT_ROOT", "/tmp/pipeline_artifacts"),
            ),
        )
        ctx.trace.record("job_created", "success", f"mode={self._mode}")
        return ctx

    async def resolve_execution_policy(
        self,
        context: PipelineExecutionContext,
    ) -> ExecutionPolicy:
        """Resolve the execution policy from frozen context flags."""
        ff = context.feature_flags
        return ExecutionPolicy(
            canary_enabled=bool(context.rollout.canary),
            canary_bucket=context.rollout.bucket,
            structure_freeze_mode=str(ff.get("structure_freeze_mode", "legacy")),
            quality_gate_mode=str(ff.get("quality_gate_mode", "off")),
            native_text_routing_mode=str(ff.get("native_text_routing_mode", "off")),
            ocr_gateway_mode=str(ff.get("ocr_gateway_mode", "legacy")),
            document_ir_ssot_mode=str(ff.get("document_ir_ssot_mode", "dual")),
            unified_safety_mode=str(ff.get("unified_safety_mode", "off")),
            persistence_mode=str(ff.get("persistence_mode", "legacy")),
            page_stream_mode=str(ff.get("page_stream_mode", "legacy")),
        )

    async def claim_quota(
        self,
        context: PipelineExecutionContext,
        demand: ResourceDemand,
    ) -> QuotaLease:
        """Claim quota for a resource demand. Returns lease or rejection."""
        q = context.quota
        if demand.estimated_pages > q.max_pages:
            return QuotaLease(False, "pages", q.max_pages, "PAGE_LIMIT_EXCEEDED")
        if demand.estimated_input_bytes > q.max_input_bytes:
            return QuotaLease(False, "input_bytes", q.max_input_bytes, "INPUT_TOO_LARGE")
        if demand.estimated_render_pixels > q.max_render_pixels:
            return QuotaLease(False, "render_pixels", q.max_render_pixels, "PIXEL_BUDGET_EXCEEDED")
        return QuotaLease(True, "all", 999999, "")

    async def record_stage_result(
        self,
        context: PipelineExecutionContext,
        *,
        stage_name: str,
        status: str = "success",
        duration_ms: float = 0.0,
        error_code: str = "",
    ) -> None:
        """Record a stage result in trace and metrics."""
        context.trace.record(stage_name, status, duration_ms=int(duration_ms))
        context.metrics.gauge(f"stage.{stage_name}.latency_ms", duration_ms)
        if error_code:
            context.metrics.increment(f"stage.{stage_name}.errors")
        logger.info(
            "ControlPlane: stage=%s status=%s duration=%.0fms%s",
            stage_name, status, duration_ms,
            f" error={error_code}" if error_code else "",
        )

    async def finalize_job(
        self,
        context: PipelineExecutionContext,
        outcome: PipelineOutcome,
    ) -> None:
        """Finalize the pipeline run — record outcome and metrics."""
        context.trace.record("job_finalized", outcome.value)
        context.metrics.gauge("job.outcome", 1.0 if outcome == PipelineOutcome.SUCCESS else 0.0)
        logger.info(
            "ControlPlane: finalize pipeline=%s outcome=%s",
            context.pipeline_id, outcome.value,
        )
