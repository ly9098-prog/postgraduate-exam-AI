"""Tests for AI repair using the current gateway runtime contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.model_config_resolver import AICapability


def _runtime(**overrides):
    values = {
        "api_key": "test-secret-key",
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-v4-flash",
        "provider": "deepseek",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _chat_result(content: str = '{"stem": "repaired"}', tokens: int = 100):
    return {"content": content, "tokens_used": tokens}


class TestAIRepairUsesAdminAIConfig:
    @pytest.mark.asyncio
    async def test_call_ai_for_repair_uses_ai_repair_capability(self):
        from app.features.ai_repair import _call_ai_for_repair

        runtime = _runtime()
        with (
            patch("app.ai.gateway.resolve_llm_runtime_config", new=AsyncMock(return_value=runtime)) as resolve,
            patch("app.ai.client.llm.chat", new=AsyncMock(return_value=_chat_result())) as chat,
            patch("app.features.ai_repair.check_token_limit", return_value=True),
        ):
            result = await _call_ai_for_repair(
                "test text", {}, {"daily_token_limit": 100000}, db=AsyncMock()
            )

        assert resolve.await_args.kwargs["capability"] == AICapability.AI_REPAIR
        assert chat.call_args.kwargs["api_key"] == "test-secret-key"
        assert chat.call_args.kwargs["base_url"] == "https://api.deepseek.com"
        assert result is not None

    @pytest.mark.asyncio
    async def test_call_ai_for_repair_no_db_fallback(self):
        from app.features.ai_repair import _call_ai_for_repair

        with (
            patch("app.ai.client.llm.chat", new=AsyncMock(return_value=_chat_result())) as chat,
            patch("app.features.ai_repair.check_token_limit", return_value=True),
        ):
            result = await _call_ai_for_repair(
                "test text", {}, {"daily_token_limit": 100000},
                api_key="env-api-key", base_url="https://env.deepseek.com", model_name="env-model",
            )

        assert chat.call_args.kwargs["api_key"] == "env-api-key"
        assert chat.call_args.kwargs["base_url"] == "https://env.deepseek.com"
        assert result is not None

    @pytest.mark.asyncio
    async def test_call_ai_for_repair_resolver_failure_graceful(self):
        from app.features.ai_repair import _call_ai_for_repair

        with (
            patch("app.ai.gateway.resolve_llm_runtime_config", new=AsyncMock(return_value=None)),
            patch("app.ai.client.llm.chat", new=AsyncMock(return_value=_chat_result())) as chat,
            patch("app.features.ai_repair.check_token_limit", return_value=True),
        ):
            result = await _call_ai_for_repair(
                "test text", {}, {"daily_token_limit": 100000}, db=AsyncMock()
            )

        assert chat.call_args.kwargs["api_key"] is None
        assert result is not None

    @pytest.mark.asyncio
    async def test_direct_credentials_skip_runtime_resolution(self):
        from app.features.ai_repair import _call_ai_for_repair

        with (
            patch("app.ai.gateway.resolve_llm_runtime_config", new=AsyncMock()) as resolve,
            patch("app.ai.client.llm.chat", new=AsyncMock(return_value=_chat_result())) as chat,
            patch("app.features.ai_repair.check_token_limit", return_value=True),
        ):
            await _call_ai_for_repair(
                "text", {}, {"daily_token_limit": 100000}, db=AsyncMock(),
                api_key="direct-key", base_url="https://direct.api.com",
            )

        resolve.assert_not_awaited()
        assert chat.call_args.kwargs["api_key"] == "direct-key"

    @pytest.mark.asyncio
    async def test_batch_and_roman_paths_use_ai_repair_capability(self):
        from app.features.ai_repair import (
            _call_ai_for_batch_repair,
            _call_ai_for_roman_decision,
        )

        runtime = _runtime()
        with (
            patch("app.ai.gateway.resolve_llm_runtime_config", new=AsyncMock(return_value=runtime)) as resolve,
            patch("app.ai.client.llm.chat", new=AsyncMock(side_effect=[
                _chat_result('[{"stem": "fixed"}]', 200),
                _chat_result('{"decisions": []}', 50),
            ])),
            patch("app.features.ai_repair.check_token_limit", return_value=True),
        ):
            results = await _call_ai_for_batch_repair(
                [(0, {}, "text")], {"daily_token_limit": 100000}, db=AsyncMock()
            )
            roman = await _call_ai_for_roman_decision(
                {"id": 1}, [], {"daily_token_limit": 100000}, db=AsyncMock()
            )

        assert len(results) == 1
        assert roman is not None
        assert resolve.await_count == 2
