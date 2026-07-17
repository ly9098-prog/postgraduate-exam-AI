"""Deterministic bucket assignment tests."""
from __future__ import annotations

import hashlib

import pytest

from app.features.ocr_canary import (
    BUCKET_DIVISOR,
    OCRCanaryConfig,
    assign_canary_bucket,
    stable_hash,
)


class TestStableHash:
    def test_deterministic(self):
        """Same inputs → same output."""
        assert stable_hash("tenant1", "doc1", "v1", "cfg1") == stable_hash("tenant1", "doc1", "v1", "cfg1")

    def test_different_inputs_different_output(self):
        h1 = stable_hash("tenant1", "doc1", "v1", "cfg1")
        h2 = stable_hash("tenant2", "doc1", "v1", "cfg1")
        assert h1 != h2

    def test_in_range(self):
        for _ in range(100):
            h = stable_hash("a", "b", "c", "d")
            assert 0 <= h < BUCKET_DIVISOR

    def test_different_config_version_changes_bucket(self):
        h1 = stable_hash("t", "d", "v", "cfg1")
        h2 = stable_hash("t", "d", "v", "cfg2")
        assert h1 != h2

    def test_restart_same(self):
        """Simulate restart by recomputing."""
        h1 = stable_hash("tenant_a", "doc_xyz", "v2.1", "s3f-v1")
        h2 = stable_hash("tenant_a", "doc_xyz", "v2.1", "s3f-v1")
        assert h1 == h2


class TestAssignCanaryBucket:
    def test_disabled_no_selection(self):
        config = OCRCanaryConfig(enabled=False)
        assignment = assign_canary_bucket("t", "d", "v", config)
        assert assignment.canary_selected is False
        assert "canary_disabled_or_zero_percent" in assignment.selection_reasons

    def test_zero_percent_no_selection(self):
        config = OCRCanaryConfig(enabled=True, rollout_percent=0.0)
        assignment = assign_canary_bucket("t", "d", "v", config)
        assert assignment.canary_selected is False

    def test_subject_filter(self):
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=100.0,
            subjects=("exam408",),
        )
        assignment = assign_canary_bucket("t", "d", "v", config, subject="math2")
        assert assignment.canary_selected is False
        assert any("subject_not_allowed" in r for r in assignment.selection_reasons)

    def test_subject_allowed(self):
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=100.0,
            subjects=("exam408",),
        )
        assignment = assign_canary_bucket("t", "d", "v", config, subject="exam408")
        assert assignment.canary_selected is True

    def test_source_type_filter(self):
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=100.0,
            source_types=("pdf",),
        )
        assignment = assign_canary_bucket("t", "d", "v", config, source_type="png")
        assert assignment.canary_selected is False
        assert any("source_type_not_allowed" in r for r in assignment.selection_reasons)

    def test_page_count_filter(self):
        config = OCRCanaryConfig(enabled=True, rollout_percent=100.0, max_pages=5)
        assignment = assign_canary_bucket("t", "d", "v", config, page_count=10)
        assert assignment.canary_selected is False

    def test_page_count_allowed(self):
        config = OCRCanaryConfig(enabled=True, rollout_percent=100.0, max_pages=5)
        assignment = assign_canary_bucket("t", "d", "v", config, page_count=3)
        assert assignment.canary_selected is True

    def test_rollout_expansion_monotonicity(self):
        """Increasing rollout percentage should not remove already-selected tasks."""
        config_1pct = OCRCanaryConfig(enabled=True, rollout_percent=1.0)
        config_5pct = OCRCanaryConfig(enabled=True, rollout_percent=5.0)

        # Test with 1000 different inputs
        selected_at_1 = set()
        selected_at_5 = set()
        for i in range(1000):
            doc_hash = f"doc_{i}"
            a1 = assign_canary_bucket("tenant", doc_hash, "v1", config_1pct)
            a5 = assign_canary_bucket("tenant", doc_hash, "v1", config_5pct)
            if a1.canary_selected:
                selected_at_1.add(doc_hash)
            if a5.canary_selected:
                selected_at_5.add(doc_hash)

        # All docs selected at 1% should also be selected at 5%
        assert selected_at_1.issubset(selected_at_5), "Rollout expansion should not remove existing selections"

    def test_same_bucket_on_retry(self):
        """Same document gets same bucket on retry."""
        config = OCRCanaryConfig(enabled=True, rollout_percent=5.0)
        a1 = assign_canary_bucket("t1", "doc_hash_abc", "v2", config)
        a2 = assign_canary_bucket("t1", "doc_hash_abc", "v2", config)
        assert a1.canary_bucket == a2.canary_bucket
        assert a1.canary_selected == a2.canary_selected

    def test_reason_codes_present(self):
        config = OCRCanaryConfig(enabled=True, rollout_percent=5.0)
        assignment = assign_canary_bucket("t1", "doc_hash", "v1", config)
        assert len(assignment.selection_reasons) > 0

    def test_bucket_serializable(self):
        config = OCRCanaryConfig(enabled=True, rollout_percent=5.0)
        assignment = assign_canary_bucket("t1", "d", "v1", config)
        d = assignment.to_dict()
        assert "canary_selected" in d
        assert "canary_bucket" in d
        assert "rollout_percent" in d
        assert "config_version" in d
        assert "selection_reasons" in d

    def test_multi_worker_consistency(self):
        """Multiple workers should produce the same assignment (simulated via hashing)."""
        config = OCRCanaryConfig(enabled=True, rollout_percent=3.0)
        a1 = assign_canary_bucket("tenant_xyz", "doc_001", "v1", config,
                                   subject="exam408", source_type="pdf", page_count=5)
        a2 = assign_canary_bucket("tenant_xyz", "doc_001", "v1", config,
                                   subject="exam408", source_type="pdf", page_count=5)
        assert a1.canary_bucket == a2.canary_bucket
        assert a1.canary_selected == a2.canary_selected
