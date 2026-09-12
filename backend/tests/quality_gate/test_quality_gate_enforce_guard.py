"""Quality Gate Enforce Guard Tests.

Verifies that ``DOMAIN_QUALITY_GATE_MODE=enforce`` cannot be enabled
without the explicit ``QUALITY_GATE_ENFORCE_ENABLED=True`` sentinel.
"""

from __future__ import annotations

import pytest


class TestEnforceGuard:
    """Guard prevents accidental enforce mode."""

    def test_enforce_disabled_by_default(self):
        """DOMAIN_QUALITY_GATE_MODE default is 'off'."""
        from app.core.config import settings
        assert settings.DOMAIN_QUALITY_GATE_MODE == "off"

    def test_enforce_sentinel_false_by_default(self):
        """QUALITY_GATE_ENFORCE_ENABLED defaults to False."""
        from app.core.config import settings
        assert settings.QUALITY_GATE_ENFORCE_ENABLED is False

    def test_enforce_raises_without_sentinel(self):
        """Setting enforce mode without sentinel raises ConfigurationError."""
        from app.features.pipeline_orchestrator import _validate_quality_gate_mode

        with pytest.raises(RuntimeError, match="enforce"):
            _validate_quality_gate_mode("enforce")

    def test_shadow_and_off_pass_validation(self):
        """Shadow and off modes pass validation without sentinel."""
        from app.features.pipeline_orchestrator import _validate_quality_gate_mode

        # Should not raise
        result_off = _validate_quality_gate_mode("off")
        result_shadow = _validate_quality_gate_mode("shadow")
        assert result_off == "off"
        assert result_shadow == "shadow"

    def test_quality_gate_module_default_is_off(self):
        """quality_gate.py module-level default is 'off'."""
        from app.features.quality_gate import DOMAIN_QUALITY_GATE_MODE
        assert DOMAIN_QUALITY_GATE_MODE == "off"
