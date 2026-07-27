"""Tests for admin_ai_config_service encryption safety."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.core.secret_crypto import ENCRYPTED_PREFIX, encrypt_secret

TEST_FERNET_KEY = Fernet.generate_key().decode()
TEST_API_KEY = "sk-test-do-not-use-123456"


def _set_key(key: str | None):
    os.environ["AI_CONFIG_ENCRYPT_KEY"] = key or ""
    from app.core.config import settings
    settings.AI_CONFIG_ENCRYPT_KEY = key or ""


class TestAdminAiConfigEncryption:
    """Service-level tests for AI model config encryption."""

    def setup_method(self):
        _set_key(TEST_FERNET_KEY)

    def _make_model(self, api_key_encrypted=None):
        from app.models.admin_ai_config import AdminAiModelConfig
        return AdminAiModelConfig(
            id=1, name="deepseek-v4-flash", display_name="test",
            provider="deepseek", is_enabled=True, is_default=False,
            sort_order=0, api_key_encrypted=api_key_encrypted,
        )

    @pytest.mark.asyncio
    async def test_env_key_sync_preserves_on_decrypt_failure(self):
        """_ensure_env_key_synced must NOT overwrite DB value on decrypt failure."""
        model = self._make_model(encrypt_secret(TEST_API_KEY))

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = model
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        # Set env key to a DIFFERENT value, and encrypt key to something else
        _set_key(Fernet.generate_key().decode())
        from app.core.config import settings
        original_deepseek = settings.DEEPSEEK_API_KEY
        settings.DEEPSEEK_API_KEY = "different-env-key"

        original_encrypted = model.api_key_encrypted

        from app.services.admin_ai_config_service import _ensure_env_key_synced
        await _ensure_env_key_synced(mock_db)

        # DB value must be unchanged — flush should not have been called
        assert model.api_key_encrypted == original_encrypted

        # Restore
        _set_key(TEST_FERNET_KEY)
        settings.DEEPSEEK_API_KEY = original_deepseek

    @pytest.mark.asyncio
    async def test_env_key_sync_empty_db_stores(self):
        model = self._make_model(api_key_encrypted=None)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = model
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        from app.core.config import settings
        original_deepseek = settings.DEEPSEEK_API_KEY
        settings.DEEPSEEK_API_KEY = "new-env-key"

        from app.services.admin_ai_config_service import _ensure_env_key_synced
        await _ensure_env_key_synced(mock_db)

        key = model.api_key_encrypted
        assert key is not None
        assert key.startswith(ENCRYPTED_PREFIX)

        settings.DEEPSEEK_API_KEY = original_deepseek

    def test_model_to_response_fixed_mask(self):
        model = self._make_model(encrypt_secret(TEST_API_KEY))
        from app.services.admin_ai_config_service import _model_to_response
        resp = _model_to_response(model)

        assert resp.api_configured is True
        assert resp.api_key_masked == "********"
        assert TEST_API_KEY not in str(resp.model_dump())

    def test_model_to_response_no_key(self):
        model = self._make_model(api_key_encrypted=None)
        from app.services.admin_ai_config_service import _model_to_response
        resp = _model_to_response(model)

        assert resp.api_configured is False
        assert resp.api_key_masked is None

    def test_mask_placeholder_not_encrypted(self):
        from app.schemas.admin_ai_config import AdminAiModelConfigPatchRequest

        req = AdminAiModelConfigPatchRequest(api_key="****")
        assert req.get_api_key_value() is None

        req2 = AdminAiModelConfigPatchRequest(api_key="********")
        assert req2.get_api_key_value() is None

    @pytest.mark.asyncio
    async def test_encrypt_failure_in_create_raises(self):
        _set_key("")
        from app.core.secret_crypto import SecretEncryptionError
        from app.schemas.admin_ai_config import AdminAiModelConfigCreateRequest

        req = AdminAiModelConfigCreateRequest(
            name="test", display_name="test", provider="deepseek",
            api_key=TEST_API_KEY,
        )
        with pytest.raises(SecretEncryptionError, match="not configured"):
            from app.services.admin_ai_config_service import create_model
            principal = type(
                "Principal", (), {"id": 1, "username": "admin", "roles": ["super_admin"]}
            )()
            await create_model(AsyncMock(), req, principal)
