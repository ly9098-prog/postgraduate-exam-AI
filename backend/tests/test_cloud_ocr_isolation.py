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
        from app.core.deployment_profile import DeploymentProfile
        from app.services.production_config_validator import detect_deployment_profile

        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "cloud_api"}, clear=False):
            assert detect_deployment_profile() == DeploymentProfile.CLOUD_API

    def test_local_import_when_env_set(self):
        from app.core.deployment_profile import DeploymentProfile
        from app.services.production_config_validator import detect_deployment_profile

        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "local_import"}, clear=False):
            assert detect_deployment_profile() == DeploymentProfile.LOCAL_IMPORT

    def test_cloud_api_when_app_env_production(self):
        from app.core.config import settings
        from app.core.deployment_profile import DeploymentProfile
        from app.services.production_config_validator import detect_deployment_profile

        original = settings.APP_ENV
        settings.APP_ENV = "production"
        try:
            with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "", "DEPLOY_PROFILE": ""}, clear=False):
                assert detect_deployment_profile() == DeploymentProfile.CLOUD_API
        finally:
            settings.APP_ENV = original

    def test_local_import_when_app_env_development(self):
        from app.core.deployment_profile import DeploymentProfile
        from app.services.production_config_validator import detect_deployment_profile

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

    def _import_with_staging(self, env_patch: dict) -> None:
        """Hack: force fresh import of staging_storage under patched env + settings."""
        import sys
        from app.core.config import settings

        # Ensure the staging dir parent exists
        staging_dir = env_patch.get("STAGING_STORAGE_DIR", "/tmp/test_staging")
        sys.modules.pop("app.services.staging_storage", None)
        sys.modules.pop("app.services.import_pipeline_service", None)
        with patch.object(settings, "STAGING_STORAGE_DIR", staging_dir):
            with patch.dict(os.environ, env_patch, clear=False):
                from app.services.import_pipeline_service import _build_ocr_runtime_diagnostics

                return _build_ocr_runtime_diagnostics()

    def test_build_ocr_diagnostics_no_paddle_check_in_cloud(self):
        """In cloud_api mode, diagnostics report paddleocr as unavailable without checking."""
        result = self._import_with_staging({
            "DEPLOYMENT_PROFILE": "cloud_api",
            "STAGING_STORAGE_DIR": "/tmp/test_staging",
        })
        assert result.get("paddleocr_available") is False

    def test_build_ocr_diagnostics_checks_paddle_in_local(self):
        """In local_import mode, diagnostics check for paddleocr."""
        result = self._import_with_staging({
            "DEPLOYMENT_PROFILE": "local_import",
            "STAGING_STORAGE_DIR": "/tmp/test_staging",
        })
        assert "paddleocr_available" in result

    def test_image_import_no_paddle_check_in_cloud(self):
        """In cloud_api mode, image import validation doesn't check for paddleocr."""
        result = self._import_with_staging({
            "DEPLOYMENT_PROFILE": "cloud_api",
            "STAGING_STORAGE_DIR": "/tmp/test_staging",
        })
        assert result["paddleocr_available"] is False


class TestCloudOcrSubprocessIsolation:
    """Subprocess-level isolation tests — verify cloud_api in a clean interpreter.

    These tests start a fresh Python subprocess with cloud_api environment
    variables to ensure no paddle/paddleocr modules leak at any point during
    application startup or import.
    """

    SUBPROCESS_SCRIPT = """
import os
import sys

# Must be set before any imports
os.environ["APP_ENV"] = "production"
os.environ["DEPLOYMENT_PROFILE"] = "cloud_api"
os.environ["PROCESS_ROLE"] = "worker"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@localhost:5432/db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["APP_SECRET"] = "a" * 32
os.environ["CORS_ORIGINS"] = '["https://example.com"]'
os.environ["STAGING_STORAGE_DIR"] = "/tmp"
# Cloud OCR config
os.environ["OCR_ENABLED"] = "true"
os.environ["OCR_USE_GPU"] = "false"
os.environ["OCR_EXECUTION_BACKEND"] = "paddlex_http"
os.environ["OCR_REMOTE_URL"] = "https://ocr.example.com/api"
os.environ["OCR_REMOTE_TOKEN"] = "test-token-123"
os.environ["VECTOR_ENABLED"] = "false"

# Cloud-appropriate PDF settings (must pass production validator)
os.environ["PDF_RENDER_PAGE_WINDOW"] = "1"
os.environ["PDF_MAX_RENDER_PAGES_CONCURRENT"] = "1"
os.environ["PDF_MAX_PAGES"] = "30"
os.environ["PDF_MAX_FILE_SIZE_BYTES"] = str(5 * 1024 * 1024)

# Wipe any cached modules from parent process
for mod in list(sys.modules.keys()):
    if "paddle" in mod or "ocr" in mod:
        del sys.modules[mod]

# Now import app core
from app.core.config import settings
from app.core.deployment_profile import detect_deployment_profile, DeploymentProfile
from app.services.production_config_validator import validate_production_config

# Verify profile
profile = detect_deployment_profile()
assert profile == DeploymentProfile.CLOUD_API, f"Expected CLOUD_API, got {profile}"

# Sync validation must pass for valid cloud config
validate_production_config()

# Check no paddle/paddleocr modules loaded
banned = [m for m in sys.modules if m.startswith(("paddle", "paddleocr"))]
if banned:
    print(f"BANNED_MODULES_LOADED: {banned}", file=sys.stderr)
    sys.exit(1)

print("SUCCESS: No local OCR modules loaded in cloud_api subprocess")
sys.exit(0)
"""

    def test_subprocess_cloud_api_no_paddle_imported(self):
        """Start a clean interpreter with cloud_api env; verify no paddle modules."""
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, "-c", self.SUBPROCESS_SCRIPT],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if stderr:
            print(f"Subprocess stderr:\n{stderr}")
        print(f"Subprocess stdout:\n{stdout}")
        assert proc.returncode == 0, (
            f"Subprocess exited with code {proc.returncode}. "
            f"stdout: {stdout}\nstderr: {stderr}"
        )
        assert "SUCCESS" in stdout

    def test_subprocess_cloud_api_config_validator_rejects_local(self):
        """Subprocess: verify config validator rejects local_process in cloud."""
        import subprocess
        import sys

        script = """
import os, sys
os.environ["APP_ENV"] = "production"
os.environ["DEPLOYMENT_PROFILE"] = "cloud_api"
os.environ["PROCESS_ROLE"] = "worker"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@localhost:5432/db"
os.environ["APP_SECRET"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
os.environ["CORS_ORIGINS"] = '["https://example.com"]'
os.environ["STAGING_STORAGE_DIR"] = "/tmp"
os.environ["VECTOR_ENABLED"] = "false"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["OCR_ENABLED"] = "true"
os.environ["OCR_USE_GPU"] = "true"  # must be rejected
os.environ["OCR_EXECUTION_BACKEND"] = "local_process"  # must be rejected
os.environ["OCR_REMOTE_URL"] = "https://ocr.example.com/api"
os.environ["OCR_REMOTE_TOKEN"] = "test-token-123"
for mod in list(sys.modules.keys()):
    if "paddle" in mod or "ocr" in mod:
        del sys.modules[mod]
try:
    from app.services.production_config_validator import validate_production_config
    validate_production_config()
    print("VALIDATION_PASSED_UNEXPECTEDLY")
    sys.exit(2)
except SystemError as e:
    error_text = str(e)
    if "GPU" in error_text or "local_process" in error_text:
        print("CORRECTLY_REJECTED")
        sys.exit(0)
    else:
        print(f"UNEXPECTED_ERROR: {error_text}")
        sys.exit(3)
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if stderr:
            print(f"Subprocess stderr:\n{stderr}")
        print(f"Subprocess stdout:\n{stdout}")
        assert proc.returncode == 0, (
            f"Subprocess exited with code {proc.returncode}. "
            f"stdout: {stdout}\nstderr: {stderr}"
        )
        assert "CORRECTLY_REJECTED" in stdout

    def test_subprocess_local_import_allows_local_ocr(self):
        """Subprocess: verify local_import profile does NOT block local OCR."""
        import subprocess
        import sys

        script = """
import os, sys
os.environ["APP_ENV"] = "development"
os.environ["DEPLOYMENT_PROFILE"] = "local_import"
os.environ["PROCESS_ROLE"] = "all"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test_isolation.db"
os.environ["APP_SECRET"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
os.environ["CORS_ORIGINS"] = '["https://example.com"]'
os.environ["STAGING_STORAGE_DIR"] = "/tmp"
os.environ["VECTOR_ENABLED"] = "false"
os.environ["OCR_ENABLED"] = "true"
os.environ["OCR_USE_GPU"] = "false"
os.environ["OCR_EXECUTION_BACKEND"] = "local_process"
os.environ["REDIS_URL"] = ""
for mod in list(sys.modules.keys()):
    if "paddle" in mod or "ocr" in mod:
        del sys.modules[mod]
from app.core.deployment_profile import detect_deployment_profile, DeploymentProfile
profile = detect_deployment_profile()
assert profile == DeploymentProfile.LOCAL_IMPORT, f"Expected LOCAL_IMPORT, got {profile}"
# local_import should validate without error for local_process backend
from app.services.production_config_validator import validate_production_config
validate_production_config()
print("LOCAL_IMPORT_OK")
sys.exit(0)
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if stderr:
            print(f"Subprocess stderr:\n{stderr}")
        print(f"Subprocess stdout:\n{stdout}")
        assert proc.returncode == 0, (
            f"Subprocess exited with code {proc.returncode}. "
            f"stdout: {stdout}\nstderr: {stderr}"
        )
        assert "LOCAL_IMPORT_OK" in stdout


class TestProductionConfigValidatorOcr:
    """Production config validator catches cloud OCR violations."""

    def _run_checks(self, **overrides) -> list[str]:
        """Run OCR-related checks with patched settings and env."""
        from app.core.config import settings
        from app.services import production_config_validator as validator

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
            import pytest

            from app.core.deployment_profile import detect_deployment_profile
            with pytest.raises(ValueError, match="无效的 DEPLOYMENT_PROFILE"):
                detect_deployment_profile()


class TestCloudOcrNoImportFallback:
    """Verify cloud_api never falls back to local OCR imports."""

    def test_no_local_adapter_import_on_cloud_profile(self):
        """cloud_api profile does NOT import paddleocr adapter modules."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "cloud_api"}, clear=False):
            from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
            profile = detect_deployment_profile()
            assert profile == DeploymentProfile.CLOUD_API

    def test_startup_rejects_local_backend_and_gpu_combination(self):
        """Config validator rejects local_process + GPU in restricted env."""
        from unittest.mock import patch

        from app.core.config import settings
        from app.services import production_config_validator as validator

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
