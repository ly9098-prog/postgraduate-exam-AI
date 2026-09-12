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
            api_base_url="https://api.test.com",
            api_key=TEST_API_KEY,
        )
        with pytest.raises(SecretEncryptionError, match="not configured"):
            from unittest.mock import patch

            from app.services.admin_ai_config_service import create_model
            principal = type(
                "Principal", (), {"id": 1, "username": "admin", "roles": ["super_admin"]}
            )()
            with patch(
                "app.services.admin_ai_config_service._validated_api_base_url",
                return_value=req.api_base_url,
            ):
                await create_model(AsyncMock(), req, principal)
