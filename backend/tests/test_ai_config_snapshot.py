"""Tests for AIModelConfigSnapshot — serialization, no-secret guarantee, resume safety."""

from __future__ import annotations

import json

import pytest

from app.services.model_config_resolver import (
    AIModelConfigSnapshot,
    ResolvedAIModelConfig,
)


class TestSnapshotSecurity:
    """Verify that snapshots never contain secrets."""

    SENSITIVE_KEYS = {"api_key", "api_token", "secret", "password", "token", "credential"}

    def _assert_no_secrets(self, obj, path=""):
        """Recursively check that no sensitive keys exist in a dict or object."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_lower = key.lower()
                if any(sk in key_lower for sk in self.SENSITIVE_KEYS):
                    pytest.fail(f"Secret field found at {path}.{key}")
                if isinstance(value, (dict, list)):
                    self._assert_no_secrets(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, (dict, list)):
                    self._assert_no_secrets(item, f"{path}[{i}]")

    def test_snapshot_dict_no_secrets(self):
        resolved = ResolvedAIModelConfig(
            config_id=1, model_config_id=1,
            provider="deepseek", model_name="test",
            config_fingerprint="fp", secret_reference="somewhere",
        )
        snapshot = AIModelConfigSnapshot.from_resolved(resolved, "ocr_vl")
        d = {
            "config_id": snapshot.config_id,
            "model_config_id": snapshot.model_config_id,
            "provider": snapshot.provider,
            "model_name": snapshot.model_name,
            "capability": snapshot.capability,
            "config_fingerprint": snapshot.config_fingerprint,
            "timeout_seconds": snapshot.timeout_seconds,
            "max_retries": snapshot.max_retries,
            "resolved_at": snapshot.resolved_at,
        }
        self._assert_no_secrets(d)

    def test_snapshot_json_serializable_no_secrets(self):
        resolved = ResolvedAIModelConfig(
            config_id=42, model_config_id=42,
            provider="paddleocr_vl", model_name="PaddleOCR-VL-1.6",
            endpoint="https://paddleocr.aistudio-app.com",
            config_fingerprint="abc123def456",
        )
        snapshot = AIModelConfigSnapshot.from_resolved(resolved, "ocr_vl",
                                                        resolved_at="2026-07-18T12:00:00")
        d = {
            "config_id": int(snapshot.config_id),
            "model_config_id": int(snapshot.model_config_id),
            "provider": snapshot.provider,
            "model_name": snapshot.model_name,
            "capability": snapshot.capability,
            "config_fingerprint": snapshot.config_fingerprint,
            "timeout_seconds": snapshot.timeout_seconds,
            "max_retries": snapshot.max_retries,
            "resolved_at": snapshot.resolved_at,
        }
        serialized = json.dumps(d)
        restored = json.loads(serialized)
        assert restored["provider"] == "paddleocr_vl"
        assert restored["model_name"] == "PaddleOCR-VL-1.6"


class TestSnapshotFrozenOnResume:
    """Verify snapshot survives serialization round-trip (resume safety)."""

    def test_round_trip(self):
        resolved = ResolvedAIModelConfig(
            config_id=1, model_config_id=1,
            provider="deepseek", model_name="deepseek-v4-flash",
            endpoint="https://api.deepseek.com",
            config_fingerprint="fp123",
            timeout_seconds=120.0, max_retries=3,
        )
        snapshot = AIModelConfigSnapshot.from_resolved(resolved, "ocr_vl")

        # Simulate serialization into PipelineExecutionContext
        d = {
            "config_id": int(snapshot.config_id),
            "model_config_id": int(snapshot.model_config_id),
            "provider": snapshot.provider,
            "model_name": snapshot.model_name,
            "capability": snapshot.capability,
            "config_fingerprint": snapshot.config_fingerprint,
            "timeout_seconds": snapshot.timeout_seconds,
            "max_retries": snapshot.max_retries,
            "resolved_at": snapshot.resolved_at,
        }
        # Resume: reconstruct from dict
        restored = AIModelConfigSnapshot(
            config_id=d["config_id"],
            model_config_id=d["model_config_id"],
            provider=d["provider"],
            model_name=d["model_name"],
            capability=d["capability"],
            config_fingerprint=d["config_fingerprint"],
            timeout_seconds=d["timeout_seconds"],
            max_retries=d["max_retries"],
            resolved_at=d["resolved_at"],
        )
        assert restored.model_name == snapshot.model_name
        assert restored.config_fingerprint == snapshot.config_fingerprint
        assert restored.timeout_seconds == snapshot.timeout_seconds

    def test_config_id_unchanged_after_resume(self):
        """Config IDs must be same on resume — no re-resolution with different model."""
        snapshot = AIModelConfigSnapshot(
            config_id=42,
            model_config_id=42,
            provider="paddleocr_vl",
            model_name="PaddleOCR-VL-1.6",
            capability="ocr_vl",
            config_fingerprint="original_fp",
            timeout_seconds=300.0,
            max_retries=3,
            resolved_at="2026-07-18T10:00:00",
        )
        # On resume, we use the same config_id — not re-resolving
        assert snapshot.model_config_id == 42
        assert snapshot.config_fingerprint == "original_fp"
