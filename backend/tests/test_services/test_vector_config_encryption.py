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
        from app.schemas.admin_ai_config import AdminAiModelConfigPatchRequest

        req = AdminAiModelConfigPatchRequest(api_key="****")
        val = req.get_api_key_value()
        assert val is None

        req2 = AdminAiModelConfigPatchRequest(api_key="********")
        val2 = req2.get_api_key_value()
        assert val2 is None

    def test_empty_string_treated_as_no_key(self):
        """Empty string should be treated as no key provided."""
        from app.schemas.admin_ai_config import AdminAiModelConfigPatchRequest

        req = AdminAiModelConfigPatchRequest(api_key="")
        val = req.get_api_key_value()
        assert val is None

    def test_real_key_passes_through(self):
        from app.schemas.admin_ai_config import AdminAiModelConfigPatchRequest

        req = AdminAiModelConfigPatchRequest(api_key=TEST_API_KEY)
        val = req.get_api_key_value()
        assert val == TEST_API_KEY

    def test_embedding_test_request_handles_mask(self):
        """EmbeddingTestRequest's get_api_key_value must reject masks."""
        from app.schemas.admin_ai_config import ModelTestConnectionRequest

        req = ModelTestConnectionRequest(
            api_base_url="https://test.com",
            api_key="****",
            model_name="test-model",
        )
        assert req.get_api_key_value() is None

        req2 = ModelTestConnectionRequest(
            api_base_url="https://test.com",
            api_key=TEST_API_KEY,
            model_name="test-model",
        )
        assert req2.get_api_key_value() == TEST_API_KEY

    def test_embedding_api_key_not_in_repr(self):
        """SecretStr must prevent api_key from appearing in repr/str."""
        from app.schemas.admin_ai_config import AdminAiModelConfigPatchRequest

        req = AdminAiModelConfigPatchRequest(api_key=TEST_API_KEY)
        dump = str(req.model_dump())
        assert TEST_API_KEY not in dump
