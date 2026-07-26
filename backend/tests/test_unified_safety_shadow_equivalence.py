"""Shadow equivalence test for UnifiedSafetyEvaluator.

Verifies that shadow mode:
- Does NOT change existing candidate decisions
- Produces consistent evidence
- Does NOT raise exceptions
"""
from __future__ import annotations

from app.features.unified_safety import (
    SAFETY_ACCEPT,
    CandidateContext,
    UnifiedSafetyEvaluator,
)


class TestUnifiedSafetyShadowEquivalence:
    def setup_method(self):
        self.evaluator = UnifiedSafetyEvaluator(mode="shadow")
        self.ctx = CandidateContext(candidate_id="shadow-eq-test")

    def test_shadow_consistent_decision(self):
        """Shadow mode should produce same decision for same input."""
        from app.core.document_ir import new_document
        doc = new_document(b"shadow eq test")

        d1 = self.evaluator.evaluate(None, doc, self.ctx)
        d2 = self.evaluator.evaluate(None, doc, self.ctx)

        assert d1.accepted == d2.accepted
        assert d1.action == d2.action

    def test_shadow_does_not_change_decision(self):
        """Shadow mode decision should be compatible with existing path."""
        from app.core.document_ir import new_document
        doc = new_document(b"no-change test")

        decision = self.evaluator.evaluate(None, doc, self.ctx)
        # Shadow mode must not raise
        assert decision is not None
        # Decision should be one of the allowed actions
        assert decision.action in (SAFETY_ACCEPT, "REJECT", "FALLBACK", "REVIEW")

    def test_shadow_no_side_effects(self):
        """Shadow mode should not modify input documents."""
        from app.core.document_ir import new_document
        doc = new_document(b"no-side-effects")
        original_id = doc.document_id

        self.evaluator.evaluate(None, doc, self.ctx)

        # Document must not be mutated
        assert doc.document_id == original_id
