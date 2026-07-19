"""Sprint 4C: Verify rollback and resume paths remain available.

Both legacy and coordinator pipelines must be importable so that
a rollback from coordinator mode to legacy mode is always possible.
"""

from __future__ import annotations

import inspect

import pytest


class TestRollbackResumeIdempotency:
    """Verify both legacy and coordinator pipeline entries are available."""

    def test_legacy_pipeline_importable(self):
        """run_import_pipeline is importable from legacy orchestrator."""
        from app.features.pipeline_orchestrator import run_import_pipeline

        assert callable(run_import_pipeline)
        assert inspect.iscoroutinefunction(run_import_pipeline)

    def test_coordinator_entry_importable(self):
        """run_pipeline is importable from coordinator entry."""
        from app.features.pipeline_coordinator_entry import run_pipeline

        assert callable(run_pipeline)
        assert inspect.iscoroutinefunction(run_pipeline)

    def test_both_entry_points_available(self):
        """Both run_pipeline and run_import_pipeline are importable."""
        from app.features.pipeline_coordinator_entry import run_pipeline
        from app.features.pipeline_orchestrator import run_import_pipeline

        assert run_pipeline is not run_import_pipeline
        assert callable(run_pipeline)
        assert callable(run_import_pipeline)

    def test_is_legacy_available_returns_true(self):
        """is_legacy_available returns True (legacy always available)."""
        from app.features.pipeline_coordinator_entry import is_legacy_available

        result = is_legacy_available()
        assert result is True, "Legacy orchestrator must be available for rollback"

    def test_legacy_mode_via_env(self, monkeypatch):
        """PIPELINE_COORDINATOR_MODE=legacy selects legacy mode."""
        monkeypatch.setenv("PIPELINE_COORDINATOR_MODE", "legacy")
        from app.features.pipeline_coordinator_entry import get_coordinator_mode

        assert get_coordinator_mode() == "legacy"

    def test_coordinator_mode_via_env(self, monkeypatch):
        """PIPELINE_COORDINATOR_MODE=coordinator selects coordinator mode."""
        monkeypatch.setenv("PIPELINE_COORDINATOR_MODE", "coordinator")
        from app.features.pipeline_coordinator_entry import get_coordinator_mode

        assert get_coordinator_mode() == "coordinator"

    def test_shadow_mode_via_env(self, monkeypatch):
        """PIPELINE_COORDINATOR_MODE=shadow selects shadow mode."""
        monkeypatch.setenv("PIPELINE_COORDINATOR_MODE", "shadow")
        from app.features.pipeline_coordinator_entry import get_coordinator_mode

        assert get_coordinator_mode() == "shadow"

    def test_default_mode_is_shadow(self, monkeypatch):
        """Default mode (no env var) is 'shadow'."""
        monkeypatch.delenv("PIPELINE_COORDINATOR_MODE", raising=False)
        from app.features.pipeline_coordinator_entry import get_coordinator_mode

        assert get_coordinator_mode() == "shadow"

    def test_shadow_plan_importable(self):
        """ShadowPlan class is importable."""
        from app.features.pipeline_coordinator_entry import ShadowPlan

        plan = ShadowPlan()
        assert plan.stages == []
        assert plan.ocr_route == ""
        assert plan.document_ir_plan is False
        assert plan.pages_planned == 0

    def test_shadow_plan_add_stage(self):
        """ShadowPlan.add_stage works correctly."""
        from app.features.pipeline_coordinator_entry import ShadowPlan

        plan = ShadowPlan()
        plan.add_stage("input", {"planned": True, "profile": "local_import"})
        assert len(plan.stages) == 1
        assert plan.stages[0]["stage"] == "input"
        assert plan.stages[0]["planned"] is True

    @pytest.mark.asyncio
    async def test_shadow_pipeline_runs(self, monkeypatch):
        """run_coordinator_pipeline_shadow returns a ShadowPlan."""
        monkeypatch.setenv("PIPELINE_COORDINATOR_MODE", "shadow")
        from app.features.pipeline_coordinator_entry import (
            ShadowPlan,
            run_coordinator_pipeline_shadow,
        )

        plan = await run_coordinator_pipeline_shadow(
            request=None, context=None, policy=None,
        )

        assert isinstance(plan, ShadowPlan)
        assert len(plan.stages) > 0

        stage_names = [s["stage"] for s in plan.stages]
        assert "input" in stage_names
        assert "ocr" in stage_names
        assert "review" in stage_names
        assert "persistence" in stage_names

    def test_coordinator_pipeline_importable(self):
        """CoordinatorPipeline class is importable."""
        from app.features.coordinator_orchestrator import CoordinatorPipeline
        assert CoordinatorPipeline is not None

    def test_coordinator_pipeline_docstring(self):
        """CoordinatorPipeline has documentation."""
        from app.features.coordinator_orchestrator import CoordinatorPipeline

        doc = CoordinatorPipeline.__doc__
        assert doc is not None
        assert "Coordinator" in doc or "Sequential" in doc
