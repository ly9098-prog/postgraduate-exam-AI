"""Tests for OCR Fix using admin AI config — verify _build_router_config uses AIModelConfigResolver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.features.ocr_fix.router import STRATEGY_AUTO
from app.services.model_config_resolver import AICapability


class TestOCRFixUsesAdminAIConfig:
    """Verify OCR Fix router config resolves through AIModelConfigResolver."""

    @pytest.mark.asyncio
    async def test_build_router_config_uses_ocr_fix_capability(self):
        """_build_router_config calls resolve_for_capability with OCR_FIX."""
        from app.features.pipeline_orchestrator import ImportPipeline

        mock_db = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.provider = "deepseek"
        mock_resolved.model_name = "deepseek-v4-flash"
        mock_resolved.endpoint = "https://api.deepseek.com"
        mock_resolved.timeout_seconds = 150.0
        mock_resolved.max_retries = 2

        mock_resolver = AsyncMock()
        mock_resolver.resolve_for_capability = AsyncMock(return_value=mock_resolved)
        mock_resolver.resolve_secret = AsyncMock(return_value="test-secret-key")

        orchestrator = ImportPipeline()

        with patch(
            "app.services.model_config_resolver.AIModelConfigResolver",
            return_value=mock_resolver,
        ):
            config = await orchestrator._build_router_config({}, mock_db)

        # Verify resolver was called with OCR_FIX capability
        mock_resolver.resolve_for_capability.assert_any_call(AICapability.OCR_FIX)

        # Verify the config dict contains the resolved values
        assert config.get("deepseek_api_key") == "test-secret-key"
        assert config.get("deepseek_base_url") == "https://api.deepseek.com"

    @pytest.mark.asyncio
    async def test_build_router_config_paddleocr_vl_provider(self):
        """PaddleOCR-VL provider maps to paddleocr_vl_* config keys."""
        from app.features.pipeline_orchestrator import ImportPipeline

        mock_db = AsyncMock()
        mock_resolved = MagicMock()
        mock_resolved.provider = "paddleocr-vl"
        mock_resolved.model_name = "PaddleOCR-VL-1.6"
        mock_resolved.endpoint = "https://paddleocr.aistudio-app.com"
        mock_resolved.timeout_seconds = 300.0
        mock_resolved.max_retries = 3

        mock_resolver = AsyncMock()
        mock_resolver.resolve_for_capability = AsyncMock(return_value=mock_resolved)
        mock_resolver.resolve_secret = AsyncMock(return_value="test-vl-token")

        orchestrator = ImportPipeline()

        with patch(
            "app.services.model_config_resolver.AIModelConfigResolver",
            return_value=mock_resolver,
        ):
            config = await orchestrator._build_router_config({}, mock_db)

        mock_resolver.resolve_for_capability.assert_any_call(AICapability.OCR_FIX)
        assert config.get("paddleocr_vl_api_token") == "test-vl-token"
        assert config.get("paddleocr_vl_base_url") == "https://paddleocr.aistudio-app.com"
        assert config.get("paddleocr_vl_model") == "PaddleOCR-VL-1.6"

    @pytest.mark.asyncio
    async def test_build_router_config_resolver_failure_graceful(self):
        """When resolver raises, _build_router_config degrades gracefully."""
        from app.features.pipeline_orchestrator import ImportPipeline

        mock_db = AsyncMock()
        mock_resolver = AsyncMock()
        mock_resolver.resolve_for_capability = AsyncMock(
            side_effect=ValueError("No enabled model"),
        )

        orchestrator = ImportPipeline()

        with patch(
            "app.services.model_config_resolver.AIModelConfigResolver",
            return_value=mock_resolver,
        ):
            config = await orchestrator._build_router_config({}, mock_db)

        # Should not crash — gracefully degrades to env var fallback
        assert isinstance(config, dict)
        assert "mode" in config

    @pytest.mark.asyncio
    async def test_build_router_config_uses_ai_repair_fallback(self):
        """When OCR_FIX resolves to non-DeepSeek, AI_REPAIR is used as fallback."""
        from app.features.pipeline_orchestrator import ImportPipeline

        mock_db = AsyncMock()

        # OCR_FIX resolves to paddleocr-vl (no deepseek keys set)
        ocr_fix_resolved = MagicMock()
        ocr_fix_resolved.provider = "paddleocr-vl"
        ocr_fix_resolved.model_name = "PaddleOCR-VL-1.6"
        ocr_fix_resolved.endpoint = "https://paddleocr.aistudio-app.com"

        # AI_REPAIR resolves to deepseek (fallback)
        ai_repair_resolved = MagicMock()
        ai_repair_resolved.provider = "deepseek"
        ai_repair_resolved.model_name = "deepseek-v4-flash"
        ai_repair_resolved.endpoint = "https://api.deepseek.com"

        mock_resolver = AsyncMock()
        mock_resolver.resolve_for_capability = AsyncMock(
            side_effect=[ocr_fix_resolved, ai_repair_resolved],
        )
        mock_resolver.resolve_secret = AsyncMock(return_value="test-secret-key")

        orchestrator = ImportPipeline()

        with patch(
            "app.services.model_config_resolver.AIModelConfigResolver",
            return_value=mock_resolver,
        ):
            config = await orchestrator._build_router_config({}, mock_db)

        # OCR_FIX keys present
        assert config.get("paddleocr_vl_api_token") == "test-secret-key"
        assert config.get("paddleocr_vl_base_url") == "https://paddleocr.aistudio-app.com"

        # AI_REPAIR fallback keys present
        assert config.get("deepseek_api_key") == "test-secret-key"
        assert config.get("deepseek_base_url") == "https://api.deepseek.com"

        # Both capabilities were queried
        mock_resolver.resolve_for_capability.assert_any_call(AICapability.OCR_FIX)
        mock_resolver.resolve_for_capability.assert_any_call(AICapability.AI_REPAIR)

    @pytest.mark.asyncio
    async def test_opts_forwarded_to_config(self):
        """Pipeline opts (mode, strategy) are forwarded to router config."""
        from app.features.pipeline_orchestrator import ImportPipeline

        opts = {
            "ocr_correction_mode": "auto",
            "ocr_noise_threshold": 0.5,
            "ocr_fix_strategy": STRATEGY_AUTO,
        }

        orchestrator = ImportPipeline()
        config = await orchestrator._build_router_config(opts, db=None)

        assert config.get("mode") == "auto"
        assert config.get("noise_threshold") == 0.5
        assert config.get("ocr_fix_strategy") == STRATEGY_AUTO
