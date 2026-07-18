"""Tests for AI Repair using admin AI config — verify _call_ai_for_repair uses AIModelConfigResolver."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.model_config_resolver import AICapability


class TestAIRepairUsesAdminAIConfig:
    """Verify AI Repair resolves credentials through AIModelConfigResolver."""

    @pytest.mark.asyncio
    async def test_call_ai_for_repair_uses_ai_repair_capability(self):
        """_call_ai_for_repair resolves with AICapability.AI_REPAIR when db is provided."""
        from app.features.ai_repair import _call_ai_for_repair

        mock_db = AsyncMock()
        mock_resolved = AsyncMock()
        mock_resolved.provider = "deepseek"
        mock_resolved.model_name = "deepseek-v4-flash"
        mock_resolved.endpoint = "https://api.deepseek.com"
        mock_resolved.timeout_seconds = 150.0

        mock_resolver = AsyncMock()
        mock_resolver.resolve_for_capability = AsyncMock(return_value=mock_resolved)
        mock_resolver.resolve_secret = AsyncMock(return_value="test-secret-key")

        with patch(
            "app.services.model_config_resolver.AIModelConfigResolver",
            return_value=mock_resolver,
        ):
            with patch("app.ai.client.deepseek") as mock_deepseek:
                mock_deepseek.chat = AsyncMock(
                    return_value={
                        "content": '{"stem": "repaired"}',
                        "tokens_used": 100,
                    },
                )
                with patch("app.features.ai_repair.check_token_limit", return_value=True):
                    result = await _call_ai_for_repair(
                        "test text", {},
                        {"daily_token_limit": 100000},
                        db=mock_db,
                    )

        # Verify resolver was called with AI_REPAIR capability
        mock_resolver.resolve_for_capability.assert_called_once_with(AICapability.AI_REPAIR)

        # Verify the resolved secret was passed to deepseek.chat
        _, kwargs = mock_deepseek.chat.call_args
        assert kwargs.get("api_key") == "test-secret-key"
        assert kwargs.get("base_url") == "https://api.deepseek.com"

        assert result is not None

    @pytest.mark.asyncio
    async def test_call_ai_for_repair_no_db_fallback(self):
        """When db is None, _call_ai_for_repair falls back to passed credentials."""
        from app.features.ai_repair import _call_ai_for_repair

        with patch("app.ai.client.deepseek") as mock_deepseek:
            mock_deepseek.chat = AsyncMock(
                return_value={
                    "content": '{"stem": "repaired"}',
                    "tokens_used": 100,
                },
            )
            with patch("app.features.ai_repair.check_token_limit", return_value=True):
                result = await _call_ai_for_repair(
                    "test text", {},
                    {"daily_token_limit": 100000},
                    db=None,
                    api_key="env-api-key",
                    base_url="https://env.deepseek.com",
                    model_name="env-model",
                )

        _, kwargs = mock_deepseek.chat.call_args
        assert kwargs.get("api_key") == "env-api-key"
        assert kwargs.get("base_url") == "https://env.deepseek.com"
        assert result is not None

    @pytest.mark.asyncio
    async def test_call_ai_for_repair_resolver_failure_graceful(self):
        """When resolver raises, _call_ai_for_repair falls back gracefully."""
        from app.features.ai_repair import _call_ai_for_repair

        mock_db = AsyncMock()
        mock_resolver = AsyncMock()
        mock_resolver.resolve_for_capability = AsyncMock(
            side_effect=ValueError("No enabled model"),
        )

        with patch(
            "app.services.model_config_resolver.AIModelConfigResolver",
            return_value=mock_resolver,
        ):
            with patch("app.ai.client.deepseek") as mock_deepseek:
                mock_deepseek.chat = AsyncMock(
                    return_value={
                        "content": '{"stem": "repaired"}',
                        "tokens_used": 100,
                    },
                )
                with patch("app.features.ai_repair.check_token_limit", return_value=True):
                    result = await _call_ai_for_repair(
                        "test text", {},
                        {"daily_token_limit": 100000},
                        db=mock_db,
                    )

        # DeepSeek client called with None credentials (falls back to env vars)
        _, kwargs = mock_deepseek.chat.call_args
        assert kwargs.get("api_key") is None
        assert result is not None

    @pytest.mark.asyncio
    async def test_call_ai_for_batch_repair_uses_ai_repair_capability(self):
        """_call_ai_for_batch_repair resolves with AICapability.AI_REPAIR."""
        from app.features.ai_repair import _call_ai_for_batch_repair

        mock_db = AsyncMock()
        mock_resolved = AsyncMock()
        mock_resolved.provider = "deepseek"
        mock_resolved.model_name = "deepseek-v4-flash"
        mock_resolved.endpoint = "https://api.deepseek.com"

        mock_resolver = AsyncMock()
        mock_resolver.resolve_for_capability = AsyncMock(return_value=mock_resolved)
        mock_resolver.resolve_secret = AsyncMock(return_value="test-secret-key")

        with patch(
            "app.services.model_config_resolver.AIModelConfigResolver",
            return_value=mock_resolver,
        ):
            with patch("app.ai.client.deepseek") as mock_deepseek:
                mock_deepseek.chat = AsyncMock(
                    return_value={
                        "content": '[{"stem": "fixed"}]',
                        "tokens_used": 200,
                    },
                )
                with patch("app.features.ai_repair.check_token_limit", return_value=True):
                    candidates = [(0, {}, "text")]
                    results = await _call_ai_for_batch_repair(
                        candidates, {"daily_token_limit": 100000}, db=mock_db,
                    )

        mock_resolver.resolve_for_capability.assert_called_once_with(AICapability.AI_REPAIR)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_call_ai_for_roman_decision_uses_ai_repair_capability(self):
        """_call_ai_for_roman_decision resolves with AICapability.AI_REPAIR."""
        from app.features.ai_repair import _call_ai_for_roman_decision

        mock_db = AsyncMock()
        mock_resolved = AsyncMock()
        mock_resolved.provider = "deepseek"
        mock_resolved.model_name = "deepseek-v4-flash"
        mock_resolved.endpoint = "https://api.deepseek.com"

        mock_resolver = AsyncMock()
        mock_resolver.resolve_for_capability = AsyncMock(return_value=mock_resolved)
        mock_resolver.resolve_secret = AsyncMock(return_value="test-secret-key")

        with patch(
            "app.services.model_config_resolver.AIModelConfigResolver",
            return_value=mock_resolver,
        ):
            with patch("app.ai.client.deepseek") as mock_deepseek:
                mock_deepseek.chat = AsyncMock(
                    return_value={
                        "content": '{"decisions": []}',
                        "tokens_used": 50,
                    },
                )
                with patch("app.features.ai_repair.check_token_limit", return_value=True):
                    result = await _call_ai_for_roman_decision(
                        {"id": 1}, [], {"daily_token_limit": 100000}, db=mock_db,
                    )

        mock_resolver.resolve_for_capability.assert_called_once_with(AICapability.AI_REPAIR)
        assert result is not None

    @pytest.mark.asyncio
    async def test_env_api_key_forwarded_when_resolver_not_used(self):
        """When api_key is passed directly, resolver is not consulted."""
        from app.features.ai_repair import _call_ai_for_repair

        mock_db = AsyncMock()

        with patch(
            "app.services.model_config_resolver.AIModelConfigResolver",
        ) as mock_resolver_cls:
            with patch("app.ai.client.deepseek") as mock_deepseek:
                mock_deepseek.chat = AsyncMock(
                    return_value={
                        "content": '{"stem": "ok"}',
                        "tokens_used": 50,
                    },
                )
                with patch("app.features.ai_repair.check_token_limit", return_value=True):
                    await _call_ai_for_repair(
                        "text", {},
                        {"daily_token_limit": 100000},
                        db=mock_db,
                        api_key="direct-key",
                        base_url="https://direct.api.com",
                    )

        # Resolver should NOT be instantiated when api_key is provided
        mock_resolver_cls.assert_not_called()
