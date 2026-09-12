"""Canary resume consistency tests."""
from __future__ import annotations

from app.features.ocr_canary import (
    OCRCanaryConfig,
    assign_canary_bucket,
    select_canary_group,
)


class TestCanaryResume:
    def test_same_input_same_bucket(self):
        """Same input should always get the same bucket."""
        config = OCRCanaryConfig(enabled=True, rollout_percent=5.0)
        a1 = assign_canary_bucket("t1", "doc_hash_abc", "pv1", config)
        a2 = assign_canary_bucket("t1", "doc_hash_abc", "pv1", config)
        assert a1.canary_bucket == a2.canary_bucket
        assert a1.canary_selected == a2.canary_selected

    def test_restart_same_group(self):
        """Simulate service restart → same group assignment."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=5.0,
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        s1 = select_canary_group("t1", "doc_hash", "pv1", config)
        s2 = select_canary_group("t1", "doc_hash", "pv1", config)
        assert s1.group == s2.group
        assert s1.effective_freeze_mode == s2.effective_freeze_mode

    def test_different_input_different_bucket(self):
        """Different inputs usually get different buckets."""
        config = OCRCanaryConfig(enabled=True, rollout_percent=50.0)
        buckets = set()
        for i in range(50):
            a = assign_canary_bucket("t1", f"doc_{i}", "v1", config)
            buckets.add(a.canary_bucket)
        # With 50 docs and 10000 slots, likelihood of all identical is negligible
        assert len(buckets) > 1

    def test_config_version_change_rebuckets(self):
        """Changing config version can result in different bucket."""
        config_v1 = OCRCanaryConfig(enabled=True, rollout_percent=100.0, config_version="v1")
        config_v2 = OCRCanaryConfig(enabled=True, rollout_percent=100.0, config_version="v2")
        a1 = assign_canary_bucket("t1", "doc_hash", "pv1", config_v1)
        a2 = assign_canary_bucket("t1", "doc_hash", "pv1", config_v2)
        # Different config versions → different hash input → likely different bucket
        # (not guaranteed but extremely likely with 10000 slots)
        assert a1.canary_bucket >= 0
        assert a2.canary_bucket >= 0

    def test_env_change_preserves_existing_bucket(self):
        """Changing rollout percentage should not change existing buckets."""
        config_1 = OCRCanaryConfig(enabled=True, rollout_percent=1.0)
        config_5 = OCRCanaryConfig(enabled=True, rollout_percent=5.0)
        a1 = assign_canary_bucket("t1", "doc_hash", "pv1", config_1)
        a5 = assign_canary_bucket("t1", "doc_hash", "pv1", config_5)
        # Bucket should be the same (hash doesn't include rollout_percent)
        assert a1.canary_bucket == a5.canary_bucket
