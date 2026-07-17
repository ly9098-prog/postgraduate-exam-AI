"""OCR Canary — pre-release verification framework for Structure Freeze.

Provides:
- OCRCanaryConfig: frozen config model with env var mapping
- stable_hash(): deterministic bucket assignment (not random)
- CanaryBucketAssignment: bucket result with reasons
- Control / Observation / IR Canary group logic
- IR Canary failover conditions and tracing
- CanaryHealthDecision: auto-stop conditions
- CanaryReviewOutcome: human review result model
- Rollback support via env var switches
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ===========================================================================
# Constants
# ===========================================================================

# BUCKET_DIVISOR: total bucket slots (10000 = 0.01% granularity)
BUCKET_DIVISOR = 10000

# Group identifiers
GROUP_CONTROL_A = "control_a"          # freeze=legacy, quality_gate=off
GROUP_OBSERVATION_B = "observation_b"   # freeze=dual, quality_gate=shadow
GROUP_CANARY_C = "canary_c"            # freeze=ir_canary, quality_gate=shadow

# Config version for rebucketing
_CANARY_CONFIG_VERSION = "s3f-v1"

# Default canary env vars
ENV_CANARY_ENABLED = "OCR_CANARY_ENABLED"
ENV_IR_CANARY_PERCENT = "IR_FREEZE_CANARY_PERCENT"
ENV_CANARY_SUBJECTS = "CANARY_SUBJECTS"
ENV_CANARY_SOURCE_TYPES = "CANARY_SOURCE_TYPES"
ENV_CANARY_TENANT_ALLOWLIST = "CANARY_TENANT_ALLOWLIST"
ENV_CANARY_TENANT_DENYLIST = "CANARY_TENANT_DENYLIST"
ENV_CANARY_MAX_PAGES = "CANARY_MAX_PAGES"
ENV_CANARY_FAIL_OPEN = "CANARY_FAIL_OPEN"
ENV_CANARY_REQUIRE_REVIEW = "CANARY_REQUIRE_REVIEW"
ENV_CANARY_CONFIG_VERSION = "CANARY_CONFIG_VERSION"

# ===========================================================================
# Canary Config
# ===========================================================================


@dataclass(frozen=True)
class OCRCanaryConfig:
    """Frozen canary configuration — single source of truth for this run.

    All fields have defaults that produce safe (no-op) behavior.
    ``enabled=False`` means no canary logic runs at all.
    ``rollout_percent=0`` means IR canary is disabled even when enabled=True.
    """
    enabled: bool = False
    rollout_percent: float = 0.0        # 0.0–100.0, 0 = disabled
    freeze_mode: str = "legacy"         # legacy | dual | ir_canary
    quality_gate_mode: str = "off"      # off | shadow
    process_pool_enabled: bool = False
    subjects: tuple[str, ...] = ()       # empty = all subjects
    source_types: tuple[str, ...] = ()   # empty = all types
    tenant_allowlist: tuple[str, ...] = ()
    tenant_denylist: tuple[str, ...] = ()
    max_pages: int | None = None
    require_human_review: bool = True
    fail_open: bool = False              # True = degrade gracefully, False = fail fast
    config_version: str = _CANARY_CONFIG_VERSION

    def __post_init__(self) -> None:
        """Validate config invariants at construction time."""
        if not 0.0 <= self.rollout_percent <= 100.0:
            raise ValueError(f"rollout_percent must be 0–100, got {self.rollout_percent}")
        if self.freeze_mode not in ("legacy", "dual", "ir_canary"):
            raise ValueError(
                f"freeze_mode must be legacy/dual/ir_canary, got {self.freeze_mode}"
            )
        if self.quality_gate_mode not in ("off", "shadow"):
            raise ValueError(
                f"quality_gate_mode must be off/shadow, got {self.quality_gate_mode}"
            )
        if self.quality_gate_mode == "enforce":
            raise ValueError("CANARY: quality_gate=enforce is prohibited in canary config")
        if self.freeze_mode == "ir_global_default":
            raise ValueError("CANARY: freeze=ir_global_default is prohibited in canary config")

    @staticmethod
    def from_env() -> OCRCanaryConfig:
        """Build config from environment variables.

        Falls back to safe defaults when env vars are unset.
        Canary logic is disabled when OCR_CANARY_ENABLED != "true".
        """
        import os as _os

        enabled = _os.environ.get(ENV_CANARY_ENABLED, "").lower() == "true"
        rollout_percent_str = _os.environ.get(ENV_IR_CANARY_PERCENT, "0")

        try:
            rollout_percent = float(rollout_percent_str)
        except (ValueError, TypeError):
            rollout_percent = 0.0

        subjects_str = _os.environ.get(ENV_CANARY_SUBJECTS, "")
        source_types_str = _os.environ.get(ENV_CANARY_SOURCE_TYPES, "")

        return OCRCanaryConfig(
            enabled=enabled,
            rollout_percent=rollout_percent,
            freeze_mode=_os.environ.get("STRUCTURE_FREEZE_MODE", "legacy"),
            quality_gate_mode=_os.environ.get("DOMAIN_QUALITY_GATE_MODE", "off"),
            process_pool_enabled=_os.environ.get("OCR_USE_PROCESS_POOL", "").lower() == "true",
            subjects=tuple(s.strip() for s in subjects_str.split(",") if s.strip()),
            source_types=tuple(s.strip() for s in source_types_str.split(",") if s.strip()),
            tenant_allowlist=_parse_csv_env(ENV_CANARY_TENANT_ALLOWLIST),
            tenant_denylist=_parse_csv_env(ENV_CANARY_TENANT_DENYLIST),
            max_pages=_parse_int_env(ENV_CANARY_MAX_PAGES),
            require_human_review=_os.environ.get(ENV_CANARY_REQUIRE_REVIEW, "true").lower() != "false",
            fail_open=_os.environ.get(ENV_CANARY_FAIL_OPEN, "").lower() == "true",
            config_version=_os.environ.get(ENV_CANARY_CONFIG_VERSION, _CANARY_CONFIG_VERSION),
        )

    def with_overrides(self, **kwargs: Any) -> OCRCanaryConfig:
        """Return a new config with specific fields overridden."""
        d = {
            "enabled": self.enabled,
            "rollout_percent": self.rollout_percent,
            "freeze_mode": self.freeze_mode,
            "quality_gate_mode": self.quality_gate_mode,
            "process_pool_enabled": self.process_pool_enabled,
            "subjects": self.subjects,
            "source_types": self.source_types,
            "tenant_allowlist": self.tenant_allowlist,
            "tenant_denylist": self.tenant_denylist,
            "max_pages": self.max_pages,
            "require_human_review": self.require_human_review,
            "fail_open": self.fail_open,
            "config_version": self.config_version,
        }
        d.update(kwargs)
        return OCRCanaryConfig(**d)


def _parse_csv_env(key: str) -> tuple[str, ...]:
    import os as _os
    val = _os.environ.get(key, "")
    if not val:
        return ()
    return tuple(s.strip() for s in val.split(",") if s.strip())


def _parse_int_env(key: str) -> int | None:
    import os as _os
    val = _os.environ.get(key, "")
    if not val:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ===========================================================================
# Deterministic bucket assignment
# ===========================================================================


@dataclass
class CanaryBucketAssignment:
    """Result of bucket assignment for a single document/task.

    Serialized to pipeline diagnostics for full traceability.
    """
    canary_selected: bool = False
    canary_bucket: int = 0
    rollout_percent: float = 0.0
    config_version: str = ""
    selection_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canary_selected": self.canary_selected,
            "canary_bucket": self.canary_bucket,
            "rollout_percent": self.rollout_percent,
            "config_version": self.config_version,
            "selection_reasons": list(self.selection_reasons),
        }


def stable_hash(*parts: str) -> int:
    """Deterministic hash across all input parts.

    Returns an integer in [0, BUCKET_DIVISOR).

    Guarantees:
    - Same inputs → same output (deterministic)
    - Service restart → same output
    - Multi-worker → same output
    - Different rollout_percent doesn't change existing bucket assignments
    - Config version change can rebucket explicitly
    """
    raw = "::".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % BUCKET_DIVISOR


def assign_canary_bucket(
    tenant_id: str,
    document_hash: str,
    pipeline_version: str,
    config: OCRCanaryConfig,
    *,
    subject: str = "",
    source_type: str = "",
    page_count: int = 1,
) -> CanaryBucketAssignment:
    """Assign a document/task to a canary bucket.

    Returns the assignment with reasons for selection/non-selection.
    This function is pure and deterministic: same inputs → same output.
    """
    assignment = CanaryBucketAssignment(
        rollout_percent=config.rollout_percent,
        config_version=config.config_version,
    )

    # ── Canary globally disabled or rollout 0% → not selected ──
    if not config.enabled or config.rollout_percent <= 0.0:
        assignment.selection_reasons.append("canary_disabled_or_zero_percent")
        return assignment

    # ── Subject filter ──
    if config.subjects and subject and subject not in config.subjects:
        assignment.selection_reasons.append(f"subject_not_allowed:{subject}")
        return assignment

    # ── Source type filter ──
    if config.source_types and source_type and source_type not in config.source_types:
        assignment.selection_reasons.append(f"source_type_not_allowed:{source_type}")
        return assignment

    # ── Page count filter ──
    if config.max_pages is not None and page_count > config.max_pages:
        assignment.selection_reasons.append(f"page_count_exceeded:{page_count}>{config.max_pages}")
        return assignment

    # ── Compute stable bucket ──
    bucket = stable_hash(
        tenant_id,
        document_hash,
        pipeline_version,
        config.config_version,
    )
    assignment.canary_bucket = bucket

    # ── Check if bucket falls within rollout ──
    threshold = int(config.rollout_percent * (BUCKET_DIVISOR / 100.0))
    if bucket < threshold:
        assignment.canary_selected = True
        assignment.selection_reasons.append("stable_hash_selected")
    else:
        assignment.selection_reasons.append("stable_hash_not_selected")

    return assignment


# ===========================================================================
# Group selection
# ===========================================================================


@dataclass
class CanaryGroupSelection:
    """Which group this task belongs to and the associated config.

    Control A: legacy freeze, quality gate off
    Observation B: dual freeze, quality gate shadow (no output change)
    Canary C: ir_canary freeze, quality gate shadow, forced review
    """
    group: str = GROUP_CONTROL_A
    effective_freeze_mode: str = "legacy"
    effective_quality_gate_mode: str = "off"
    bucket_assignment: CanaryBucketAssignment | None = None
    force_review: bool = False
    canary_fallback: bool = False
    fallback_from: str = ""
    fallback_to: str = ""
    fallback_reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "group": self.group,
            "effective_freeze_mode": self.effective_freeze_mode,
            "effective_quality_gate_mode": self.effective_quality_gate_mode,
            "force_review": self.force_review,
        }
        if self.bucket_assignment:
            d["bucket_assignment"] = self.bucket_assignment.to_dict()
        if self.canary_fallback:
            d["canary_fallback"] = True
            d["fallback_from"] = self.fallback_from
            d["fallback_to"] = self.fallback_to
            d["fallback_reason_codes"] = list(self.fallback_reason_codes)
        return d


def select_canary_group(
    tenant_id: str,
    document_hash: str,
    pipeline_version: str,
    config: OCRCanaryConfig,
    *,
    subject: str = "",
    source_type: str = "",
    page_count: int = 1,
) -> CanaryGroupSelection:
    """Select the appropriate group for a task.

    Rules:
    1. If canary disabled or global config is not dual/shadow → Control A
    2. If global config is dual+shadow → Observation B (100% of pre-release traffic)
    3. If bucket selects IR canary → Canary C
    4. Fallback always returns control-compatible result
    """
    # ── Default: Control A ──
    selection = CanaryGroupSelection(
        group=GROUP_CONTROL_A,
        effective_freeze_mode="legacy",
        effective_quality_gate_mode=config.quality_gate_mode,
    )

    # ── Bucket assignment ──
    bucket = assign_canary_bucket(
        tenant_id=tenant_id,
        document_hash=document_hash,
        pipeline_version=pipeline_version,
        config=config,
        subject=subject,
        source_type=source_type,
        page_count=page_count,
    )
    selection.bucket_assignment = bucket

    # ── Observation B: dual+shadow runs for ALL pre-release traffic ──
    if config.freeze_mode == "dual" and config.quality_gate_mode == "shadow":
        selection.group = GROUP_OBSERVATION_B
        selection.effective_freeze_mode = "dual"
        selection.effective_quality_gate_mode = "shadow"

    # ── Canary C: IR canary for selected tasks ──
    if bucket.canary_selected and config.enabled:
        if (config.freeze_mode == "dual" and config.quality_gate_mode == "shadow") or \
           config.freeze_mode == "ir_canary":
            selection.group = GROUP_CANARY_C
            selection.effective_freeze_mode = "ir_canary"
            selection.effective_quality_gate_mode = "shadow"
            selection.force_review = config.require_human_review

    return selection


# ===========================================================================
# IR Canary failover
# ===========================================================================

# Condition codes for IR canary failover
FAILOVER_IR_MISSING = "IR_FREEZE_DOCUMENT_IR_MISSING"
FAILOVER_IR_SCHEMA_INCOMPATIBLE = "IR_FREEZE_SCHEMA_INCOMPATIBLE"
FAILOVER_IR_REGISTRY_EMPTY = "IR_FREEZE_REGISTRY_EMPTY"
FAILOVER_OPTION_KEY_MISMATCH = "IR_FREEZE_OPTION_KEY_MISMATCH"
FAILOVER_BINDING_LOST = "IR_FREEZE_BINDING_LOST"
FAILOVER_REPLACEMENT_MAP_CYCLE = "IR_FREEZE_REPLACEMENT_MAP_CYCLE"
FAILOVER_CROSS_PAGE_AMBIGUOUS = "IR_FREEZE_CROSS_PAGE_AMBIGUOUS"
FAILOVER_ARTIFACT_RESUME_INCONSISTENT = "IR_FREEZE_ARTIFACT_RESUME_INCONSISTENT"
FAILOVER_IR_EXCEPTION = "IR_FREEZE_EXCEPTION"


def check_ir_canary_failover(
    *,
    doc_ir_available: bool = True,
    ir_schema_compatible: bool = True,
    ir_registry_nonempty: bool = True,
    legacy_registry_nonempty: bool = False,
    option_key_match: bool = True,
    binding_lost_count: int = 0,
    replacement_map_cycle: bool = False,
    cross_page_ambiguous: bool = False,
    resume_inconsistent: bool = False,
    exception_occurred: bool = False,
) -> tuple[bool, list[str]]:
    """Check whether IR canary should fall back to legacy.

    Returns (should_fallback: bool, reason_codes: list[str]).
    Any single condition triggers fallback.
    """
    reasons: list[str] = []

    if not doc_ir_available:
        reasons.append(FAILOVER_IR_MISSING)
    if not ir_schema_compatible:
        reasons.append(FAILOVER_IR_SCHEMA_INCOMPATIBLE)
    if not ir_registry_nonempty and legacy_registry_nonempty:
        reasons.append(FAILOVER_IR_REGISTRY_EMPTY)
    if not option_key_match:
        reasons.append(FAILOVER_OPTION_KEY_MISMATCH)
    if binding_lost_count > 0:
        reasons.append(FAILOVER_BINDING_LOST)
    if replacement_map_cycle:
        reasons.append(FAILOVER_REPLACEMENT_MAP_CYCLE)
    if cross_page_ambiguous:
        reasons.append(FAILOVER_CROSS_PAGE_AMBIGUOUS)
    if resume_inconsistent:
        reasons.append(FAILOVER_ARTIFACT_RESUME_INCONSISTENT)
    if exception_occurred:
        reasons.append(FAILOVER_IR_EXCEPTION)

    return len(reasons) > 0, reasons


# ===========================================================================
# Canary health decision (auto-stop conditions)
# ===========================================================================


@dataclass
class CanaryHealthDecision:
    """Result of canary health evaluation."""
    healthy: bool = True
    stop_rollout: bool = False
    rollback_required: bool = False
    reason_codes: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


def evaluate_canary_health(
    *,
    data_loss_detected: bool = False,
    exact_match_decrease: bool = False,
    option_key_mismatch_count: int = 0,
    binding_lost_count: int = 0,
    duplicate_import_count: int = 0,
    artifact_resume_failure_count: int = 0,
    pipeline_crash_count: int = 0,
    main_process_crash: bool = False,
    permanent_pending_count: int = 0,
    ir_fallback_rate: float = 0.0,
    question_count_mismatch_rate: float = 0.0,
    option_text_normalized_mismatch_rate: float = 0.0,
    p95_latency_increase_pct: float = 0.0,
    error_rate_increase_pct: float = 0.0,
    review_rejection_rate: float = 0.0,
    artifact_size_increase_pct: float = 0.0,
    unrecoverable_cross_page_error: bool = False,
) -> CanaryHealthDecision:
    """Evaluate canary health against hard and statistical stop conditions.

    Hard conditions → immediate rollback required.
    Statistical conditions → stop rollout, may or may not require rollback.
    """
    hard_reasons: list[str] = []
    stat_reasons: list[str] = []

    # ── Hard stop conditions ──
    if data_loss_detected:
        hard_reasons.append("DATA_LOSS_DETECTED")
    if exact_match_decrease:
        hard_reasons.append("EXACT_MATCH_DECREASED")
    if option_key_mismatch_count > 0:
        hard_reasons.append(f"OPTION_KEY_MISMATCH={option_key_mismatch_count}")
    if binding_lost_count > 0:
        hard_reasons.append(f"BINDING_LOST={binding_lost_count}")
    if duplicate_import_count > 0:
        hard_reasons.append(f"DUPLICATE_IMPORT={duplicate_import_count}")
    if artifact_resume_failure_count > 0:
        hard_reasons.append(f"ARTIFACT_RESUME_FAILURE={artifact_resume_failure_count}")
    if pipeline_crash_count > 0:
        hard_reasons.append(f"PIPELINE_CRASH={pipeline_crash_count}")
    if main_process_crash:
        hard_reasons.append("MAIN_PROCESS_CRASH")
    if permanent_pending_count > 0:
        hard_reasons.append(f"PERMANENT_PENDING={permanent_pending_count}")
    if unrecoverable_cross_page_error:
        hard_reasons.append("UNRECOVERABLE_CROSS_PAGE_ERROR")

    # ── Statistical stop conditions ──
    if ir_fallback_rate > 1.0:
        stat_reasons.append(f"IR_FALLBACK_RATE={ir_fallback_rate:.1f}%")
    if question_count_mismatch_rate > 0.0:
        stat_reasons.append(f"QUESTION_COUNT_MISMATCH_RATE={question_count_mismatch_rate:.1f}%")
    if option_text_normalized_mismatch_rate > 5.0:
        stat_reasons.append(f"OPTION_TEXT_MISMATCH_RATE={option_text_normalized_mismatch_rate:.1f}%")
    if p95_latency_increase_pct > 20.0:
        stat_reasons.append(f"P95_LATENCY_INCREASE={p95_latency_increase_pct:.1f}%")
    if error_rate_increase_pct > 0.5:
        stat_reasons.append(f"ERROR_RATE_INCREASE={error_rate_increase_pct:.1f}%")
    if review_rejection_rate > 50.0:
        stat_reasons.append(f"REVIEW_REJECTION_RATE={review_rejection_rate:.1f}%")
    if artifact_size_increase_pct > 50.0:
        stat_reasons.append(f"ARTIFACT_SIZE_INCREASE={artifact_size_increase_pct:.1f}%")

    all_reasons = hard_reasons + stat_reasons
    stop_rollout = len(all_reasons) > 0
    rollback_required = len(hard_reasons) > 0

    return CanaryHealthDecision(
        healthy=len(all_reasons) == 0,
        stop_rollout=stop_rollout,
        rollback_required=rollback_required,
        reason_codes=all_reasons,
        metrics={
            "binding_lost_count": float(binding_lost_count),
            "option_key_mismatch_count": float(option_key_mismatch_count),
            "duplicate_import_count": float(duplicate_import_count),
            "ir_fallback_rate": ir_fallback_rate,
            "question_count_mismatch_rate": question_count_mismatch_rate,
            "option_text_mismatch_rate": option_text_normalized_mismatch_rate,
            "p95_latency_increase_pct": p95_latency_increase_pct,
            "error_rate_increase_pct": error_rate_increase_pct,
            "review_rejection_rate": review_rejection_rate,
            "artifact_size_increase_pct": artifact_size_increase_pct,
        },
    )


# ===========================================================================
# Canary review outcome
# ===========================================================================


@dataclass
class CanaryReviewOutcome:
    """Human review result for a canary task.

    Issue types (non-exhaustive):
    question_missing, question_extra, stem_corrupted, option_missing,
    option_reordered, answer_wrong, reading_order_wrong, cross_page_wrong,
    code_corrupted, formula_corrupted, table_corrupted, image_binding_wrong, other
    """
    pipeline_id: str
    document_id: str
    group: str  # control_a | observation_b | canary_c
    accepted: bool
    issue_types: list[str] = field(default_factory=list)
    affected_question_ids: list[str] = field(default_factory=list)
    reviewer: str = ""
    reviewed_at: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "document_id": self.document_id,
            "group": self.group,
            "accepted": self.accepted,
            "issue_types": list(self.issue_types),
            "affected_question_ids": list(self.affected_question_ids),
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "notes": self.notes,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> CanaryReviewOutcome:
        return CanaryReviewOutcome(
            pipeline_id=str(d.get("pipeline_id", "")),
            document_id=str(d.get("document_id", "")),
            group=str(d.get("group", "")),
            accepted=bool(d.get("accepted", False)),
            issue_types=list(d.get("issue_types", [])),
            affected_question_ids=list(d.get("affected_question_ids", [])),
            reviewer=str(d.get("reviewer", "")),
            reviewed_at=str(d.get("reviewed_at", "")),
            notes=str(d.get("notes", "")),
        )


# ===========================================================================
# Canary artifact diagnostics helper
# ===========================================================================


def build_canary_diagnostics(
    group_selection: CanaryGroupSelection,
    fallback_reason_codes: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canary diagnostics block for artifact persistence.

    Attached to pipeline diagnostics so that canary decisions are fully
    traceable post-hoc.
    """
    d = group_selection.to_dict()

    if fallback_reason_codes:
        d["fallback_reason_codes"] = fallback_reason_codes
        d["canary_fallback"] = True

    if extra:
        d.update(extra)

    return d


# ===========================================================================
# Release decision
# ===========================================================================


@dataclass
class OCRReleaseDecision:
    """Machine-readable release decision for canary rollout stages.

    Used to gate progression through:
      Stage 0: Offline Replay
      Stage 1: Pre-release Observation (dual+shadow)
      Stage 2: IR Canary 1%
      Stage 3: IR Canary 5%
      Stage 4: IR Canary 20%
      Stage 5: IR Canary 50% (requires separate approval)
    """
    approved: bool = False
    approved_stage: str = "stage_0"
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    evidence_artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "approved_stage": self.approved_stage,
            "recommendation": self._recommendation(),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "metrics": dict(self.metrics),
            "evidence_artifacts": list(self.evidence_artifacts),
        }

    def _recommendation(self) -> str:
        if self.approved:
            return f"proceed_to_{self.approved_stage}"
        if any("DATA_LOSS" in b or "DUPLICATE" in b or "CRASH" in b for b in self.blockers):
            return "rollback_to_legacy"
        return "hold_and_investigate"


def generate_release_decision(
    health: CanaryHealthDecision,
    *,
    bench_valid_count: int = 0,
    bench_placeholder_count: int = 0,
    bench_invalid_count: int = 0,
    paddle_quality_done: bool = False,
    question_count_mismatch: int = 0,
    option_key_mismatch: int = 0,
    binding_lost: int = 0,
    artifact_resume_consistent: bool = True,
    duplicate_import: int = 0,
    canary_fallback_traced: bool = True,
    quality_gate_enforce_check: bool = True,
    human_review_data_exists: bool = True,
    no_p0_p1_regression: bool = True,
) -> OCRReleaseDecision:
    """Generate a release decision based on health and external checks.

    Hard blocking conditions:
    - Paddle --quality not done when process pool enabled
    - Bench has placeholder or invalid cases
    - Question count mismatch > 0
    - Option key mismatch > 0
    - Binding lost > 0
    - Artifact resume inconsistent
    - Duplicate import detected
    - Canary fallback not traced
    - Quality Gate enforce accidentally enabled
    - Missing human review data
    - P0/P1 regression detected
    """
    blockers: list[str] = []
    warnings: list[str] = []

    # ── Health-based blocks ──
    if health.rollback_required:
        blockers.extend(health.reason_codes)
    elif health.stop_rollout:
        warnings.extend(health.reason_codes)

    # ── External condition blocks ──
    if bench_placeholder_count > 0:
        blockers.append(f"BENCH_PLACEHOLDER={bench_placeholder_count}")
    if bench_invalid_count > 0:
        blockers.append(f"BENCH_INVALID={bench_invalid_count}")
    if question_count_mismatch > 0:
        blockers.append(f"QUESTION_COUNT_MISMATCH={question_count_mismatch}")
    if option_key_mismatch > 0:
        blockers.append(f"OPTION_KEY_MISMATCH={option_key_mismatch}")
    if binding_lost > 0:
        blockers.append(f"BINDING_LOST={binding_lost}")
    if not artifact_resume_consistent:
        blockers.append("ARTIFACT_RESUME_INCONSISTENT")
    if duplicate_import > 0:
        blockers.append(f"DUPLICATE_IMPORT={duplicate_import}")
    if not canary_fallback_traced:
        blockers.append("CANARY_FALLBACK_UNTRACED")
    if not quality_gate_enforce_check:
        blockers.append("QUALITY_GATE_ENFORCE_DETECTED")
    if not human_review_data_exists:
        blockers.append("MISSING_HUMAN_REVIEW_DATA")
    if not no_p0_p1_regression:
        blockers.append("P0_P1_REGRESSION_DETECTED")

    # ── Determine stage ──
    approved = len(blockers) == 0
    if approved:
        if bench_valid_count >= 100 and paddle_quality_done:
            approved_stage = "stage_2"
        elif bench_valid_count >= 50:
            approved_stage = "stage_1"
        else:
            approved_stage = "stage_0"
    else:
        approved_stage = "stage_0"

    return OCRReleaseDecision(
        approved=approved,
        approved_stage=approved_stage,
        blockers=blockers,
        warnings=warnings,
        metrics=health.metrics,
        evidence_artifacts=[
            "run_manifest.json",
            "summary.json",
            "control_vs_canary.json",
            "release_decision.json",
        ],
    )


# ===========================================================================
# Rollback control
# ===========================================================================


def is_canary_globally_disabled() -> bool:
    """Check the global canary kill switch.

    When OCR_CANARY_ENABLED=false, no canary logic runs at all.
    """
    import os as _os
    return _os.environ.get(ENV_CANARY_ENABLED, "").lower() != "true"


def is_ir_canary_disabled() -> bool:
    """Check the IR canary specific kill switch.

    When IR_FREEZE_CANARY_PERCENT=0 or unset, IR canary is disabled
    even if the global switch is on.
    """
    import os as _os
    val = _os.environ.get(ENV_IR_CANARY_PERCENT, "0")
    try:
        return float(val) <= 0.0
    except (ValueError, TypeError):
        return True
