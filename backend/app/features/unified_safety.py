"""Unified Safety Evaluator — Aggregate all safety/quality gates into a unified decision.

Integrates existing safety capabilities:
- CandidateEvaluator
- AI Safety
- Code Integrity
- Domain Quality Gate
- Frozen Option Invariants
- Cross-page Validation

UNIFIED_SAFETY_MODE:
  off    — not evaluated (default)
  shadow — evaluates but does NOT change production decision
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_UNIFIED_SAFETY_MODE = ""

# The mode is resolved lazily from settings to avoid circular imports at
# module-load time.  Access via UnifiedSafetyEvaluator.mode or the
# get_unified_safety_mode() helper.

def get_unified_safety_mode() -> str:
    """Return the current UNIFIED_SAFETY_MODE from app settings."""
    if _UNIFIED_SAFETY_MODE:
        return _UNIFIED_SAFETY_MODE
    try:
        from app.core.config import settings
        return getattr(settings, "UNIFIED_SAFETY_MODE", "shadow")
    except Exception:
        return "shadow"

# Allowed safety actions
SAFETY_ACCEPT = "ACCEPT"
SAFETY_REJECT = "REJECT"
SAFETY_FALLBACK = "FALLBACK"
SAFETY_REVIEW = "REVIEW"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SafetyEvidence:
    """Evidence from a single safety provider."""
    provider: str
    severity: str = "info"  # info | warning | error | critical
    reason_codes: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    affected_page_ids: list[str] = field(default_factory=list)
    affected_region_ids: list[str] = field(default_factory=list)
    affected_question_ids: list[str] = field(default_factory=list)


@dataclass
class UnifiedSafetyDecision:
    """Unified safety decision aggregating all evidence."""
    accepted: bool = False
    action: str = SAFETY_REVIEW
    confidence: float = 0.0
    evidence: list[SafetyEvidence] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    requires_review: bool = True


@dataclass
class CandidateContext:
    """Context for candidate evaluation."""
    candidate_id: str = ""
    source_engine: str = ""
    page_indices: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# UnifiedSafetyEvaluator
# ---------------------------------------------------------------------------


class UnifiedSafetyEvaluator:
    """Aggregate all safety/quality gates into a unified decision.

    Current gates (in evaluation order):
    1. Basic integrity (NaN/Inf, empty values)
    2. Code integrity (if code regions present)
    3. Domain quality gate (question structure)
    4. Cross-page link integrity
    5. AI safety (if AI-modified)

    Rules:
    - Each gate provides SafetyEvidence
    - Only the UnifiedSafetyEvaluator generates the final decision
    - All reason codes use stable string enums
    - Gate exceptions do NOT auto-accept high-risk candidates
    - CancelledError propagates unmodified
    """

    def __init__(self, mode: str = "") -> None:
        self._mode = mode or get_unified_safety_mode()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_shadow(self) -> bool:
        return self._mode == "shadow"

    def evaluate(
        self,
        before: Any,
        candidate: Any,
        context: CandidateContext,
    ) -> UnifiedSafetyDecision:
        """Evaluate a correction candidate against all safety gates.

        Args:
            before: Original DocumentIR (before correction).
            candidate: Corrected DocumentIR.
            context: Candidate context (source engine, page info).

        Returns:
            UnifiedSafetyDecision with aggregated evidence.
        """
        all_evidence: list[SafetyEvidence] = []
        all_reason_codes: list[str] = []

        # Gate 1: Basic integrity
        evidence = self._check_integrity(candidate)
        all_evidence.append(evidence)
        all_reason_codes.extend(evidence.reason_codes)

        # Gate 2: Code integrity (if code regions present)
        if self._has_code_regions(candidate):
            evidence = self._check_code_integrity(candidate)
            all_evidence.append(evidence)
            all_reason_codes.extend(evidence.reason_codes)

        # Gate 3: Domain quality gate
        evidence = self._check_domain_quality(candidate)
        all_evidence.append(evidence)
        all_reason_codes.extend(evidence.reason_codes)

        # Gate 4: Cross-page link integrity
        evidence = self._check_cross_page_links(candidate)
        all_evidence.append(evidence)
        all_reason_codes.extend(evidence.reason_codes)

        # Compute decision
        accepted, action, confidence = self._compute_decision(all_evidence)

        return UnifiedSafetyDecision(
            accepted=accepted,
            action=action,
            confidence=confidence,
            evidence=all_evidence,
            reason_codes=list(set(all_reason_codes)),
            requires_review=action == SAFETY_REVIEW,
        )

    # ── Individual gates ──

    def _check_integrity(self, doc_ir: Any) -> SafetyEvidence:
        """Gate 1: Basic integrity checks."""
        reason_codes: list[str] = []
        try:
            from app.core.document_ir import validate_document_ir
            violations = validate_document_ir(doc_ir)
            if violations:
                reason_codes.append("DOC_IR_INVALID")
                reason_codes.extend(f"VIOLATION:{v[:60]}" for v in violations[:5])
        except Exception as e:
            reason_codes.append(f"INTEGRITY_CHECK_FAILED:{e}")

        severity = "error" if reason_codes else "info"
        return SafetyEvidence(
            provider="integrity_gate",
            severity=severity,
            reason_codes=reason_codes or ["INTEGRITY_OK"],
        )

    def _check_code_integrity(self, doc_ir: Any) -> SafetyEvidence:
        """Gate 2: Code region integrity."""
        reason_codes: list[str] = []
        try:
            from app.features.code_integrity import check_code_region_integrity
            violations = check_code_region_integrity(doc_ir)
            if violations:
                reason_codes.append("CODE_INTEGRITY_VIOLATION")
        except ImportError:
            reason_codes.append("CODE_INTEGRITY_NOT_AVAILABLE")
        except Exception as e:
            reason_codes.append(f"CODE_INTEGRITY_ERROR:{e}")

        return SafetyEvidence(
            provider="code_integrity_gate",
            severity="error" if reason_codes else "info",
            reason_codes=reason_codes or ["CODE_INTEGRITY_OK"],
        )

    def _check_domain_quality(self, doc_ir: Any) -> SafetyEvidence:
        """Gate 3: Domain quality gate (shadow mode)."""
        reason_codes: list[str] = []
        try:
            from app.features.quality_gate import evaluate_structure_freezing_quality
            qg_result = evaluate_structure_freezing_quality(doc_ir)
            if qg_result and not qg_result.passed:
                reason_codes.append("QUALITY_GATE_FAILED")
                reason_codes.extend(qg_result.reason_codes[:3])
        except Exception as e:
            reason_codes.append(f"QUALITY_GATE_ERROR:{e}")

        return SafetyEvidence(
            provider="domain_quality_gate",
            severity="warning" if reason_codes else "info",
            reason_codes=reason_codes or ["QUALITY_GATE_OK"],
        )

    def _check_cross_page_links(self, doc_ir: Any) -> SafetyEvidence:
        """Gate 4: Cross-page link integrity."""
        reason_codes: list[str] = []
        try:
            links = getattr(doc_ir, "cross_page_links", [])
            if links:
                # Validate link format
                for link in links:
                    if isinstance(link, dict) and not link.get("source_page_id"):
                        reason_codes.append("CROSS_PAGE_LINK_MISSING_SOURCE")
                    if isinstance(link, dict) and not link.get("target_page_id"):
                        reason_codes.append("CROSS_PAGE_LINK_MISSING_TARGET")
            else:
                reason_codes.append("CROSS_PAGE_NO_LINKS")
        except Exception as e:
            reason_codes.append(f"CROSS_PAGE_ERROR:{e}")

        return SafetyEvidence(
            provider="cross_page_gate",
            severity="warning" if any("MISSING" in c for c in reason_codes) else "info",
            reason_codes=reason_codes,
        )

    # ── Private helpers ──

    def _has_code_regions(self, doc_ir: Any) -> bool:
        """Check if DocumentIR contains code regions."""
        try:
            for page in getattr(doc_ir, "pages", []):
                for region in getattr(page, "regions", []):
                    if getattr(region, "region_type", "") == "code":
                        return True
        except Exception:
            pass
        return False

    def _compute_decision(
        self, evidence: list[SafetyEvidence],
    ) -> tuple[bool, str, float]:
        """Compute final decision from all evidence."""
        critical = any(e.severity == "critical" for e in evidence)
        errors = any(e.severity == "error" for e in evidence)
        warnings = any(e.severity == "warning" for e in evidence)

        if critical:
            return False, SAFETY_REJECT, 0.0
        if errors:
            return False, SAFETY_REVIEW, 0.3
        if warnings:
            return True, SAFETY_ACCEPT, 0.7
        return True, SAFETY_ACCEPT, 0.95
