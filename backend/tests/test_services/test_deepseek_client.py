"""Regression tests for DeepSeek client model=None fallback.

Covers:
1. DeepSeekClient.chat() 内部兜底 model=None → 默认模型
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
async def test_chat_model_none_falls_back():
    """model=None 时应使用默认模型名（字符串）。"""
    client = _make_client()

    with patch("app.ai.client.request_remote_bytes", return_value=_make_remote()) as mock_req:
        result = await client.chat(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
        )

    assert result is not None
    request_body = mock_req.call_args.args[0]
    assert "/v1/chat/completions" in request_body
    payload = json.loads(mock_req.call_args.kwargs["body"])
    assert isinstance(payload["model"], str), f"model 应是字符串, 实际: {payload['model']}"
    assert payload["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_chat_model_none_no_settings_field():
    """没有显式模型配置时也应兜底到默认模型名。"""
    client = DeepSeekClient()
    client._api_key = "sk-test-key"
    client._base_url = "https://api.deepseek.com"
    client.timeout = 60

    with patch("app.ai.client.request_remote_bytes", return_value=_make_remote()) as mock_req:
        result = await client.chat(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
        )

    assert result is not None
    payload = json.loads(mock_req.call_args.kwargs["body"])
    assert isinstance(payload["model"], str)
    assert payload["model"] == "deepseek-v4-flash"


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
async def test_chat_model_none_sentry_tag_uses_fallback():
    """Sentry tag 应使用兜底后的模型名。"""
    client = _make_client()

    with patch("app.ai.client.request_remote_bytes", return_value=_make_remote()), \
         patch("app.ai.client.set_tag") as mock_set_tag:
        await client.chat(messages=[{"role": "user", "content": "hi"}], model=None)

    ai_model_calls = [
        call for call in mock_set_tag.call_args_list
        if call.args[0] == "ai.model"
    ]
    assert ai_model_calls, "应调用 set_tag('ai.model', ...)"
    model_value = ai_model_calls[0].args[1]
    assert isinstance(model_value, str), f"model tag 应是字符串: {model_value}"
