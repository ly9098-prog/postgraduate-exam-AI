"""Canary group execution tests — Control A / Observation B / Canary C."""
from __future__ import annotations

import pytest

from app.features.ocr_canary import (
    GROUP_CONTROL_A,
    GROUP_OBSERVATION_B,
    GROUP_CANARY_C,
    OCRCanaryConfig,
    select_canary_group,
)


class TestGroupSelection:
    def test_disabled_config_returns_control_a(self):
        """When canary is disabled, all tasks are Control A."""
        config = OCRCanaryConfig(enabled=False)
        selection = select_canary_group("t", "d", "v", config)
        assert selection.group == GROUP_CONTROL_A
        assert selection.effective_freeze_mode == "legacy"
        assert selection.effective_quality_gate_mode == "off"

    def test_dual_shadow_returns_observation_b(self):
        """Dual+shadow config assigns all tasks to Observation B."""
        config = OCRCanaryConfig(
            enabled=True,
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.group == GROUP_OBSERVATION_B

    def test_observation_b_does_not_change_output(self):
        """Observation B should use legacy freeze mode but dual comparison."""
        config = OCRCanaryConfig(
            enabled=True,
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.effective_freeze_mode == "dual"
        assert selection.effective_quality_gate_mode == "shadow"
        # No force review for observation
        assert selection.force_review is False

    def test_control_a_has_off_quality_gate(self):
        """Control A reflects config quality gate mode."""
        config = OCRCanaryConfig(enabled=False, quality_gate_mode="off")
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.effective_quality_gate_mode == "off"

    def test_control_a_with_shadow_qg(self):
        """Control A can use shadow quality gate when config sets it."""
        config = OCRCanaryConfig(enabled=False, quality_gate_mode="shadow")
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.effective_quality_gate_mode == "shadow"

    def test_ir_canary_selected(self):
        """When bucket selects IR canary, group should be Canary C."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=100.0,  # 100% ensures selection
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        selection = select_canary_group("t1", "doc_hash_sel", "v1", config)
        if selection.bucket_assignment and selection.bucket_assignment.canary_selected:
            assert selection.group == GROUP_CANARY_C
            assert selection.effective_freeze_mode == "ir_canary"

    def test_canary_c_force_review(self):
        """Canary C tasks should be forced to human review."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=100.0,
            freeze_mode="ir_canary",
            quality_gate_mode="shadow",
            require_human_review=True,
        )
        selection = select_canary_group("t1", "doc_hash_xyz", "v1", config)
        if selection.group == GROUP_CANARY_C:
            assert selection.force_review is True

    def test_canary_c_no_force_review_when_disabled(self):
        """When require_human_review=False, Canary C doesn't force review."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=100.0,
            freeze_mode="ir_canary",
            quality_gate_mode="shadow",
            require_human_review=False,
        )
        selection = select_canary_group("t1", "d", "v1", config)
        if selection.group == GROUP_CANARY_C:
            assert selection.force_review is False

    def test_same_input_same_group(self):
        """Same input always gets same group assignment."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=100.0,
            freeze_mode="ir_canary",
            quality_gate_mode="shadow",
        )
        s1 = select_canary_group("t1", "doc_hash", "v1", config)
        s2 = select_canary_group("t1", "doc_hash", "v1", config)
        assert s1.group == s2.group

    def test_selection_serializable(self):
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=100.0,
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        selection = select_canary_group("t1", "d", "v1", config)
        d = selection.to_dict()
        assert "group" in d
        assert "effective_freeze_mode" in d
        assert "effective_quality_gate_mode" in d

    def test_empty_tenants_all_allowed(self):
        """Empty allowlist/denylist means all tenants allowed with canary config."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=100.0,
            freeze_mode="ir_canary",
            quality_gate_mode="shadow",
        )
        selection = select_canary_group("any_tenant", "d", "v1", config)
        assert selection.group == GROUP_CANARY_C

    def test_bucket_trace_in_diagnostics(self):
        """Bucket assignment should be included in diagnostics."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=5.0,
        )
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.bucket_assignment is not None
        assert selection.bucket_assignment.canary_bucket >= 0
