"""Real compatibility baseline for embedding endpoint URL construction."""

from __future__ import annotations

import pytest

from app.services.embedding_endpoints import build_embeddings_url


class TestBuildEmbeddingsUrl:
    def test_empty_returns_empty(self):
        assert build_embeddings_url("") == ""

    def test_none_returns_empty(self):
        assert build_embeddings_url(None) == ""

    def test_openai_v1(self):
        result = build_embeddings_url("https://api.openai.com/v1")
        assert result.endswith("/v1/embeddings")

    def test_trailing_slash_stripped(self):
        result = build_embeddings_url("https://api.openai.com/v1/")
        assert result.endswith("/v1/embeddings")

    def test_full_embeddings_preserved(self):
        result = build_embeddings_url("https://api.openai.com/v1/embeddings")
        assert result == "https://api.openai.com/v1/embeddings"

    def test_compatible_mode_appends_v1(self):
        result = build_embeddings_url("https://dashscope.aliyuncs.com/compatible-mode")
        assert result.endswith("/compatible-mode/v1/embeddings")

    def test_compatible_mode_v1_appends_embeddings(self):
        result = build_embeddings_url("https://dashscope.aliyuncs.com/compatible-mode/v1")
        assert result.endswith("/compatible-mode/v1/embeddings")

    def test_alibaba_bare_host(self):
        result = build_embeddings_url("https://dashscope.aliyuncs.com")
        assert result.endswith("/compatible-mode/v1/embeddings")

    def test_alibaba_workspace_host(self):
        result = build_embeddings_url("https://test.maas.aliyuncs.com")
        assert result.endswith("/compatible-mode/v1/embeddings")

    def test_bare_host_appends_v1(self):
        result = build_embeddings_url("https://my-server.com")
        assert result.endswith("/v1/embeddings")

    def test_api_v3_path(self):
        result = build_embeddings_url("https://my-server.com/api/v3")
        assert result.endswith("/api/v3/embeddings")
