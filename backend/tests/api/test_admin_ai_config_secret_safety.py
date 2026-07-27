"""Tests for AI model config API response safety — no plaintext keys in responses."""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

TEST_FERNET_KEY = Fernet.generate_key().decode()
TEST_API_KEY = "sk-test-api-do-not-use"


def _set_key(key: str | None):
    os.environ["AI_CONFIG_ENCRYPT_KEY"] = key or ""
    from app.core.config import settings
    settings.AI_CONFIG_ENCRYPT_KEY = key or ""


class TestModelConfigResponseSafety:
    """API response must never expose API key plaintext."""

    def setup_method(self):
        _set_key(TEST_FERNET_KEY)

    def test_response_has_no_api_key_field(self):
        """AdminAiModelConfigResponse must not contain api_key field."""
        from app.schemas.admin_ai_config import AdminAiModelConfigResponse

        # Verify the schema does NOT have an api_key field
        schema_fields = AdminAiModelConfigResponse.model_fields
        assert "api_key" not in schema_fields, (
            "Response schema must not contain api_key field"
        )
        assert "api_key_masked" in schema_fields
        assert "api_configured" in schema_fields

    def test_masked_field_is_fixed_length(self):
        """api_key_masked must always be '********' (fixed length)."""
        from app.core.secret_crypto import encrypt_secret
        from app.models.admin_ai_config import AdminAiModelConfig
        from app.services.admin_ai_config_service import _model_to_response

        model = AdminAiModelConfig(
            id=1, name="test", display_name="test", provider="deepseek",
            is_enabled=True, is_default=False, sort_order=0,
            api_key_encrypted=encrypt_secret(TEST_API_KEY),
        )
        resp = _model_to_response(model)
        assert resp.api_key_masked == "********"

    def test_masked_not_variable_length(self):
        """The masked value must not reveal key length."""
        from app.core.secret_crypto import encrypt_secret
        from app.models.admin_ai_config import AdminAiModelConfig
        from app.services.admin_ai_config_service import _model_to_response

        short_key = encrypt_secret("sk-short")
        long_key = encrypt_secret("sk-this-is-a-very-long-api-key-for-testing-purposes")

        short_model = AdminAiModelConfig(
            id=2, name="short", display_name="s", provider="deepseek",
            is_enabled=True, is_default=False, sort_order=0,
            api_key_encrypted=short_key,
        )
        long_model = AdminAiModelConfig(
            id=3, name="long", display_name="l", provider="deepseek",
            is_enabled=True, is_default=False, sort_order=0,
            api_key_encrypted=long_key,
        )

        short_resp = _model_to_response(short_model)
        long_resp = _model_to_response(long_model)

        assert short_resp.api_key_masked == long_resp.api_key_masked
        assert short_resp.api_key_masked == "********"

    def _full_vector_row(self, **kw):
        from app.models.admin_vector_config import AdminVectorConfig

        defaults = dict(
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
        )
        defaults.update(kw)
        row = AdminVectorConfig(**defaults)
        return row

    def test_vector_response_masked_is_fixed(self):
        from app.core.secret_crypto import encrypt_secret
        from app.services.vector_config_service import _to_response

        row = self._full_vector_row(
            embedding_api_key_encrypted=encrypt_secret(TEST_API_KEY),
        )
        resp = _to_response(row)
        assert resp.embedding_api_key_masked == "********"

    def test_vector_response_decrypt_failure_no_leak(self):
        """Decrypt failure must not return 'not configured' — return False."""
        from app.models.admin_vector_config import AdminVectorConfig
        from app.services.vector_config_service import _to_response

        # Set a value that can't be decrypted
        _set_key(Fernet.generate_key().decode())
        from app.core.secret_crypto import encrypt_secret
        _set_key(TEST_FERNET_KEY)
        encrypted = encrypt_secret(TEST_API_KEY)
        _set_key(Fernet.generate_key().decode())

        row = self._full_vector_row(
            embedding_api_key_encrypted=encrypted,
        )
        resp = _to_response(row)
        assert resp.embedding_api_key_configured is False
        assert resp.embedding_api_key_masked == ""

        _set_key(TEST_FERNET_KEY)

    def test_secret_str_hides_in_repr(self):
        """Pydantic SecretStr must prevent API key from appearing in repr/str."""
        from app.schemas.admin_ai_config import AdminAiModelConfigCreateRequest

        req = AdminAiModelConfigCreateRequest(
            name="test", display_name="test", provider="deepseek",
            api_key=TEST_API_KEY,
        )
        dump = str(req.model_dump())
        assert TEST_API_KEY not in dump

    def test_api_key_encrypted_not_in_response(self):
        """Response must not contain api_key_encrypted field."""
        from app.schemas.admin_ai_config import AdminAiModelConfigResponse

        schema_fields = AdminAiModelConfigResponse.model_fields
        assert "api_key_encrypted" not in schema_fields

    def test_test_connection_response_no_key_leak(self):
        """Test connection request model must not leak key in repr."""
        from app.schemas.admin_ai_config import ModelTestConnectionRequest

        req = ModelTestConnectionRequest(
            api_base_url="https://test.com",
            api_key=TEST_API_KEY,
            model_name="test-model",
        )
        dump = str(req.model_dump())
        assert TEST_API_KEY not in dump

    def test_no_api_key_in_error_message(self):
        """SecretEncryptionError must not contain the key value."""
        _set_key("")
        from app.core.secret_crypto import SecretEncryptionError
        try:
            from app.core.secret_crypto import encrypt_secret
            encrypt_secret(TEST_API_KEY)
        except SecretEncryptionError as exc:
            msg = str(exc)
            assert TEST_API_KEY not in msg
