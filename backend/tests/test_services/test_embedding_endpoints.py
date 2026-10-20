"""Characterize shared embedding URL rules and their request consumers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.embedding_endpoints import build_embeddings_url


@pytest.mark.parametrize(("base_url", "expected"), [
    ("", ""),
    (None, ""),
    (" \n/// ", ""),
    (" https://provider.example/// ", "https://provider.example/v1/embeddings"),
    ("https://provider.example/v1", "https://provider.example/v1/embeddings"),
    ("https://provider.example/api/v3/", "https://provider.example/api/v3/embeddings"),
    ("https://provider.example/v1/embeddings/", "https://provider.example/v1/embeddings"),
    ("https://provider.example/EMBEDDINGS", "https://provider.example/EMBEDDINGS"),
    ("https://provider.example/COMPATIBLE-MODE", "https://provider.example/COMPATIBLE-MODE/v1/embeddings"),
    ("https://provider.example/compatible-mode/v1", "https://provider.example/compatible-mode/v1/embeddings"),
    ("https://dashscope.aliyuncs.com", "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"),
    ("https://dashscope-intl.aliyuncs.com", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/embeddings"),
    ("https://cn-hongkong.dashscope.aliyuncs.com", "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1/embeddings"),
    ("https://workspace.maas.aliyuncs.com", "https://workspace.maas.aliyuncs.com/compatible-mode/v1/embeddings"),
    ("https://maas.aliyuncs.com", "https://maas.aliyuncs.com/v1/embeddings"),
    ("https://dashscope.aliyuncs.com.evil.example", "https://dashscope.aliyuncs.com.evil.example/v1/embeddings"),
    ("https://DASHSCOPE.ALIYUNCS.COM:443", "https://DASHSCOPE.ALIYUNCS.COM:443/compatible-mode/v1/embeddings"),
    ("https://dashscope.aliyuncs.com/custom", "https://dashscope.aliyuncs.com/custom/embeddings"),
    ("http://localhost:8000", "http://localhost:8000/v1/embeddings"),
    ("relative/path", "relative/path/embeddings"),
    # URL construction preserves historical query/fragment placement, not validation.
    ("https://provider.example/v1?test=1", "https://provider.example/v1?test=1/embeddings"),
    ("https://provider.example/#section", "https://provider.example/#section/v1/embeddings"),
])
def test_embedding_url_compatibility(base_url, expected):
    assert build_embeddings_url(base_url) == expected


def test_invalid_ipv6_url_keeps_parse_error():
    with pytest.raises(ValueError):
        build_embeddings_url("https://[invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize("base_url", [
    "https://provider.example/api/v3",
    "https://dashscope.aliyuncs.com",
    "https://provider.example/v1/embeddings",
])
async def test_single_batch_and_admin_probe_use_the_same_endpoint(monkeypatch, base_url):
    from app.services import embedding_service, safe_remote_fetch, vector_config_service

    cfg = vector_config_service.EmbeddingConfig(
        api_key="test-only-key", base_url=base_url, model="test-model",
        dim=2, timeout=13, batch_size=10,
    )
    request = AsyncMock(side_effect=[
        (200, {"data": [{"embedding": [0.1, 0.2]}]}),
        (200, {"data": [
            {"index": 1, "embedding": [0.3, 0.4]}, {"index": 0, "embedding": [0.1, 0.2]},
        ]}),
    ])
    monkeypatch.setattr(embedding_service, "_request_embeddings", request)
    expected_url = build_embeddings_url(base_url)
    assert await embedding_service.get_embedding(" first ", config=cfg) == [0.1, 0.2]
    assert await embedding_service.get_embeddings_batch(["", "first", "second"], config=cfg) == [
        None, [0.1, 0.2], [0.3, 0.4],
    ]
    assert request.await_args_list[0].args == (expected_url, {"model": "test-model", "input": " first "}, cfg)
    assert request.await_args_list[1].args == (expected_url, {"model": "test-model", "input": ["first", "second"]}, cfg)
    validate = Mock()
    remote = Mock(return_value=SimpleNamespace(
        status=200, data=json.dumps({"data": [{"embedding": [0.1, 0.2]}]}).encode(),
    ))
    monkeypatch.setattr(safe_remote_fetch, "validate_remote_url", validate)
    monkeypatch.setattr(safe_remote_fetch, "request_remote_bytes", remote)
    result = await vector_config_service.test_embedding_connection(
        base_url, "test-only-key", "test-model", dim=2, timeout=13,
    )
    assert result.success and result.returned_dim == 2
    validate.assert_called_once_with(base_url, allow_http=vector_config_service.settings.AI_ALLOW_HTTP_BASE_URLS)
    assert remote.call_args.args == (expected_url,)
    assert json.loads(remote.call_args.kwargs["body"]) == {"model": "test-model", "input": "test"}
    assert remote.call_args.kwargs["headers"]["Authorization"] == "Bearer test-only-key"
    assert remote.call_args.kwargs["timeout"] == 13.0
    assert remote.call_args.kwargs["follow_redirects"] is False
