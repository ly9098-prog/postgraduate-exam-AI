"""Tests for AI capability model separation — verify OCR_FIX and AI_REPAIR resolve independently."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from app.services.model_config_resolver import (
    AICapability,
    AIModelConfigResolver,
    ResolvedAIModelConfig,
)


class TestAICapabilityModelSeparation:
    """Verify OCR_FIX and AI_REPAIR capabilities resolve to separate model configs."""

    def test_capability_maps_to_different_db_features(self):
        """OCR_FIX and AI_REPAIR map to different DB features."""
        ocr_fix_feature = AIModelConfigResolver._capability_to_db_feature("ocr_fix")
        ai_repair_feature = AIModelConfigResolver._capability_to_db_feature("ai_repair")

        assert ocr_fix_feature == "ocr"
        assert ai_repair_feature == "completion"
        assert ocr_fix_feature != ai_repair_feature

    @pytest.mark.asyncio
    async def test_resolve_different_models_for_each_capability(self):
        """OCR_FIX and AI_REPAIR can resolve to different provider/model."""
        ocr_fix_model = MagicMock()
        ocr_fix_model.id = 1
        ocr_fix_model.name = "paddleocr-vl-1.6"
        ocr_fix_model.display_name = "PaddleOCR VL 1.6"
        ocr_fix_model.provider = "paddleocr-vl"
        ocr_fix_model.api_base_url = "https://paddleocr.aistudio-app.com"
        ocr_fix_model.api_key_encrypted = "enc_ocr_fix"
        ocr_fix_model.is_enabled = True
        ocr_fix_model.is_default = False
        ocr_fix_model.sort_order = 1
        ocr_fix_model.feature = None
        ocr_fix_model.features = ["ocr", "vision"]
        ocr_fix_model.created_at = datetime.now()
        ocr_fix_model.updated_at = datetime.now()

        ai_repair_model = MagicMock()
        ai_repair_model.id = 2
        ai_repair_model.name = "deepseek-v4-flash"
        ai_repair_model.display_name = "DeepSeek V4 Flash"
        ai_repair_model.provider = "deepseek"
        ai_repair_model.api_base_url = "https://api.deepseek.com"
        ai_repair_model.api_key_encrypted = "enc_ai_repair"
        ai_repair_model.is_enabled = True
        ai_repair_model.is_default = True
        ai_repair_model.sort_order = 1
        ai_repair_model.feature = "completion"
        ai_repair_model.features = ["completion"]
        ai_repair_model.created_at = datetime.now()
        ai_repair_model.updated_at = datetime.now()

        mock_db = AsyncMock()

        # OCR_FIX query returns only the paddleocr model
        # AI_REPAIR query returns only the deepseek model
        # We use a side_effect to return different results per query
        mock_db.execute = AsyncMock()
        mock_db.execute.side_effect = [
            # First call: query for OCR_FIX → all_enabled models
            MagicMock(scalars=lambda: MagicMock(
                all=lambda: [ocr_fix_model, ai_repair_model],
            )),
            # Second call: query for AI_REPAIR → same models
            MagicMock(scalars=lambda: MagicMock(
                all=lambda: [ocr_fix_model, ai_repair_model],
            )),
        ]

        with patch(
            "app.services.model_config_resolver.decrypt_api_key",
            side_effect=["ocr-fix-secret", "ai-repair-secret"],
        ):
            resolver = AIModelConfigResolver(mock_db)

            # Resolve OCR_FIX → should match the "ocr" featured model (paddleocr-vl)
            ocr_fix_config = await resolver.resolve_for_capability(AICapability.OCR_FIX)
            assert ocr_fix_config.provider == "paddleocr-vl"
            assert ocr_fix_config.model_name == "paddleocr-vl-1.6"

            # Resolve AI_REPAIR → should match the "completion" featured model (deepseek)
            ai_repair_config = await resolver.resolve_for_capability(AICapability.AI_REPAIR)
            assert ai_repair_config.provider == "deepseek"
            assert ai_repair_config.model_name == "deepseek-v4-flash"

        # Different config IDs confirm separate model configs
        assert ocr_fix_config.config_id != ai_repair_config.config_id

    @pytest.mark.asyncio
    async def test_resolve_separate_secrets(self):
        """Each capability's model has its own secret."""
        ocr_fix_model = MagicMock()
        ocr_fix_model.id = 1
        ocr_fix_model.name = "ocr-fix-model"
        ocr_fix_model.provider = "deepseek"
        ocr_fix_model.api_base_url = "https://ocr-fix.deepseek.com"
        ocr_fix_model.api_key_encrypted = "enc_ocr_fix"
        ocr_fix_model.is_enabled = True
        ocr_fix_model.is_default = False
        ocr_fix_model.sort_order = 1
        ocr_fix_model.feature = None
        ocr_fix_model.features = ["ocr"]
        ocr_fix_model.created_at = datetime.now()
        ocr_fix_model.updated_at = datetime.now()

        ai_repair_model = MagicMock()
        ai_repair_model.id = 2
        ai_repair_model.name = "ai-repair-model"
        ai_repair_model.provider = "deepseek"
        ai_repair_model.api_base_url = "https://ai-repair.deepseek.com"
        ai_repair_model.api_key_encrypted = "enc_ai_repair"
        ai_repair_model.is_enabled = True
        ai_repair_model.is_default = False
        ai_repair_model.sort_order = 2
        ai_repair_model.feature = "completion"
        ai_repair_model.features = ["completion"]
        ai_repair_model.created_at = datetime.now()
        ai_repair_model.updated_at = datetime.now()

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=MagicMock(
                scalars=lambda: MagicMock(
                    all=lambda: [ocr_fix_model, ai_repair_model],
                ),
            ),
        )
        mock_db.get = AsyncMock()
        mock_db.get.side_effect = lambda model_cls, pk: {
            1: ocr_fix_model,
            2: ai_repair_model,
        }[pk]

        resolver = AIModelConfigResolver(mock_db)

        with patch(
            "app.services.model_config_resolver.decrypt_api_key",
            side_effect=["ocr-fix-secret-value", "ai-repair-secret-value"],
        ):
            ocr_fix_config = await resolver.resolve_for_capability(AICapability.OCR_FIX)
            ai_repair_config = await resolver.resolve_for_capability(AICapability.AI_REPAIR)

            ocr_fix_secret = await resolver.resolve_secret(ocr_fix_config)
            ai_repair_secret = await resolver.resolve_secret(ai_repair_config)

        assert ocr_fix_secret == "ocr-fix-secret-value"
        assert ai_repair_secret == "ai-repair-secret-value"
        assert ocr_fix_secret != ai_repair_secret

    @pytest.mark.asyncio
    async def test_same_model_can_serve_both_capabilities(self):
        """A single model with both 'ocr' and 'completion' features can serve both."""
        multi_model = MagicMock()
        multi_model.id = 1
        multi_model.name = "multi-capability-model"
        multi_model.provider = "deepseek"
        multi_model.api_base_url = "https://api.deepseek.com"
        multi_model.api_key_encrypted = "enc_multi"
        multi_model.is_enabled = True
        multi_model.is_default = True
        multi_model.sort_order = 1
        multi_model.feature = None
        multi_model.features = ["ocr", "completion", "vision"]
        multi_model.created_at = datetime.now()
        multi_model.updated_at = datetime.now()

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=MagicMock(
                scalars=lambda: MagicMock(
                    all=lambda: [multi_model],
                ),
            ),
        )

        with patch(
            "app.services.model_config_resolver.decrypt_api_key",
            return_value="same-secret",
        ):
            resolver = AIModelConfigResolver(mock_db)

            ocr_fix_config = await resolver.resolve_for_capability(AICapability.OCR_FIX)
            ai_repair_config = await resolver.resolve_for_capability(AICapability.AI_REPAIR)

        assert ocr_fix_config.config_id == ai_repair_config.config_id
        assert ocr_fix_config.model_name == "multi-capability-model"
        assert ai_repair_config.model_name == "multi-capability-model"
