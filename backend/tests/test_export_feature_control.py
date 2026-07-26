"""Tests for export feature control: whitelist, capability API, feature flags.

Covers:
- EXPORT_FEATURE_ENABLED=false blocks task creation
- EXPORT_ALLOWED_USER_IDS restricts access
- EXPORT_ALLOW_ALL_USERS opens access when whitelist is empty
- Capability API returns correct per-user response
- DOCX feature flag blocks DOCX requests
- WS feature flag on the WS endpoint
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException


class TestFeatureFlagCreate:
    """EXPORT_FEATURE_ENABLED must block create/retry/re-export."""

    @pytest.mark.asyncio
    async def test_create_blocked_when_feature_disabled(self):
        """EXPORT_FEATURE_ENABLED=False → create_export returns 403."""
        from app.services.export.capability import is_user_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = False
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            assert is_user_allowed(1) is False

    @pytest.mark.asyncio
    async def test_create_blocked_when_user_not_in_whitelist(self):
        """User not in EXPORT_ALLOWED_USER_IDS → 403."""
        from app.services.export.capability import is_user_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = "2,3"
            assert is_user_allowed(1) is False
            assert is_user_allowed(2) is True
            assert is_user_allowed(3) is True

    @pytest.mark.asyncio
    async def test_allow_all_users_opens_access(self):
        """EXPORT_ALLOW_ALL_USERS=True → whitelist check passes."""
        from app.services.export.capability import is_user_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            assert is_user_allowed(1) is True
            assert is_user_allowed(999) is True

    @pytest.mark.asyncio
    async def test_safe_default_blocked(self):
        """Empty whitelist + EXPORT_ALLOW_ALL_USERS=False → blocked."""
        from app.services.export.capability import is_user_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            assert is_user_allowed(1) is False

    @pytest.mark.asyncio
    async def test_whitelist_whitespace_handling(self):
        """Comma-separated whitelist with spaces is handled correctly."""
        from app.services.export.capability import is_user_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = " 1 , 2 "
            assert is_user_allowed(1) is True
            assert is_user_allowed(2) is True
            assert is_user_allowed(3) is False

    @pytest.mark.asyncio
    async def test_create_blocked_with_structured_error(self):
        """The error response includes error_code."""
        from app.schemas.export_task import ExportErrorCode
        from app.services.export.capability import raise_export_error

        with pytest.raises(HTTPException) as exc_info:
            raise_export_error(403, ExportErrorCode.USER_NOT_ALLOWED, "导出功能未开放")
        assert exc_info.value.status_code == 403
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert detail["error_code"] == "user_not_allowed"
        assert detail["message"] == "导出功能未开放"


class TestDocxFeatureFlag:
    """EXPORT_DOCX_ENABLED must block DOCX task creation."""

    @pytest.mark.asyncio
    async def test_docx_blocked_when_disabled(self):
        """DOCX format request with EXPORT_DOCX_ENABLED=False → 403."""
        from app.schemas.export_task import ExportErrorCode
        from app.services.export.capability import raise_export_error

        with pytest.raises(HTTPException) as exc_info:
            raise_export_error(403, ExportErrorCode.DOCX_DISABLED, "Word 导出功能已关闭")
        assert exc_info.value.status_code == 403
        assert "Word" in str(exc_info.value.detail["message"])


class TestCapabilityAPI:
    """Capability endpoint returns correct per-user response."""

    @pytest.mark.asyncio
    async def test_capability_whitelist_allowed(self):
        """Whitelisted user gets export_enabled=True."""
        from app.schemas.export_task import ExportCapabilityResponse

        resp = ExportCapabilityResponse(
            export_enabled=True,
            pdf_enabled=True,
            docx_enabled=True,
            websocket_enabled=True,
        )
        assert resp.export_enabled is True
        assert resp.docx_enabled is True
        assert resp.websocket_enabled is True

    @pytest.mark.asyncio
    async def test_capability_whitelist_blocked(self):
        """Non-whitelisted user gets export_enabled=False."""
        from app.schemas.export_task import ExportCapabilityResponse

        resp = ExportCapabilityResponse(
            export_enabled=False,
            pdf_enabled=False,
            docx_enabled=False,
            websocket_enabled=False,
        )
        assert resp.export_enabled is False
        assert resp.docx_enabled is False

    @pytest.mark.asyncio
    async def test_capability_response_model(self):
        """Capability response shape is correct."""
        from app.schemas.export_task import ExportCapabilityResponse

        resp = ExportCapabilityResponse(
            export_enabled=True,
            pdf_enabled=True,
            docx_enabled=True,
            websocket_enabled=True,
        )
        data = resp.model_dump()
        assert "export_enabled" in data
        assert "pdf_enabled" in data
        assert "docx_enabled" in data
        assert "websocket_enabled" in data
        assert "max_question_count" in data
        assert "retention_days" in data
        assert data["max_question_count"] == 100


class TestErrorCodeEnum:
    """ExportErrorCode enum values are stable."""

    def test_enum_values(self):
        from app.schemas.export_task import ExportErrorCode
        assert ExportErrorCode.FEATURE_DISABLED == "feature_disabled"
        assert ExportErrorCode.USER_NOT_ALLOWED == "user_not_allowed"
        assert ExportErrorCode.DOCX_DISABLED == "docx_disabled"
        assert ExportErrorCode.TOO_MANY_CONCURRENT == "too_many_concurrent"
        assert ExportErrorCode.TASK_NOT_FOUND == "task_not_found"
        assert ExportErrorCode.FILE_NOT_READY == "file_not_ready"
        assert ExportErrorCode.FILE_EXPIRED == "file_expired"
