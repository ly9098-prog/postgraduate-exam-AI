"""Cloud OCR profile boundaries with real guards and isolated backend ports."""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
from app.core.ocr_types import WorkerResult
from app.services import import_pipeline_service as pipeline
from app.services import ocr_service, ocr_worker_client, production_config_validator
from tests.cloud_isolation.cloud_subprocess_scripts import (
    HTTP_IMPORT_PROBE,
    INVALID_LOCAL_BACKEND_PROBE,
    LOCAL_IMPORT_PROBE,
    VALID_CLOUD_PROBE,
)
from tests.cloud_isolation.cloud_test_ports import cloud_settings as cloud_settings
from tests.cloud_isolation.cloud_test_ports import forbid_local_ocr as forbid_local_ocr
from tests.cloud_isolation.cloud_test_ports import (
    install_paddle_probe,
    run_script,
)
from tests.cloud_isolation.cloud_test_ports import (
    isolated_cloud_settings as isolated_cloud_settings,
)
from tests.cloud_isolation.cloud_test_ports import (
    production_app_env as production_app_env,
)


class TestCloudProfileDetection:
    def test_cloud_api_when_env_set(self, production_app_env):
        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "cloud_api"}):
            assert detect_deployment_profile() == DeploymentProfile.CLOUD_API

    def test_local_import_when_env_set(self):
        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "local_import"}):
            assert detect_deployment_profile() == DeploymentProfile.LOCAL_IMPORT

    def test_cloud_api_when_app_env_production(self, production_app_env):
        assert detect_deployment_profile() == DeploymentProfile.CLOUD_API

    def test_local_import_when_app_env_development(self, monkeypatch):
        monkeypatch.setattr(settings, "APP_ENV", "development")
        assert detect_deployment_profile() == DeploymentProfile.LOCAL_IMPORT

    @pytest.mark.parametrize("app_env,profile", [
        ("test", "cloud_api"), ("development", "cloud_api"), ("production", "local_import"),
    ])
    def test_mixed_security_environment_is_rejected(self, monkeypatch, app_env, profile):
        monkeypatch.setattr(settings, "APP_ENV", app_env)
        monkeypatch.setenv("DEPLOYMENT_PROFILE", profile)
        with pytest.raises(ValueError, match="部署档案冲突"):
            detect_deployment_profile()


class TestCloudOcrLegacyFunctionsRejected:
    def test_legacy_ocr_pages_rejected_in_cloud(self, cloud_settings, forbid_local_ocr):
        with pytest.raises(RuntimeError, match="cloud_api"):
            ocr_service._legacy_ocr_pages([(1, b"synthetic-image")])

    def test_legacy_ocr_pages_with_boxes_rejected_in_cloud(self, cloud_settings, forbid_local_ocr):
        with pytest.raises(RuntimeError, match="cloud_api"):
            ocr_service._legacy_ocr_pages_with_boxes([(1, b"synthetic-image")])

    def test_legacy_ocr_raw_text_rejected_in_cloud(self, cloud_settings, forbid_local_ocr):
        with pytest.raises(RuntimeError, match="cloud_api"):
            ocr_service._legacy_ocr_raw_text(b"synthetic-image")

    def test_reset_ocr_engine_rejected_in_cloud(self, cloud_settings, forbid_local_ocr):
        with pytest.raises(RuntimeError, match="cloud_api"):
            ocr_service.reset_ocr_engine()

    def test_legacy_ocr_pages_allowed_in_local(self, monkeypatch):
        recognize = AsyncMock(return_value={1: "synthetic OCR text"})
        monkeypatch.setitem(sys.modules, "app.services.ocr_executor_service", SimpleNamespace(
            ocr_executor=SimpleNamespace(run_ocr_pages=recognize),
        ))
        pages = [(1, b"synthetic-image")]
        assert ocr_service._legacy_ocr_pages(pages) == {1: "synthetic OCR text"}
        recognize.assert_awaited_once_with(pages)


class TestCloudOcrNoPaddleSpec:
    def test_build_ocr_diagnostics_no_paddle_check_in_cloud(self, cloud_settings, monkeypatch):
        probes = install_paddle_probe(monkeypatch, forbidden=True)
        result = pipeline._build_ocr_runtime_diagnostics()
        assert result["paddleocr_available"] is False
        assert result["execution_backend"] == "paddlex_http"
        assert result["use_gpu"] is False
        assert probes == []

    def test_build_ocr_diagnostics_checks_paddle_in_local(self, monkeypatch):
        probes = install_paddle_probe(monkeypatch, available=True)
        result = pipeline._build_ocr_runtime_diagnostics()
        assert result["paddleocr_available"] is True
        assert probes == ["paddleocr"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("outcome", ["success", "failed", "error", "cancel"])
    async def test_image_import_no_paddle_check_in_cloud(
        self, cloud_settings, forbid_local_ocr, monkeypatch, outcome,
    ):
        probes = install_paddle_probe(monkeypatch, forbidden=True)
        result = {"text": "synthetic remote OCR text", "lines": []}
        worker_result = WorkerResult(status="success", result=result)
        client = SimpleNamespace(recognize_batch=AsyncMock(return_value=[worker_result]), shutdown=AsyncMock())
        if outcome == "failed":
            worker_result.status = "failed"
            worker_result.stable_error_code = "ocr.synthetic_failure"
        error = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("synthetic remote error")
        if outcome in {"error", "cancel"}:
            client.recognize_batch.side_effect = error
        create = Mock(return_value=client)
        monkeypatch.setattr(ocr_service, "get_gateway", lambda: None)
        monkeypatch.setattr(ocr_worker_client, "create_ocr_worker_client", create)
        if outcome == "success":
            assert await pipeline._run_ocr_via_configured_backend(b"synthetic-image") is result
        elif outcome == "failed":
            with pytest.raises(RuntimeError, match="ocr.synthetic_failure"):
                await pipeline._run_ocr_via_configured_backend(b"synthetic-image")
        else:
            with pytest.raises(type(error)) as caught:
                await pipeline._run_ocr_via_configured_backend(b"synthetic-image")
            assert caught.value is error
        client.recognize_batch.assert_awaited_once_with([(1, b"synthetic-image")])
        client.shutdown.assert_awaited_once()
        create.assert_called_once()
        config = create.call_args.args[0]
        assert config.profile == "cloud_api" and config.execution_backend == "paddlex_http"
        assert probes == []


class TestCloudOcrSubprocessIsolation:
    def test_subprocess_cloud_api_no_paddle_imported(self, tmp_path):
        assert "SUCCESS: No local OCR modules" in run_script(VALID_CLOUD_PROBE, tmp_path)

    def test_subprocess_http_assembly_does_not_import_paddle(self, tmp_path):
        output = run_script(HTTP_IMPORT_PROBE, tmp_path)
        assert "HTTP_IMPORT_OK" in output
        assert "SUCCESS: No local OCR modules" in output

    def test_subprocess_cloud_api_config_validator_rejects_local(self, tmp_path):
        assert "CORRECTLY_REJECTED" in run_script(INVALID_LOCAL_BACKEND_PROBE, tmp_path)

    def test_subprocess_local_import_allows_local_ocr(self, tmp_path):
        assert "LOCAL_IMPORT_OK" in run_script(LOCAL_IMPORT_PROBE, tmp_path)


class TestProductionConfigValidatorOcr:
    def _run_checks(self, **overrides) -> list[str]:
        fields = {
            "APP_ENV": "production", "OCR_ENABLED": True, "OCR_USE_GPU": False,
            "OCR_EXECUTION_BACKEND": "paddlex_http", "OCR_REMOTE_URL": "https://ocr.example.com/api",
            "OCR_REMOTE_TOKEN": "synthetic-ocr-token",
        }
        fields.update({key: value for key, value in overrides.items() if key != "DEPLOYMENT_PROFILE"})
        profile = overrides.get("DEPLOYMENT_PROFILE", "cloud_api")
        errors = []
        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": profile}):
            with patch.multiple(settings, **fields):
                production_config_validator._check_deployment_profile(errors)
                production_config_validator._check_ocr_production_rules(errors)
                production_config_validator._check_ocr_no_local_deps(errors)
        return errors

    def test_valid_cloud_config_passes(self):
        assert self._run_checks() == []

    def test_gpu_enabled_fails(self):
        assert any("OCR_USE_GPU=false" in error for error in self._run_checks(OCR_USE_GPU=True))

    def test_local_profile_fails(self):
        with pytest.raises(ValueError, match="APP_ENV='production'.*cloud_api"):
            self._run_checks(DEPLOYMENT_PROFILE="local_import")

    def test_local_process_backend_fails(self):
        assert any("local_process" in error for error in self._run_checks(OCR_EXECUTION_BACKEND="local_process"))

    def test_missing_remote_token_fails_when_ocr_enabled(self):
        assert "OCR_EXECUTION_BACKEND=paddlex_http 时必须设置 OCR_REMOTE_TOKEN" in self._run_checks(OCR_REMOTE_TOKEN="")

    def test_invalid_explicit_profile_fails(self):
        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "invalid_profile"}):
            with pytest.raises(ValueError, match="无效的 DEPLOYMENT_PROFILE"):
                detect_deployment_profile()


class TestCloudOcrNoImportFallback:
    def test_no_local_adapter_import_on_cloud_profile(self, cloud_settings, forbid_local_ocr):
        from app.features.ocr_gateway import OCRGateway

        gateway = OCRGateway(profile=detect_deployment_profile(), mode="shadow")
        assert gateway._registry.get_ocr("paddleocr") is None
        assert gateway._get_forbidden_fallback() == ["paddleocr", "rule_fallback"]
        assert gateway._enforce_fallback_policy(["paddleocr", "paddleocr-vl", "rule_fallback"]) == ["paddleocr-vl"]

    def test_startup_rejects_local_backend_and_gpu_combination(self):
        errors = TestProductionConfigValidatorOcr()._run_checks(OCR_USE_GPU=True, OCR_EXECUTION_BACKEND="local_process")
        assert any("OCR_USE_GPU=false" in error for error in errors)
        assert any("local_process" in error for error in errors)
