"""Tests for scheduler: coordinator shadow into production, mode switching, and rollback."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.features.pipeline_coordinator_entry import (
    PipelineCoordinatorMode,
    get_coordinator_mode,
    is_legacy_available,
)


class TestPipelineCoordinatorMode:
    """Test coordinator mode enum and detection."""

    def test_mode_values(self):
        assert PipelineCoordinatorMode.LEGACY.value == "legacy"
        assert PipelineCoordinatorMode.SHADOW.value == "shadow"
        assert PipelineCoordinatorMode.COORDINATOR.value == "coordinator"

    def test_default_mode(self):
        """Default should be 'shadow' as defined in entry point."""
        mode = get_coordinator_mode()
        assert mode == "shadow"

    def test_mode_from_env(self):
        """Mode can be overridden by env var."""
        with patch.dict(os.environ, {"PIPELINE_COORDINATOR_MODE": "coordinator"}, clear=False):
            mode = get_coordinator_mode()
            assert mode == "coordinator"

    def test_legacy_mode(self):
        with patch.dict(os.environ, {"PIPELINE_COORDINATOR_MODE": "legacy"}, clear=False):
            mode = get_coordinator_mode()
            assert mode == "legacy"


class TestCoordinatorShadow:
    """Test shadow mode — plan only, no real execution."""

    @pytest.mark.asyncio
    async def test_shadow_creates_plan(self):
        """Shadow mode creates a plan but doesn't execute OCR/API/persistence."""
        from app.features.pipeline_coordinator_entry import (
            run_coordinator_pipeline_shadow,
        )

        plan = await run_coordinator_pipeline_shadow()
        assert plan is not None
        assert hasattr(plan, "stages")
        assert hasattr(plan, "ocr_route")

    @pytest.mark.asyncio
    async def test_shadow_plan_has_no_execution(self):
        """Verify shadow plan stages contain routing decisions, not execution results."""
        from app.features.pipeline_coordinator_entry import (
            run_coordinator_pipeline_shadow,
        )

        plan = await run_coordinator_pipeline_shadow()
        for stage in plan.stages:
            assert "stage" in stage
            # Should have planning info, not execution results
            assert not any(k in stage for k in ("result", "output", "error"))

    def test_legacy_orchestrator_available(self):
        """Legacy orchestrator should be importable for rollback."""
        available = is_legacy_available()
        assert available is True
