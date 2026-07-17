"""Canary config model tests."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.features.ocr_canary import (
    ENV_CANARY_ENABLED,
    ENV_IR_CANARY_PERCENT,
    ENV_CANARY_SUBJECTS,
    ENV_CANARY_SOURCE_TYPES,
    OCRCanaryConfig,
)


class TestOCREnCryptConfig:
    def test_default_config_is_safe(self):
        """Default config should have canary disabled."""
        config = OCRCanaryConfig()
        assert config.enabled is False
        assert config.rollout_percent == 0.0
        assert config.freeze_mode == "legacy"
        assert config.quality_gate_mode == "off"

    def test_enabled_config(self):
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=1.0,
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        assert config.enabled
        assert config.rollout_percent == 1.0

    def test_frozen_immutable(self):
        config = OCRCanaryConfig()
        with pytest.raises(AttributeError):
            config.enabled = True  # type: ignore[misc]

    def test_invalid_rollout_percent_low(self):
        with pytest.raises(ValueError, match="rollout_percent"):
            OCRCanaryConfig(rollout_percent=-1.0)

    def test_invalid_rollout_percent_high(self):
        with pytest.raises(ValueError, match="rollout_percent"):
            OCRCanaryConfig(rollout_percent=101.0)

    def test_invalid_freeze_mode(self):
        with pytest.raises(ValueError, match="freeze_mode"):
            OCRCanaryConfig(freeze_mode="invalid")

    def test_invalid_quality_gate_mode(self):
        with pytest.raises(ValueError, match="quality_gate_mode"):
            OCRCanaryConfig(quality_gate_mode="invalid")

    def test_quality_gate_enforce_prohibited(self):
        with pytest.raises(ValueError, match="enforce"):
            OCRCanaryConfig(quality_gate_mode="enforce")

    def test_ir_global_default_prohibited(self):
        with pytest.raises(ValueError, match="ir_global_default"):
            OCRCanaryConfig(freeze_mode="ir_global_default")

    def test_valid_dual_shadow_config(self):
        """Dual+shadow is valid for Observation B."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=1.0,
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        assert config.freeze_mode == "dual"

    def test_valid_ir_canary_config(self):
        """ir_canary is a valid freeze mode."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=1.0,
            freeze_mode="ir_canary",
            quality_gate_mode="shadow",
        )
        assert config.freeze_mode == "ir_canary"

    def test_from_env_disabled(self):
        """When env vars are unset, config should be safe (disabled)."""
        with patch.dict(os.environ, {}, clear=True):
            config = OCRCanaryConfig.from_env()
            assert config.enabled is False
            assert config.rollout_percent == 0.0

    def test_from_env_enabled(self):
        with patch.dict(os.environ, {
            ENV_CANARY_ENABLED: "true",
            ENV_IR_CANARY_PERCENT: "2.5",
        }, clear=True):
            config = OCRCanaryConfig.from_env()
            assert config.enabled is True
            assert config.rollout_percent == 2.5

    def test_from_env_subjects(self):
        with patch.dict(os.environ, {
            ENV_CANARY_SUBJECTS: "exam408,math2",
        }, clear=True):
            config = OCRCanaryConfig.from_env()
            assert config.subjects == ("exam408", "math2")

    def test_from_env_source_types(self):
        with patch.dict(os.environ, {
            ENV_CANARY_SOURCE_TYPES: "pdf,image",
        }, clear=True):
            config = OCRCanaryConfig.from_env()
            assert config.source_types == ("pdf", "image")

    def test_from_env_bad_percent_defaults_zero(self):
        with patch.dict(os.environ, {
            ENV_IR_CANARY_PERCENT: "not-a-number",
        }, clear=True):
            config = OCRCanaryConfig.from_env()
            assert config.rollout_percent == 0.0

    def test_with_overrides(self):
        base = OCRCanaryConfig(enabled=True, rollout_percent=1.0)
        overridden = base.with_overrides(rollout_percent=5.0)
        assert overridden.rollout_percent == 5.0
        assert overridden.enabled is True  # unchanged
        # Original should be unaffected
        assert base.rollout_percent == 1.0

    def test_with_overrides_freezes(self):
        """Overridden config should also be frozen."""
        base = OCRCanaryConfig()
        overridden = base.with_overrides(enabled=True)
        with pytest.raises(AttributeError):
            overridden.enabled = False  # type: ignore[misc]
