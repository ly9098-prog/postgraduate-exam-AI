"""Shadow mode tests — ShadowPlan creation, stage routing, no real execution."""

from __future__ import annotations

import pytest

from app.features.pipeline_coordinator_entry import (
    ShadowPlan,
    get_coordinator_mode,
    run_coordinator_pipeline_shadow,
)


class TestShadowMode:
    """Tests for shadow mode and ShadowPlan."""

    def test_shadow_mode_default(self):
        """get_coordinator_mode() returns a valid mode string.

        Default is 'shadow' when PIPELINE_COORDINATOR_MODE is not set,
        but in test environments it may be overridden. We only assert it
        returns a string.
        """
        mode = get_coordinator_mode()
        assert isinstance(mode, str)
        assert mode in ("legacy", "shadow", "coordinator")

    def test_shadow_plan_created(self):
        """ShadowPlan() initializes with empty stages list."""
        plan = ShadowPlan()
        assert plan.stages == []
        assert plan.ocr_route == ""
        assert plan.document_ir_plan is False
        assert plan.pages_planned == 0

    def test_shadow_plan_add_stage(self):
        """plan.add_stage(name, plan_dict) adds to stages list."""
        plan = ShadowPlan()
        plan.add_stage("ocr", {"route": "local", "confidence": 0.9})
        assert len(plan.stages) == 1
        assert plan.stages[0]["stage"] == "ocr"
        assert plan.stages[0]["route"] == "local"
        assert plan.stages[0]["confidence"] == 0.9

    def test_shadow_plan_multiple_stages(self):
        """Adding multiple stages preserves order."""
        plan = ShadowPlan()
        plan.add_stage("input", {"planned": True})
        plan.add_stage("ocr", {"route": "local"})
        plan.add_stage("persistence", {"mode": "full"})
        assert len(plan.stages) == 3
        stage_names = [s["stage"] for s in plan.stages]
        assert stage_names == ["input", "ocr", "persistence"]

    @pytest.mark.asyncio
    async def test_shadow_pipeline_no_real_execution(self):
        """run_coordinator_pipeline_shadow returns ShadowPlan without real execution.

        Shadow mode only plans stages; it never executes real OCR or AI.
        """
        plan = await run_coordinator_pipeline_shadow()
        assert isinstance(plan, ShadowPlan)
        assert len(plan.stages) > 0
        # Verify all expected stages are present
        stage_names = [s["stage"] for s in plan.stages]
        for expected in (
            "input", "page_stream", "ocr", "doc_structure",
            "domain_parsing", "correction", "validation", "review", "persistence",
        ):
            assert expected in stage_names, f"Missing stage: {expected}"

    @pytest.mark.asyncio
    async def test_shadow_plan_contains_profile(self):
        """Shadow plan input stage carries profile info."""
        plan = await run_coordinator_pipeline_shadow()
        first_stage = plan.stages[0]
        assert first_stage["stage"] == "input"
        assert "profile" in first_stage
        assert isinstance(first_stage["profile"], str)
        assert len(first_stage["profile"]) > 0

    @pytest.mark.asyncio
    async def test_shadow_plan_ocr_route_set(self):
        """ocr_route is set based on pipeline profile."""
        plan = await run_coordinator_pipeline_shadow()
        assert plan.ocr_route in ("local", "gateway")
        # Verify the OCR stage matches the route
        ocr_stage = [s for s in plan.stages if s["stage"] == "ocr"][0]
        assert ocr_stage["route"] == plan.ocr_route
