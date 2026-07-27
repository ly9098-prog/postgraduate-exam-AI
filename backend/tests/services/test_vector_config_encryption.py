"""Tests for admin_vector_config encryption safety."""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from app.core.secret_crypto import ENCRYPTED_PREFIX

TEST_FERNET_KEY = Fernet.generate_key().decode()
TEST_API_KEY = "sk-test-embedding-123456"


def _set_key(key: str | None):
    os.environ["AI_CONFIG_ENCRYPT_KEY"] = key or ""
    from app.core.config import settings
    settings.AI_CONFIG_ENCRYPT_KEY = key or ""


class TestVectorConfigEncryption:
    def setup_method(self):
        _set_key(TEST_FERNET_KEY)

    def test_mask_placeholder_not_saved(self):
        """Mask placeholders like '****' must not be encrypted/stored."""
        from app.schemas.admin_vector_config import VectorConfigPatchRequest

        req = VectorConfigPatchRequest(embedding_api_key="****")
        val = req.get_embedding_api_key_value()
        assert val is None

        req2 = VectorConfigPatchRequest(embedding_api_key="********")
        val2 = req2.get_embedding_api_key_value()
        assert val2 is None

    def test_empty_string_means_clear(self):
        """Empty string should be treated as explicit clear, not ignored."""
        from app.schemas.admin_vector_config import VectorConfigPatchRequest

        req = VectorConfigPatchRequest(embedding_api_key="")
        val = req.get_embedding_api_key_value()
        # Empty string means "clear the key"
        assert val is not None
        assert val == ""

    def test_real_key_passes_through(self):
        from app.schemas.admin_vector_config import VectorConfigPatchRequest

        req = VectorConfigPatchRequest(embedding_api_key=TEST_API_KEY)
        val = req.get_embedding_api_key_value()
        assert val == TEST_API_KEY

    @pytest.mark.asyncio
    async def test_to_response_fixed_mask(self):
        """_to_response must return '********', not variable-length mask."""
        from app.core.secret_crypto import encrypt_secret
        from app.models.admin_vector_config import AdminVectorConfig

        row = AdminVectorConfig(
            id=1,
            vector_enabled=False,
            vector_mode="off",
            vector_allowlist="",
            vector_cache_ttl_sec=300,
            vector_top_k=100,
            vector_similarity_threshold=0.15,
            embedding_provider="openai_compatible",
            embedding_base_url="",
            embedding_model="BAAI/bge-m3",
            embedding_dim=1024,
            embedding_timeout=30,
            embedding_batch_size=16,
            embedding_api_key_encrypted=encrypt_secret(TEST_API_KEY),
        )
        from app.services.vector_config_service import _to_response
        resp = _to_response(row)

        assert resp.embedding_api_key_configured is True
        assert resp.embedding_api_key_masked == "********"
        assert TEST_API_KEY not in str(resp.model_dump())

    def test_embedding_test_request_handles_mask(self):
        """EmbeddingTestRequest's get_api_key_value must reject masks."""
        from app.schemas.admin_vector_config import EmbeddingTestRequest

        req = EmbeddingTestRequest(
            api_base_url="https://test.com",
            api_key="****",
            model="test-model",
        )
        assert req.get_api_key_value() is None

        req2 = EmbeddingTestRequest(
            api_base_url="https://test.com",
            api_key=TEST_API_KEY,
            model="test-model",
        )
        assert req2.get_api_key_value() == TEST_API_KEY

    def test_embedding_api_key_not_in_repr(self):
        """SecretStr must prevent api_key from appearing in repr/str."""
        from app.schemas.admin_vector_config import VectorConfigPatchRequest

        req = VectorConfigPatchRequest(embedding_api_key=TEST_API_KEY)
        dump = str(req.model_dump())
        assert TEST_API_KEY not in dump
