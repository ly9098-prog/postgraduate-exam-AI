"""Canary artifact persistence tests."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from app.features.ocr_canary import (
    OCRCanaryConfig,
    assign_canary_bucket,
    build_canary_diagnostics,
    select_canary_group,
)


class TestCanaryArtifactPersistence:
    def test_bucket_assignment_serializable(self):
        """Bucket assignment must be JSON-serializable."""
        config = OCRCanaryConfig(enabled=True, rollout_percent=5.0)
        assignment = assign_canary_bucket("t1", "d1", "v1", config)
        d = assignment.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["canary_selected"] == d["canary_selected"]
        assert parsed["canary_bucket"] == d["canary_bucket"]

    def test_group_selection_serializable(self):
        """Group selection must be JSON-serializable."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=5.0,
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        selection = select_canary_group("t1", "d1", "v1", config)
        d = selection.to_dict()
        json_str = json.dumps(d, default=str)
        parsed = json.loads(json_str)
        assert parsed["group"] == selection.group

    def test_diagnostics_block_written_to_artifact(self):
        """Diagnostics block should contain all canary trace info."""
        config = OCRCanaryConfig(
            enabled=True,
            rollout_percent=5.0,
            freeze_mode="dual",
            quality_gate_mode="shadow",
        )
        selection = select_canary_group("t1", "d1", "pv1", config)
        diagnostics = build_canary_diagnostics(selection)
        assert "group" in diagnostics
        assert "effective_freeze_mode" in diagnostics
        assert "bucket_assignment" in diagnostics

    def test_diagnostics_includes_fallback(self):
        """Fallback diagnostics should include reason codes."""
        from app.features.ocr_canary import CanaryGroupSelection

        selection = CanaryGroupSelection(
            group="canary_c",
            effective_freeze_mode="ir_canary",
            canary_fallback=True,
            fallback_from="ir_canary",
            fallback_to="legacy",
            fallback_reason_codes=["IR_FREEZE_EXCEPTION"],
        )
        diagnostics = build_canary_diagnostics(selection, fallback_reason_codes=["IR_FREEZE_EXCEPTION"])
        assert diagnostics.get("canary_fallback") is True
        assert "fallback_reason_codes" in diagnostics

    def test_artifact_includes_config_version(self):
        config = OCRCanaryConfig(enabled=True, rollout_percent=5.0, config_version="s3f-v2")
        assignment = assign_canary_bucket("t1", "d1", "v1", config)
        assert assignment.config_version == "s3f-v2"

    def test_diagnostics_with_extra_fields(self):
        config = OCRCanaryConfig(enabled=True, rollout_percent=5.0)
        selection = select_canary_group("t1", "d1", "v1", config)
        diagnostics = build_canary_diagnostics(selection, extra={"source": "test", "pipeline_id": "p123"})
        assert diagnostics["source"] == "test"
        assert diagnostics["pipeline_id"] == "p123"
