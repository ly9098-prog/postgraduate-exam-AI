"""Tests for export capability — export is open to every authenticated user.

Covers:
- build_capability always returns export_enabled=True for any user
- pdf_enabled is always True; docx/websocket reflect settings flags
- max_question_count / retention_days are reflected
- reason_code/message stay None (no rollout gates remain)
- raise_export_error produces structured HTTPException details
- ensure_format_allowed blocks DOCX only when EXPORT_DOCX_ENABLED=False
- validate_export_range enforces no_questions / too_many_questions
- ExportErrorCode enum values are stable
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException


class TestBuildCapability:
    """build_capability is always-open and independent of the user."""

    def _build(self, user_id: int = 1):
        from app.services.export.capability import build_capability

        class FakeUser:
            id = user_id

        return build_capability(FakeUser())

    def test_export_always_enabled_for_any_user(self):
        """Any user id gets export_enabled=True (no whitelist gates)."""
        for uid in (1, 2, 999):
            cap = self._build(uid)
            assert cap.export_enabled is True
            assert cap.pdf_enabled is True

    def test_reason_code_none_when_open(self):
        """With no rollout gates, reason_code/message are always None."""
        cap = self._build(1)
        assert cap.reason_code is None
        assert cap.message is None

    def test_docx_reflects_setting(self):
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DOCX_ENABLED = False
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_MAX_QUESTIONS = 100
            mock_settings.EXPORT_RETENTION_DAYS = 7
            cap = self._build(1)
            assert cap.docx_enabled is False
            assert cap.websocket_enabled is True

    def test_websocket_reflects_setting(self):
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = False
            mock_settings.EXPORT_MAX_QUESTIONS = 100
            mock_settings.EXPORT_RETENTION_DAYS = 7
            cap = self._build(1)
            assert cap.websocket_enabled is False
            assert cap.pdf_enabled is True

    def test_max_questions_reflected(self):
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_MAX_QUESTIONS = 50
            mock_settings.EXPORT_RETENTION_DAYS = 7
            cap = self._build(1)
            assert cap.max_question_count == 50

    def test_retention_days_reflected(self):
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_MAX_QUESTIONS = 100
            mock_settings.EXPORT_RETENTION_DAYS = 3
            cap = self._build(1)
            assert cap.retention_days == 3


class TestRaiseExportError:
    """raise_export_error produces a structured HTTPException."""

    def test_structured_error(self):
        from app.schemas.export_task import ExportErrorCode
        from app.services.export.capability import raise_export_error

        with pytest.raises(HTTPException) as exc_info:
            raise_export_error(403, ExportErrorCode.ACCESS_DENIED, "导出功能未开放")
        assert exc_info.value.status_code == 403
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert detail["error_code"] == "access_denied"
        assert detail["message"] == "导出功能未开放"

    def test_docx_disabled_message(self):
        from app.schemas.export_task import ExportErrorCode
        from app.services.export.capability import raise_export_error

        with pytest.raises(HTTPException) as exc_info:
            raise_export_error(403, ExportErrorCode.DOCX_DISABLED, "Word 导出功能已关闭")
        assert exc_info.value.status_code == 403
        assert "Word" in str(exc_info.value.detail["message"])


class TestEnsureFormatAllowed:
    """ensure_format_allowed only gates DOCX when disabled."""

    def test_pdf_never_raises(self):
        from app.services.export.capability import ensure_format_allowed
        ensure_format_allowed("pdf")

    def test_docx_blocked_when_disabled(self):
        from app.services.export.capability import ensure_format_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DOCX_ENABLED = False
            with pytest.raises(HTTPException) as exc_info:
                ensure_format_allowed("docx")
            assert exc_info.value.status_code == 403
            assert exc_info.value.detail["error_code"] == "docx_disabled"

    def test_docx_allowed_when_enabled(self):
        from app.services.export.capability import ensure_format_allowed

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DOCX_ENABLED = True
            ensure_format_allowed("docx")


class TestValidateExportRange:
    """validate_export_range enforces question-count limits."""

    def test_zero_raises(self):
        from app.services.export.capability import validate_export_range

        with pytest.raises(HTTPException) as exc:
            validate_export_range("all", None, 0)
        assert exc.value.status_code == 400
        assert exc.value.detail["error_code"] == "no_questions"

    def test_exceeds_max_raises(self):
        from app.services.export.capability import validate_export_range

        with pytest.raises(HTTPException) as exc:
            validate_export_range("all", None, 999)
        assert exc.value.status_code == 400
        assert exc.value.detail["error_code"] == "too_many_questions"

    def test_within_limit_passes(self):
        from app.services.export.capability import validate_export_range
        validate_export_range("all", None, 5)


class TestLogExportConfig:
    """log_export_config_on_startup logs an always-open config."""

    def test_logs_all_users_mode(self):
        from app.services.export.capability import log_export_config_on_startup

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            log_export_config_on_startup()

    def test_logs_docx_disabled(self):
        from app.services.export.capability import log_export_config_on_startup

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DOCX_ENABLED = False
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            log_export_config_on_startup()


class TestCapabilityResponseModel:
    """ExportCapabilityResponse schema shape is stable."""

    def test_response_shape(self):
        from app.schemas.export_task import ExportCapabilityResponse

        resp = ExportCapabilityResponse(
            export_enabled=True,
            pdf_enabled=True,
            docx_enabled=True,
            websocket_enabled=True,
        )
        data = resp.model_dump()
        for field in ("export_enabled", "pdf_enabled", "docx_enabled",
                      "websocket_enabled", "max_question_count",
                      "retention_days", "reason_code", "message"):
            assert field in data
        assert data["max_question_count"] == 100
        assert data["retention_days"] == 7

    def test_reason_code_optional(self):
        from app.schemas.export_task import ExportCapabilityResponse

        resp = ExportCapabilityResponse(
            export_enabled=True,
            pdf_enabled=True,
            docx_enabled=True,
            websocket_enabled=True,
        )
        assert resp.reason_code is None
        assert resp.message is None

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


class TestErrorCodeEnum:
    """ExportErrorCode enum values are stable."""

    def test_enum_values(self):
        from app.schemas.export_task import ExportErrorCode
        assert ExportErrorCode.DOCX_DISABLED == "docx_disabled"
        assert ExportErrorCode.TOO_MANY_CONCURRENT == "too_many_concurrent"
        assert ExportErrorCode.TASK_NOT_FOUND == "task_not_found"
        assert ExportErrorCode.FILE_NOT_READY == "file_not_ready"
        assert ExportErrorCode.FILE_EXPIRED == "file_expired"
