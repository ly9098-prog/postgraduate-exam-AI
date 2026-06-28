"""Regression tests for DeepSeek client model=None fallback.

Covers:
1. DeepSeekClient.chat() 内部兜底 model=None → 默认模型
2. 显式传模型名时不被覆盖
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.client import DeepSeekClient


def _make_mock_response(status=200, model="deepseek-v4-flash"):
    """httpx.Response.json() 是同步方法，使用 MagicMock 而非 AsyncMock。"""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"total_tokens": 10},
        "model": model,
    }
    return resp


def _make_client(api_key="sk-test-key", base_url="https://api.deepseek.com"):
    """Create a client instance with patched settings."""
    with patch("app.ai.client.settings") as ms:
        ms.DEEPSEEK_API_KEY = api_key
        ms.DEEPSEEK_BASE_URL = base_url
        ms.DEEPSEEK_MODEL = "deepseek-v4-flash"
        ms.AI_TIMEOUT = 60
        return DeepSeekClient()


@pytest.mark.asyncio
async def test_chat_model_none_falls_back():
    """model=None 时应使用 settings.DEEPSEEK_MODEL 或硬编码默认值。"""
    client = _make_client()
    client._client = AsyncMock()
    client._client.post.return_value = _make_mock_response()

    result = await client.chat(
        messages=[{"role": "user", "content": "hello"}],
        model=None,
    )

    assert result is not None
    payload = client._client.post.call_args.kwargs["json"]
    assert isinstance(payload["model"], str), f"model 应是字符串, 实际: {payload['model']}"
    assert payload["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_chat_model_none_no_settings_field():
    """settings 没有 DEEPSEEK_MODEL 字段时也应兜底到硬编码默认值。"""
    with patch("app.ai.client.settings", spec=object()) as ms:
        ms.DEEPSEEK_API_KEY = "sk-test-key"
        ms.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        ms.AI_TIMEOUT = 60
        client = DeepSeekClient()

    client._client = AsyncMock()
    client._client.post.return_value = _make_mock_response()

    result = await client.chat(
        messages=[{"role": "user", "content": "hello"}],
        model=None,
    )

    assert result is not None
    payload = client._client.post.call_args.kwargs["json"]
    assert isinstance(payload["model"], str)
    assert payload["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_chat_passes_model_str():
    """显式传模型名时不应被兜底覆盖。"""
    client = _make_client()
    client._client = AsyncMock()
    client._client.post.return_value = _make_mock_response(model="custom-model")

    await client.chat(
        messages=[{"role": "user", "content": "hello"}],
        model="custom-model",
    )

    payload = client._client.post.call_args.kwargs["json"]
    assert payload["model"] == "custom-model"


@pytest.mark.asyncio
async def test_chat_model_none_sentry_tag_uses_fallback():
    """Sentry tag 应使用兜底后的模型名。"""
    client = _make_client()
    client._client = AsyncMock()
    client._client.post.return_value = _make_mock_response()

    with patch("app.ai.client.set_tag") as mock_set_tag:
        await client.chat(messages=[{"role": "user", "content": "hi"}], model=None)

    ai_model_calls = [
        call for call in mock_set_tag.call_args_list
        if call.args[0] == "ai.model"
    ]
    assert ai_model_calls, "应调用 set_tag('ai.model', ...)"
    model_value = ai_model_calls[0].args[1]
    assert isinstance(model_value, str), f"model tag 应是字符串: {model_value}"
