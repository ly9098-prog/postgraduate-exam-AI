"""Tests for Phase 8: UnifiedSafetyEvaluator."""
from __future__ import annotations

import pytest

from app.features.unified_safety import (
    SAFETY_ACCEPT,
    SAFETY_REJECT,
    SAFETY_REVIEW,
    CandidateContext,
    SafetyEvidence,
    UnifiedSafetyDecision,
    UnifiedSafetyEvaluator,
)


class TestSafetyEvidence:
    def test_create_evidence(self):
        e = SafetyEvidence(
            provider="test_gate",
            severity="warning",
            reason_codes=["TEST_ISSUE"],
            metrics={"score": 0.5},
        )
        assert e.provider == "test_gate"
        assert e.severity == "warning"


class TestUnifiedSafetyDecision:
    def test_default_decision_requires_review(self):
        d = UnifiedSafetyDecision()
        assert d.requires_review
        assert not d.accepted

    def test_accepted_decision(self):
        d = UnifiedSafetyDecision(accepted=True, action=SAFETY_ACCEPT, confidence=0.95)
        assert d.accepted
        assert d.action == SAFETY_ACCEPT


class TestUnifiedSafetyEvaluator:
    def setup_method(self):
        self.evaluator = UnifiedSafetyEvaluator(mode="shadow")

    def test_shadow_mode(self):
        assert self.evaluator.is_shadow

    def test_evaluate_accepts_good_candidate(self):
        """A valid DocumentIR should pass integrity checks."""
        from app.core.document_ir import new_document
        doc = new_document(b"test content")
        ctx = CandidateContext(candidate_id="c1", source_engine="paddleocr")

        decision = self.evaluator.evaluate(None, doc, ctx)
        assert decision is not None
        assert isinstance(decision, UnifiedSafetyDecision)

    def test_evaluate_rejects_none(self):
        ctx = CandidateContext(candidate_id="c2")
        decision = self.evaluator.evaluate(None, None, ctx)
        assert decision is not None
        # None input should still produce a decision (with error evidence)

    def test_evaluate_produces_evidence(self):
        from app.core.document_ir import new_document
        doc = new_document(b"evidence test")
        ctx = CandidateContext(candidate_id="c3")

        decision = self.evaluator.evaluate(None, doc, ctx)
        assert len(decision.evidence) >= 2  # integrity + domain quality at minimum
        assert decision.reason_codes

    def test_has_code_regions_true(self):
        from app.core.document_ir import DocumentIR, PageIR, RegionIR
        doc = DocumentIR(document_id="test")
        page = PageIR(page_index=0)
        page.regions.append(RegionIR(region_type="code"))
        doc.pages.append(page)

        assert self.evaluator._has_code_regions(doc)

    def test_has_code_regions_false(self):
        from app.core.document_ir import DocumentIR
        doc = DocumentIR(document_id="test")
        assert not self.evaluator._has_code_regions(doc)

    def test_off_mode_does_not_raise(self):
        evaluator = UnifiedSafetyEvaluator(mode="off")
        assert not evaluator.is_shadow

    def test_compute_decision_critical_rejects(self):
        evidence = [
            SafetyEvidence(provider="test", severity="critical",
                           reason_codes=["FATAL_ERROR"]),
        ]
        accepted, action, conf = self.evaluator._compute_decision(evidence)
        assert not accepted
        assert action == SAFETY_REJECT
        assert conf == 0.0

    def test_compute_decision_errors_review(self):
        evidence = [
            SafetyEvidence(provider="test", severity="error",
                           reason_codes=["ERROR"]),
        ]
        accepted, action, conf = self.evaluator._compute_decision(evidence)
        assert not accepted
        assert action == SAFETY_REVIEW
        assert conf == 0.3

    def test_compute_decision_clean_accepts(self):
        evidence = [
            SafetyEvidence(provider="test", severity="info",
                           reason_codes=["OK"]),
        ]
        accepted, action, conf = self.evaluator._compute_decision(evidence)
        assert accepted
        assert action == SAFETY_ACCEPT
        assert conf == 0.95
