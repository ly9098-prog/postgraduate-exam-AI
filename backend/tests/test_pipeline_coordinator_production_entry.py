"""Production entry tests — mode switching, run_pipeline routing, enum values."""

from __future__ import annotations

import pytest


class TestPipelineCoordinatorMode:
    """Tests for PipelineCoordinatorMode enum and mode switching."""

    def test_mode_enum_values(self):
        """PipelineCoordinatorMode values are correct."""
        from app.features.pipeline_coordinator_entry import PipelineCoordinatorMode

        assert PipelineCoordinatorMode.LEGACY.value == "legacy"
        assert PipelineCoordinatorMode.SHADOW.value == "shadow"
        assert PipelineCoordinatorMode.COORDINATOR.value == "coordinator"

    def test_mode_enum_is_string(self):
        """PipelineCoordinatorMode is a str Enum."""
        from app.features.pipeline_coordinator_entry import PipelineCoordinatorMode

        assert issubclass(PipelineCoordinatorMode, str)
        assert PipelineCoordinatorMode.SHADOW == "shadow"

    def test_coordinator_mode_switching(self):
        """get_coordinator_mode() returns consistent string values matching the enum."""
        from app.features.pipeline_coordinator_entry import (
            PipelineCoordinatorMode,
            get_coordinator_mode,
        )

        mode = get_coordinator_mode()
        # Mode should be one of the defined enum values
        valid = {e.value for e in PipelineCoordinatorMode}
        assert mode in valid, f"Mode '{mode}' not in {valid}"


class TestRunPipelineShadowMode:
    """Tests for run_pipeline routing to shadow/legacy path."""

    @pytest.mark.asyncio
    async def test_run_pipeline_shadow_calls_legacy(
        self, monkeypatch,
    ):
        """When PIPELINE_COORDINATOR_MODE=shadow, run_pipeline delegates to legacy.

        We monkeypatch the env before any import so get_coordinator_mode() sees 'shadow',
        then mock _run_legacy_pipeline to confirm it is called.
        """
        monkeypatch.setenv("PIPELINE_COORDINATOR_MODE", "shadow")

        from app.features.pipeline_coordinator_entry import (
            _run_legacy_pipeline,
            run_pipeline,
        )

        called_with = []

        async def fake_legacy(request, *, context=None, policy=None):
            called_with.append((request, context, policy))
            return {"status": "legacy_ok"}

        monkeypatch.setattr(
            "app.features.pipeline_coordinator_entry._run_legacy_pipeline",
            fake_legacy,
        )

        result = await run_pipeline({"source": b"test"}, context=None, policy=None)

        assert len(called_with) == 1
        assert called_with[0][0] == {"source": b"test"}
        assert result == {"status": "legacy_ok"}

    @pytest.mark.asyncio
    async def test_run_pipeline_legacy_mode(
        self, monkeypatch,
    ):
        """When PIPELINE_COORDINATOR_MODE=legacy, run_pipeline calls legacy path."""
        monkeypatch.setenv("PIPELINE_COORDINATOR_MODE", "legacy")

        from app.features.pipeline_coordinator_entry import run_pipeline

        called = []

        async def fake_legacy(request, *, context=None, policy=None):
            called.append(request)
            return {"status": "legacy"}

        monkeypatch.setattr(
            "app.features.pipeline_coordinator_entry._run_legacy_pipeline",
            fake_legacy,
        )

        result = await run_pipeline({"source": b"legacy-test"})

        assert len(called) == 1
        assert called[0] == {"source": b"legacy-test"}
        assert result["status"] == "legacy"


class TestRunPipelineCoordinatorMode:
    """Tests for run_pipeline routing to coordinator path."""

    @pytest.mark.asyncio
    async def test_run_pipeline_coordinator_mode(
        self, monkeypatch,
    ):
        """When PIPELINE_COORDINATOR_MODE=coordinator, run_pipeline calls coordinator path."""
        monkeypatch.setenv("PIPELINE_COORDINATOR_MODE", "coordinator")

        from app.features.pipeline_coordinator_entry import run_pipeline

        called = []

        async def fake_coordinator(request=None, context=None, policy=None):
            called.append((request, context, policy))
            return {"status": "coordinator_ok", "stages": {}}

        monkeypatch.setattr(
            "app.features.pipeline_coordinator_entry.run_coordinator_pipeline",
            fake_coordinator,
        )

        result = await run_pipeline(
            {"source": b"coord-test"}, context=None, policy=None,
        )

        assert len(called) == 1
        assert called[0][0] == {"source": b"coord-test"}
        assert result["status"] == "coordinator_ok"
