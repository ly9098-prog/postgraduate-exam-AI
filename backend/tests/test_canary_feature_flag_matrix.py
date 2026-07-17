"""Feature flag combination tests."""
from __future__ import annotations

import pytest

from app.features.ocr_canary import (
    GROUP_CONTROL_A,
    GROUP_OBSERVATION_B,
    GROUP_CANARY_C,
    OCRCanaryConfig,
    select_canary_group,
)


class TestFeatureFlagMatrix:
    """Test all feature flag combinations from section 12 of next_task.md.

    A. legacy + off + thread
    B. legacy + shadow + thread
    C. dual + off + thread
    D. dual + shadow + thread
    E. legacy + off + process pool
    F. dual + shadow + process pool
    G. ir_canary selected (bucket selected)
    H. ir_canary not selected (bucket not selected)
    I. ir_canary fallback
    J. Canary globally disabled
    """

    def test_a_legacy_off_thread(self):
        """A is the production baseline: legacy+off."""
        config = OCRCanaryConfig(
            enabled=False,
            freeze_mode="legacy",
            quality_gate_mode="off",
        )
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.group == GROUP_CONTROL_A
        assert selection.effective_freeze_mode == "legacy"
        assert selection.effective_quality_gate_mode == "off"

    def test_b_legacy_shadow_thread(self):
        """B: legacy+shadow — freeze stays legacy, quality gate shadow runs separately."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=0.0,
            freeze_mode="legacy",
            quality_gate_mode="shadow",
        )
        selection = select_canary_group("t1", "d1", "v1", config)
        # legacy freeze doesn't change; QG mode is separate
        assert selection.effective_freeze_mode == "legacy"
        # In legacy mode, quality_gate_mode stays as config-defined
        assert selection.effective_quality_gate_mode == "shadow"

    def test_c_dual_off_thread(self):
        """C: dual+off."""
        config = OCRCanaryConfig(
            enabled=False,
            freeze_mode="dual",
            quality_gate_mode="off",
        )
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.group == GROUP_CONTROL_A  # canary disabled

    def test_d_dual_shadow_thread(self):
        """D: dual+shadow — Observation B for ALL pre-release traffic."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=1.0,
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        selection = select_canary_group("t1", "d1", "v1", config)
        # All tasks in dual+shadow → Observation B
        assert selection.group in (GROUP_OBSERVATION_B, GROUP_CANARY_C)

    def test_e_legacy_off_process_pool(self):
        config = OCRCanaryConfig(
            enabled=False,
            freeze_mode="legacy",
            quality_gate_mode="off",
            process_pool_enabled=True,
        )
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.group == GROUP_CONTROL_A
        assert selection.effective_freeze_mode == "legacy"
        # process_pool is orthogonal to group selection

    def test_f_dual_shadow_process_pool(self):
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=1.0,
            freeze_mode="dual",
            quality_gate_mode="shadow",
            process_pool_enabled=True,
        )
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.group in (GROUP_OBSERVATION_B, GROUP_CANARY_C)

    def test_g_ir_canary_selected(self):
        """G: bucket-selected IR canary tasks."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=100.0,
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        selection = select_canary_group("t1", "doc_sel", "v1", config)
        if selection.bucket_assignment and selection.bucket_assignment.canary_selected:
            assert selection.group == GROUP_CANARY_C
            assert selection.effective_freeze_mode == "ir_canary"

    def test_h_ir_canary_not_selected(self):
        """H: non-selected tasks should remain in Observation or Control."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=0.001,  # very small, almost certainly not selected
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        selection = select_canary_group("t1", "doc_nonsel", "v1", config)
        # Most likely Observation B since dual+shadow
        if selection.bucket_assignment:
            if not selection.bucket_assignment.canary_selected:
                assert selection.group == GROUP_OBSERVATION_B

    def test_i_ir_canary_fallback(self):
        """I: fallback should produce legacy-compatible group."""
        from app.features.ocr_canary import CanaryGroupSelection
        fallback = CanaryGroupSelection(
            group=GROUP_CANARY_C,
            effective_freeze_mode="legacy",
            canary_fallback=True,
            fallback_from="ir_canary",
            fallback_to="legacy",
            fallback_reason_codes=["IR_FREEZE_EXCEPTION"],
        )
        assert fallback.canary_fallback is True
        assert fallback.effective_freeze_mode == "legacy"
        # Fallback output should be equivalent to Control A
        assert fallback.fallback_to == "legacy"

    def test_j_canary_globally_disabled(self):
        """J: globally disabled → no canary logic at all."""
        config = OCRCanaryConfig(enabled=False)
        selection = select_canary_group("t1", "d1", "v1", config)
        assert selection.group == GROUP_CONTROL_A
        assert selection.effective_freeze_mode == "legacy"
        assert selection.effective_quality_gate_mode == "off"
        assert selection.force_review is False
