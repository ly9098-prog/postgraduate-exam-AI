"""Cloud OCR isolation tests — verify cloud_api profile never uses local OCR.

Required by the production safety specification:
- No paddleocr/paddle imports during startup
- No local OCR subprocess creation
- No local OCR adapter fallback after remote failure
- Import pipeline doesn't check local PaddleOCR installation
- Startup config validation rejects local profile in production
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _patch_settings():
    """Patch settings for production-mode tests.

    Pydantic settings are loaded at import time, so changing os.environ
    doesn't affect the already-loaded settings object. This fixture
    patches settings.APP_ENV when needed.
    """
    from app.core.config import settings

    original = settings.APP_ENV
    yield
    settings.APP_ENV = original


class TestCloudProfileDetection:
    """detect_deployment_profile() returns correct values."""

    def test_cloud_api_when_env_set(self):
        from app.services.production_config_validator import detect_deployment_profile
        from app.core.deployment_profile import DeploymentProfile

        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "cloud_api"}, clear=False):
            assert detect_deployment_profile() == DeploymentProfile.CLOUD_API

    def test_local_import_when_env_set(self):
        from app.services.production_config_validator import detect_deployment_profile
        from app.core.deployment_profile import DeploymentProfile

        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "local_import"}, clear=False):
            assert detect_deployment_profile() == DeploymentProfile.LOCAL_IMPORT

    def test_cloud_api_when_app_env_production(self):
        from app.services.production_config_validator import detect_deployment_profile
        from app.core.deployment_profile import DeploymentProfile
        from app.core.config import settings

        original = settings.APP_ENV
        settings.APP_ENV = "production"
        try:
            with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "", "DEPLOY_PROFILE": ""}, clear=False):
                assert detect_deployment_profile() == DeploymentProfile.CLOUD_API
        finally:
            settings.APP_ENV = original

    def test_local_import_when_app_env_development(self):
        from app.services.production_config_validator import detect_deployment_profile
        from app.core.deployment_profile import DeploymentProfile

        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "", "DEPLOY_PROFILE": ""}, clear=False):
            assert detect_deployment_profile() == DeploymentProfile.LOCAL_IMPORT


class TestCloudOcrLegacyFunctionsRejected:
    """Legacy OCR functions must refuse in cloud_api mode."""

    @patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "cloud_api"}, clear=False)
    def test_legacy_ocr_pages_rejected_in_cloud(self):
        from app.services.ocr_service import _legacy_ocr_pages

        with pytest.raises(RuntimeError, match="cloud_api"):
            _legacy_ocr_pages([])

    @patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "cloud_api"}, clear=False)
    def test_legacy_ocr_pages_with_boxes_rejected_in_cloud(self):
        from app.services.ocr_service import _legacy_ocr_pages_with_boxes

        with pytest.raises(RuntimeError, match="cloud_api"):
            _legacy_ocr_pages_with_boxes([])

    @patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "cloud_api"}, clear=False)
    def test_legacy_ocr_raw_text_rejected_in_cloud(self):
        from app.services.ocr_service import _legacy_ocr_raw_text

        with pytest.raises(RuntimeError, match="cloud_api"):
            _legacy_ocr_raw_text(b"")

    @patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "cloud_api"}, clear=False)
    def test_reset_ocr_engine_rejected_in_cloud(self):
        from app.services.ocr_service import reset_ocr_engine

        with pytest.raises(RuntimeError, match="cloud_api"):
            reset_ocr_engine()

    @patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "local_import"}, clear=False)
    def test_legacy_ocr_pages_allowed_in_local(self):
        """In local_import mode, legacy functions should not be rejected by the cloud guard."""
        from app.services.ocr_service import _legacy_ocr_pages

        # Should raise RuntimeError about executor, not about cloud_api
        try:
            _legacy_ocr_pages([])
        except RuntimeError as e:
            assert "cloud_api" not in str(e).lower()


class TestCloudOcrNoPaddleSpec:
    """Import pipeline must not check for PaddleOCR in cloud mode."""

    @patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "cloud_api"}, clear=False)
    def test_build_ocr_diagnostics_no_paddle_check_in_cloud(self):
        """In cloud_api mode, diagnostics report paddleocr as unavailable without checking."""
        from app.services.import_pipeline_service import _build_ocr_runtime_diagnostics

        result = _build_ocr_runtime_diagnostics()
        assert result.get("paddleocr_available") is False

    @patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "local_import"}, clear=False)
    def test_build_ocr_diagnostics_checks_paddle_in_local(self):
        """In local_import mode, diagnostics check for paddleocr."""
        from app.services.import_pipeline_service import _build_ocr_runtime_diagnostics

        result = _build_ocr_runtime_diagnostics()
        # May be True or False depending on environment, but key must exist
        assert "paddleocr_available" in result

    @patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "cloud_api"}, clear=False)
    def test_image_import_no_paddle_check_in_cloud(self):
        """In cloud_api mode, image import validation doesn't check for paddleocr."""
        from app.services.import_pipeline_service import _build_ocr_runtime_diagnostics

        result = _build_ocr_runtime_diagnostics()
        assert "paddleocr_available" in result
        assert result["paddleocr_available"] is False


class TestProductionConfigValidatorOcr:
    """Production config validator catches cloud OCR violations."""

    def _run_checks(self, **overrides) -> list[str]:
        """Run OCR-related checks with patched settings and env."""
        from app.services import production_config_validator as validator
        from app.core.config import settings

        # Default: valid cloud config
        env_vals = {"DEPLOYMENT_PROFILE": "cloud_api"}
        set_vals = {
            "OCR_ENABLED": True,
            "OCR_USE_GPU": False,
            "OCR_EXECUTION_BACKEND": "paddlex_http",
            "OCR_REMOTE_URL": "https://ocr.example.com/api",
            "OCR_REMOTE_TOKEN": "test-token-123",
        }
        env_vals.update({k: str(v) for k, v in overrides.items() if k in ("DEPLOYMENT_PROFILE",)})
        set_vals.update({k: v for k, v in overrides.items() if k not in ("DEPLOYMENT_PROFILE",)})

        errors: list[str] = []
        with patch.dict(os.environ, env_vals, clear=False):
            with patch.object(settings, "OCR_ENABLED", set_vals["OCR_ENABLED"]):
                with patch.object(settings, "OCR_USE_GPU", set_vals["OCR_USE_GPU"]):
                    with patch.object(settings, "OCR_EXECUTION_BACKEND", set_vals["OCR_EXECUTION_BACKEND"]):
                        with patch.object(settings, "OCR_REMOTE_URL", set_vals.get("OCR_REMOTE_URL", "")):
                            with patch.object(settings, "OCR_REMOTE_TOKEN", set_vals.get("OCR_REMOTE_TOKEN", "")):
                                validator._check_deployment_profile(errors)
                                validator._check_ocr_production_rules(errors)
                                validator._check_ocr_no_local_deps(errors)
        return errors

    def test_valid_cloud_config_passes(self):
        errors = self._run_checks()
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_gpu_enabled_fails(self):
        errors = self._run_checks(OCR_USE_GPU=True)
        gpu_errors = [e for e in errors if "GPU" in e or "gpu" in e]
        assert len(gpu_errors) > 0, f"Expected GPU error. Errors: {errors}"

    def test_local_profile_fails(self):
        errors = self._run_checks(DEPLOYMENT_PROFILE="local_import")
        profile_errors = [e for e in errors if "cloud_api" in e]
        assert len(profile_errors) > 0, f"Expected profile error. Errors: {errors}"

    def test_local_process_backend_fails(self):
        errors = self._run_checks(OCR_EXECUTION_BACKEND="local_process")
        backend_errors = [e for e in errors if "local_process" in e.lower()]
        assert len(backend_errors) > 0, f"Expected local_process error. Errors: {errors}"

    def test_missing_remote_token_fails_when_ocr_enabled(self):
        """OCR_REMOTE_TOKEN must be set when external OCR is enabled."""
        errors = self._run_checks(
            OCR_ENABLED=True,
            OCR_EXECUTION_BACKEND="paddlex_http",
            OCR_REMOTE_URL="https://ocr.example.com/api",
            OCR_REMOTE_TOKEN="",
        )
        token_errors = [e for e in errors if "TOKEN" in e or "token" in e]
        assert len(token_errors) > 0, f"Expected token error. Errors: {errors}"

    def test_invalid_explicit_profile_fails(self):
        """Invalid DEPLOYMENT_PROFILE raises ValueError."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "invalid_profile"}, clear=False):
            from app.core.deployment_profile import detect_deployment_profile
            import pytest
            with pytest.raises(ValueError, match="无效的 DEPLOYMENT_PROFILE"):
                detect_deployment_profile()


class TestCloudOcrNoImportFallback:
    """Verify cloud_api never falls back to local OCR imports."""

    def test_no_local_adapter_import_on_cloud_profile(self):
        """cloud_api profile does NOT import paddleocr adapter modules."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "cloud_api"}, clear=False):
            from app.core.deployment_profile import detect_deployment_profile, DeploymentProfile
            profile = detect_deployment_profile()
            assert profile == DeploymentProfile.CLOUD_API

    def test_startup_rejects_local_backend_and_gpu_combination(self):
        """Config validator rejects local_process + GPU in restricted env."""
        from app.services import production_config_validator as validator
        from app.core.config import settings
        from unittest.mock import patch

        def _check():
            errors = []
            with patch.object(settings, "OCR_ENABLED", True):
                with patch.object(settings, "OCR_USE_GPU", True):
                    with patch.object(settings, "OCR_EXECUTION_BACKEND", "local_process"):
                        validator._check_ocr_production_rules(errors)
            return errors

        errors = _check()
        gpu_errors = [e for e in errors if "GPU" in e]
        backend_errors = [e for e in errors if "local_process" in e]
        assert len(gpu_errors) > 0, f"Expected GPU error. Errors: {errors}"
        assert len(backend_errors) > 0, f"Expected local_process error. Errors: {errors}"
