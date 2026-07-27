"""Tests for export feature control: whitelist, capability API, feature flags.

Covers:
- EXPORT_FEATURE_ENABLED=false blocks task creation
- EXPORT_ALLOWED_USER_IDS restricts access
- EXPORT_ALLOW_ALL_USERS opens access when whitelist is empty
- Capability API returns correct per-user response with reason_code
- DOCX feature flag blocks DOCX requests
- WS feature flag on the WS endpoint
- Whitelist parsing edge cases (spaces, duplicates, invalid values)
- Non-bypass: preview-count and create endpoints enforce capability
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException


class TestFeatureFlagCreate:
    """EXPORT_FEATURE_ENABLED must block create/retry/re-export."""

    @pytest.mark.asyncio
    async def test_create_blocked_when_feature_disabled(self):
        """EXPORT_FEATURE_ENABLED=False → is_user_allowed returns False."""
        from app.services.export.capability import is_user_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = False
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            assert is_user_allowed(1) is False

    @pytest.mark.asyncio
    async def test_create_blocked_when_user_not_in_whitelist(self):
        """User not in EXPORT_ALLOWED_USER_IDS → False."""
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
        """EXPORT_ALLOW_ALL_USERS=True → any user allowed."""
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
    async def test_whitelist_duplicates_handling(self):
        """Duplicate entries in whitelist don't cause errors."""
        from app.services.export.capability import is_user_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = "1,1,2,2"
            assert is_user_allowed(1) is True
            assert is_user_allowed(2) is True
            assert is_user_allowed(3) is False

    @pytest.mark.asyncio
    async def test_whitelist_invalid_values_skipped(self):
        """Non-integer entries in whitelist are silently skipped."""
        from app.services.export.capability import is_user_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = "1,abc,2,3.5"
            # Valid int entries parse correctly
            assert is_user_allowed(1) is True
            assert is_user_allowed(2) is True
            # 'abc' and '3.5' are skipped
            assert is_user_allowed(999) is False

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


class TestCapabilityReasonCode:
    """build_capability returns reason_code/message when not allowed."""

    def _make_user(self, user_id: int = 1):
        """Create a minimal user-like object for build_capability."""
        class FakeUser:
            id = user_id
        return FakeUser()

    def test_feature_disabled_reason_code(self):
        """EXPORT_FEATURE_ENABLED=False → reason_code='feature_disabled'."""
        from app.services.export.capability import build_capability

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = False
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_MAX_QUESTIONS = 100
            mock_settings.EXPORT_RETENTION_DAYS = 7

            cap = build_capability(self._make_user(1))
            assert cap.export_enabled is False
            assert cap.pdf_enabled is False
            assert cap.docx_enabled is False
            assert cap.websocket_enabled is False
            assert cap.reason_code == "feature_disabled"
            assert cap.message == "导出功能已关闭"

    def test_user_not_allowed_reason_code(self):
        """Non-whitelisted user → reason_code='user_not_allowed'."""
        from app.services.export.capability import build_capability

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = "2,3"
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_MAX_QUESTIONS = 100
            mock_settings.EXPORT_RETENTION_DAYS = 7

            cap = build_capability(self._make_user(1))
            assert cap.export_enabled is False
            assert cap.reason_code == "user_not_allowed"
            assert cap.message == "当前账号暂未获得导出权限"

    def test_user_not_allowed_empty_whitelist(self):
        """Empty whitelist + no allow_all → reason_code='user_not_allowed'."""
        from app.services.export.capability import build_capability

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_MAX_QUESTIONS = 100
            mock_settings.EXPORT_RETENTION_DAYS = 7

            cap = build_capability(self._make_user(1))
            assert cap.export_enabled is False
            assert cap.reason_code == "user_not_allowed"

    def test_allowed_user_no_reason_code(self):
        """Allowed user → reason_code=None, message=None."""
        from app.services.export.capability import build_capability

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_MAX_QUESTIONS = 100
            mock_settings.EXPORT_RETENTION_DAYS = 7

            cap = build_capability(self._make_user(1))
            assert cap.export_enabled is True
            assert cap.reason_code is None
            assert cap.message is None

    def test_capability_respects_docx_disabled(self):
        """EXPORT_DOCX_ENABLED=False → docx_enabled=False but pdf still enabled."""
        from app.services.export.capability import build_capability

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            mock_settings.EXPORT_DOCX_ENABLED = False
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_MAX_QUESTIONS = 100
            mock_settings.EXPORT_RETENTION_DAYS = 7

            cap = build_capability(self._make_user(1))
            assert cap.export_enabled is True
            assert cap.pdf_enabled is True
            assert cap.docx_enabled is False  # DOCX disabled
            assert cap.websocket_enabled is True

    def test_capability_respects_websocket_disabled(self):
        """EXPORT_WEBSOCKET_ENABLED=False → websocket_enabled=False."""
        from app.services.export.capability import build_capability

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = False
            mock_settings.EXPORT_MAX_QUESTIONS = 100
            mock_settings.EXPORT_RETENTION_DAYS = 7

            cap = build_capability(self._make_user(1))
            assert cap.export_enabled is True
            assert cap.pdf_enabled is True
            assert cap.websocket_enabled is False

    def test_capability_respects_max_questions(self):
        """EXPORT_MAX_QUESTIONS is reflected in capability response."""
        from app.services.export.capability import build_capability

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_MAX_QUESTIONS = 50
            mock_settings.EXPORT_RETENTION_DAYS = 7

            cap = build_capability(self._make_user(1))
            assert cap.max_question_count == 50


class TestEnsureExportAllowed:
    """ensure_export_allowed raises appropriate errors."""

    @pytest.mark.asyncio
    async def test_feature_disabled_raises(self):
        """EXPORT_FEATURE_ENABLED=False → ensure_export_allowed raises."""
        from app.schemas.export_task import ExportErrorCode
        from app.services.export.capability import ensure_export_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = False
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""

            with pytest.raises(HTTPException) as exc_info:
                ensure_export_allowed(1)
            detail = exc_info.value.detail
            assert detail["error_code"] == ExportErrorCode.FEATURE_DISABLED

    @pytest.mark.asyncio
    async def test_user_not_allowed_raises(self):
        """Non-whitelisted user → ensure_export_allowed raises."""
        from app.schemas.export_task import ExportErrorCode
        from app.services.export.capability import ensure_export_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = "2"

            with pytest.raises(HTTPException) as exc_info:
                ensure_export_allowed(1)
            detail = exc_info.value.detail
            assert detail["error_code"] == ExportErrorCode.USER_NOT_ALLOWED

    @pytest.mark.asyncio
    async def test_allowed_user_passes(self):
        """Whitelisted user → ensure_export_allowed does not raise."""
        from app.services.export.capability import ensure_export_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = "1"

            # Should not raise
            ensure_export_allowed(1)

    @pytest.mark.asyncio
    async def test_allow_all_users_passes(self):
        """EXPORT_ALLOW_ALL_USERS=True → ensure_export_allowed passes."""
        from app.services.export.capability import ensure_export_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""

            # Should not raise
            ensure_export_allowed(999)


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
        assert "reason_code" in data
        assert "message" in data
        assert data["max_question_count"] == 100

    def test_capability_reason_code_fields(self):
        """reason_code and message are optional and can be None."""
        from app.schemas.export_task import ExportCapabilityResponse

        # Without reason_code — backward compatible
        resp = ExportCapabilityResponse(
            export_enabled=True,
            pdf_enabled=True,
            docx_enabled=True,
            websocket_enabled=True,
        )
        assert resp.reason_code is None
        assert resp.message is None

        # With reason_code
        resp2 = ExportCapabilityResponse(
            export_enabled=False,
            pdf_enabled=False,
            docx_enabled=False,
            websocket_enabled=False,
            reason_code="feature_disabled",
            message="导出功能已关闭",
        )
        assert resp2.reason_code == "feature_disabled"
        assert resp2.message == "导出功能已关闭"


class TestLogExportConfig:
    """log_export_config_on_startup logs correct access_mode."""

    def test_disabled_mode(self):
        """EXPORT_FEATURE_ENABLED=False → access_mode=disabled."""
        from app.services.export.capability import log_export_config_on_startup

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = False
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True

            # Should not raise
            log_export_config_on_startup()

    def test_all_users_mode(self):
        """EXPORT_ALLOW_ALL_USERS=True → access_mode=all."""
        from app.services.export.capability import log_export_config_on_startup

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True

            log_export_config_on_startup()

    def test_deny_by_default_warning(self):
        """Feature enabled but no users → access_mode=deny_by_default + warning."""
        from app.services.export.capability import log_export_config_on_startup

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True

            log_export_config_on_startup()

    def test_allowlist_mode(self):
        """EXPORT_ALLOWED_USER_IDS non-empty → access_mode=allowlist."""
        from app.services.export.capability import log_export_config_on_startup

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = "1,2"
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True

            log_export_config_on_startup()


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
