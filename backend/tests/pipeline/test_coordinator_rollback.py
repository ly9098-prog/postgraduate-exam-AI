"""Coordinator rollback tests — legacy availability and mode fallback."""

from __future__ import annotations

import pytest

from app.features.pipeline_coordinator_entry import (
    PipelineCoordinatorMode,
    is_legacy_available,
)


class TestLegacyAvailability:
    """Tests for legacy orchestrator availability check."""

    def test_legacy_available_returns_bool(self):
        """is_legacy_available() returns a bool."""
        result = is_legacy_available()
        assert isinstance(result, bool)

    def test_legacy_available_idempotent(self):
        """Calling is_legacy_available() multiple times is safe."""
        first = is_legacy_available()
        second = is_legacy_available()
        assert first == second


class TestModeFallback:
    """Tests for mode enum and fallback values."""

    def test_mode_fallback_legacy_value(self):
        """PipelineCoordinatorMode.LEGACY.value is 'legacy'."""
        assert PipelineCoordinatorMode.LEGACY.value == "legacy"

    def test_mode_fallback_all_values(self):
        """All PipelineCoordinatorMode values are the expected strings."""
        assert PipelineCoordinatorMode.LEGACY.value == "legacy"
        assert PipelineCoordinatorMode.SHADOW.value == "shadow"
        assert PipelineCoordinatorMode.COORDINATOR.value == "coordinator"

    def test_mode_fallback_legacy_is_str(self):
        """LEGACY is a string enum member."""
        assert isinstance(PipelineCoordinatorMode.LEGACY, str)
        assert isinstance(PipelineCoordinatorMode.LEGACY, PipelineCoordinatorMode)

    def test_mode_fallback_from_string(self):
        """PipelineCoordinatorMode can be constructed from string values."""
        assert PipelineCoordinatorMode("legacy") == PipelineCoordinatorMode.LEGACY
        assert PipelineCoordinatorMode("shadow") == PipelineCoordinatorMode.SHADOW
        assert PipelineCoordinatorMode("coordinator") == PipelineCoordinatorMode.COORDINATOR

    def test_mode_fallback_invalid_raises(self):
        """Invalid mode string raises ValueError."""
        with pytest.raises(ValueError):
            PipelineCoordinatorMode("invalid_mode")
