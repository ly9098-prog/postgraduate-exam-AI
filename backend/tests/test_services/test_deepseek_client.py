"""Regression tests for DeepSeek client model configuration.

Covers:
1. DeepSeekClient.chat() 在 model=None 时直接失败，禁止恢复隐藏默认模型
2. 显式传模型名时不被覆盖
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.ai.client import DeepSeekClient
from app.services.safe_remote_fetch import RemoteResponse


def _make_remote(status=200, model="deepseek-v4-flash"):
    """Build a RemoteResponse with a chat-completions body."""
    data = json.dumps({
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"total_tokens": 10},
        "model": model,
    }).encode("utf-8")
    return RemoteResponse(
        status=status, data=data,
        content_type="application/json", final_url="https://api.deepseek.com",
    )


def _make_client(api_key="sk-test-key", base_url="https://api.deepseek.com"):
    """Create a client instance with the key configured for runtime use."""
    client = DeepSeekClient()
    client._api_key = api_key
    client._base_url = base_url
    client.timeout = 60
    return client


@pytest.mark.asyncio
async def test_chat_model_none_is_rejected():
    """model=None 时应失败关闭，要求后台配置模型标识。"""
    client = _make_client()

    with patch("app.ai.client.request_remote_bytes") as mock_req, \
            pytest.raises(RuntimeError, match="AI模型标识未配置"):
        await client.chat(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
        )

    mock_req.assert_not_called()


@pytest.mark.asyncio
async def test_chat_passes_model_str():
    """显式传模型名时不应被兜底覆盖。"""
    client = _make_client()

    with patch("app.ai.client.request_remote_bytes",
               return_value=_make_remote(model="custom-model")) as mock_req:
        await client.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="custom-model",
        )

    payload = json.loads(mock_req.call_args.kwargs["body"])
    assert payload["model"] == "custom-model"


@pytest.mark.asyncio
async def test_chat_model_none_does_not_start_request_or_tag():
    """model=None 时不发请求，也不上报缺失模型的 Sentry tag。"""
    client = _make_client()

    with patch("app.ai.client.request_remote_bytes") as mock_req, \
            patch("app.ai.client.set_tag") as mock_set_tag, \
            pytest.raises(RuntimeError, match="AI模型标识未配置"):
        await client.chat(messages=[{"role": "user", "content": "hi"}], model=None)

    mock_req.assert_not_called()
    mock_set_tag.assert_not_called()
