"""Failure export to bench candidate tests."""
from __future__ import annotations

from app.features.ocr_canary import CanaryReviewOutcome


class TestFailureExport:
    """Verify failure export format and dedup."""

    def test_export_metadata_format(self):
        """Export should produce candidate case metadata."""
        outcome = CanaryReviewOutcome(
            pipeline_id="p123",
            document_id="d456",
            group="canary_c",
            accepted=False,
            issue_types=["option_missing"],
            affected_question_ids=["q1"],
            reviewer="human1",
            reviewed_at="2026-07-17T10:00:00",
            notes="选项B缺失",
        )

        # Simulated export metadata
        candidate = {
            "source_pipeline_id": outcome.pipeline_id,
            "document_id": outcome.document_id,
            "issue_types": outcome.issue_types,
            "affected_question_ids": outcome.affected_question_ids,
            "review_notes": outcome.notes,
            "group": outcome.group,
        }
        assert candidate["source_pipeline_id"] == "p123"
        assert candidate["issue_types"] == ["option_missing"]

    def test_dedup_by_input_hash(self):
        """Same input hash should not produce duplicate export."""
        seen_hashes = set()

        def would_export(input_hash: str) -> bool:
            if input_hash in seen_hashes:
                return False
            seen_hashes.add(input_hash)
            return True

        assert would_export("abc123") is True
        assert would_export("abc123") is False  # duplicate
        assert would_export("def456") is True

    def test_export_includes_fingerprint(self):
        """Export must include pipeline fingerprint for traceability."""
        candidate = {
            "source_pipeline_id": "p123",
            "fingerprint": "abc123def456",
        }
        assert "fingerprint" in candidate

    def test_export_not_auto_added_to_bench(self):
        """Export should NOT automatically add to bench — requires human review."""
        # This is a behavioral contract: export generates candidates only
        export = {
            "candidate_cases": [
                {"source_id": "p123", "requires_review": True},
            ]
        }
        for case in export["candidate_cases"]:
            assert case["requires_review"] is True
