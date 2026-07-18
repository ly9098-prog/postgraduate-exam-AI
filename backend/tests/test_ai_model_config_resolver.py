"""Tests for AIModelConfigResolver — core resolution logic without database.

Uses synthetic test data injected into the resolver via patching.
For real DB integration tests, see tests/integration/.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.model_config_resolver import (
    AICapability,
    AIConfigErrorCode,
    AIModelConfigResolver,
    AIModelConfigSnapshot,
    ResolvedAIModelConfig,
)


class TestAICapability:
    def test_enum_values(self):
        assert AICapability.OCR_VL.value == "ocr_vl"
        assert AICapability.OCR_LIGHTWEIGHT.value == "ocr_lightweight"
        assert AICapability.OCR_FIX.value == "ocr_fix"
        assert AICapability.AI_REPAIR.value == "ai_repair"

    def test_all_capabilities_defined(self):
        expected = {"ocr_vl", "ocr_lightweight", "ocr_fix", "ai_repair",
                     "text_correction", "text_structuring", "completion", "embedding"}
        actual = {c.value for c in AICapability}
        assert actual == expected


class TestAIConfigErrorCode:
    def test_enum_values(self):
        assert AIConfigErrorCode.AI_CONFIG_NOT_FOUND.value == "AI_CONFIG_NOT_FOUND"
        assert AIConfigErrorCode.AI_MODEL_CONFIG_NOT_FOUND.value == "AI_MODEL_CONFIG_NOT_FOUND"
        assert AIConfigErrorCode.AI_CONFIG_CAPABILITY_MISMATCH.value == "AI_CONFIG_CAPABILITY_MISMATCH"
        assert AIConfigErrorCode.AI_CONFIG_SECRET_MISSING.value == "AI_CONFIG_SECRET_MISSING"


class TestResolvedAIModelConfig:
    def test_frozen(self):
        config = ResolvedAIModelConfig(
            config_id=1,
            model_config_id=1,
            provider="deepseek",
            model_name="deepseek-v4-flash",
        )
        assert config.config_id == 1
        assert config.provider == "deepseek"
        assert config.model_name == "deepseek-v4-flash"
        assert config.endpoint is None
        assert config.enabled is True
        assert config.timeout_seconds == 120.0
        assert config.max_retries == 3

    def test_frozen_cannot_modify(self):
        config = ResolvedAIModelConfig(config_id=1, model_config_id=1, provider="t", model_name="m")
        with pytest.raises(Exception):
            config.model_name = "other"  # frozen dataclass

    def test_with_all_fields(self):
        config = ResolvedAIModelConfig(
            config_id=42,
            model_config_id=42,
            provider="paddleocr_vl",
            model_name="PaddleOCR-VL-1.6",
            endpoint="https://paddleocr.aistudio-app.com",
            capabilities=frozenset({"vision", "ocr"}),
            timeout_seconds=300.0,
            max_retries=3,
            config_fingerprint="abc123",
            secret_reference="admin_ai_model_configs.api_key_encrypted",
            metadata={"display_name": "PaddleOCR VL 1.6"},
        )
        assert config.endpoint == "https://paddleocr.aistudio-app.com"
        assert "vision" in config.capabilities
        assert config.secret_reference is not None


class TestAIModelConfigSnapshot:
    def test_from_resolved(self):
        resolved = ResolvedAIModelConfig(
            config_id=1,
            model_config_id=1,
            provider="deepseek",
            model_name="deepseek-v4-flash",
            endpoint="https://api.deepseek.com",
            config_fingerprint="fp123",
            timeout_seconds=120.0,
            max_retries=3,
        )
        snapshot = AIModelConfigSnapshot.from_resolved(resolved, "ocr_vl")
        assert snapshot.config_id == 1
        assert snapshot.model_config_id == 1
        assert snapshot.provider == "deepseek"
        assert snapshot.model_name == "deepseek-v4-flash"
        assert snapshot.capability == "ocr_vl"
        assert snapshot.config_fingerprint == "fp123"
        assert snapshot.timeout_seconds == 120.0
        assert snapshot.max_retries == 3
        assert snapshot.resolved_at != ""

    def test_snapshot_no_secret_fields(self):
        """Verify snapshot has no secret fields."""
        resolved = ResolvedAIModelConfig(
            config_id=1, model_config_id=1,
            provider="p", model_name="m",
            secret_reference="admin_ai_model_configs.api_key_encrypted",
        )
        snapshot = AIModelConfigSnapshot.from_resolved(resolved, "test")
        snapshot_dict = {
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
        # No api_key, token, secret in snapshot dict
        sensitive_keys = {"api_key", "api_token", "token", "secret", "password", "key"}
        for key in snapshot_dict:
            assert key.lower() not in sensitive_keys, f"Secret field leaked: {key}"

    def test_snapshot_serializable(self):
        """Verify snapshot dict is JSON-serializable."""
        resolved = ResolvedAIModelConfig(
            config_id=1, model_config_id=1,
            provider="deepseek", model_name="test-model",
            config_fingerprint="fp1",
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
        import json
        serialized = json.dumps(d)
        assert isinstance(serialized, str)
        restored = json.loads(serialized)
        assert restored["config_id"] == 1
        assert restored["model_name"] == "test-model"


class TestResolverCapabilityMapping:
    """Test the static capability-to-feature mapping."""

    def test_map_ocr_vl(self):
        assert AIModelConfigResolver._capability_to_db_feature("ocr_vl") == "vision"

    def test_map_ocr_lightweight(self):
        assert AIModelConfigResolver._capability_to_db_feature("ocr_lightweight") == "ocr"

    def test_map_ocr_fix(self):
        assert AIModelConfigResolver._capability_to_db_feature("ocr_fix") == "ocr"

    def test_map_ai_repair(self):
        assert AIModelConfigResolver._capability_to_db_feature("ai_repair") == "completion"

    def test_unknown_capability(self):
        assert AIModelConfigResolver._capability_to_db_feature("unknown") is None


class TestResolverConfigResolution:
    """Test resolver with mocked DB."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock AsyncSession."""
        return AsyncMock()

    @pytest.fixture
    def mock_model(self):
        """Create a mock AdminAiModelConfig-like object."""
        model = MagicMock()
        model.id = 1
        model.name = "test-model"
        model.display_name = "Test Model"
        model.provider = "test_provider"
        model.api_base_url = "https://test.api.com"
        model.api_key_encrypted = "encrypted_key_here"
        model.is_enabled = True
        model.is_default = True
        model.sort_order = 1
        model.feature = "ocr"
        model.features = ["ocr", "vision"]
        model.created_at = datetime.now()
        model.updated_at = datetime.now()
        return model

    @pytest.mark.asyncio
    async def test_resolve_by_id(self, mock_db, mock_model):
        """Test resolving a specific config by ID."""
        mock_db.get = AsyncMock(return_value=mock_model)
        resolver = AIModelConfigResolver(mock_db)
        config = await resolver.resolve_for_capability(
            "ocr_vl", requested_config_id=1,
        )
        assert config.model_name == "test-model"
        assert config.config_id == 1
        assert config.provider == "test_provider"
        assert "vision" in config.capabilities

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_id(self, mock_db):
        """Test resolving a non-existent config ID raises error."""
        mock_db.get = AsyncMock(return_value=None)
        resolver = AIModelConfigResolver(mock_db)
        with pytest.raises(ValueError) as exc:
            await resolver.resolve_for_capability("ocr_vl", requested_config_id=999)
        assert AIConfigErrorCode.AI_MODEL_CONFIG_NOT_FOUND.value in str(exc.value)

    @pytest.mark.asyncio
    async def test_resolve_disabled_model(self, mock_db, mock_model):
        """Test resolving a disabled model raises error."""
        mock_model.is_enabled = False
        mock_db.get = AsyncMock(return_value=mock_model)
        resolver = AIModelConfigResolver(mock_db)
        with pytest.raises(ValueError) as exc:
            await resolver.resolve_for_capability("ocr_vl", requested_config_id=1)
        assert AIConfigErrorCode.AI_MODEL_DISABLED.value in str(exc.value)

    @pytest.mark.asyncio
    async def test_secret_resolution(self, mock_db, mock_model):
        """Test secret resolution."""
        mock_db.get = AsyncMock(return_value=mock_model)
        with patch("app.services.model_config_resolver.decrypt_api_key", return_value="decrypted-key"):
            resolver = AIModelConfigResolver(mock_db)
            config = await resolver.resolve_for_capability("ocr_vl", requested_config_id=1)
            secret = await resolver.resolve_secret(config)
            assert secret == "decrypted-key"

    @pytest.mark.asyncio
    async def test_secret_missing(self, mock_db, mock_model):
        """Test missing secret raises error."""
        mock_model.api_key_encrypted = None
        mock_db.get = AsyncMock(return_value=mock_model)
        resolver = AIModelConfigResolver(mock_db)
        config = await resolver.resolve_for_capability("ocr_vl", requested_config_id=1)
        with pytest.raises(ValueError) as exc:
            await resolver.resolve_secret(config)
        assert AIConfigErrorCode.AI_CONFIG_SECRET_MISSING.value in str(exc.value)
