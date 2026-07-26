"""Unit tests for deployment profile detection."""
from __future__ import annotations

import pytest

from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile


class TestDetectDeploymentProfile:
    """detect_deployment_profile() with various env configurations."""

    def test_default_local_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default (no env vars) returns LOCAL_IMPORT."""
        monkeypatch.delenv("DEPLOYMENT_PROFILE", raising=False)
        profile = detect_deployment_profile()
        assert profile == DeploymentProfile.LOCAL_IMPORT

    def test_explicit_cloud_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DEPLOYMENT_PROFILE=cloud_api returns CLOUD_API."""
        monkeypatch.setenv("DEPLOYMENT_PROFILE", "cloud_api")
        profile = detect_deployment_profile()
        assert profile == DeploymentProfile.CLOUD_API

    def test_explicit_local_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DEPLOYMENT_PROFILE=local_import returns LOCAL_IMPORT."""
        monkeypatch.setenv("DEPLOYMENT_PROFILE", "local_import")
        profile = detect_deployment_profile()
        assert profile == DeploymentProfile.LOCAL_IMPORT

    def test_invalid_explicit_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid DEPLOYMENT_PROFILE value raises ValueError."""
        monkeypatch.setenv("DEPLOYMENT_PROFILE", "invalid_profile")
        with pytest.raises(ValueError, match="无效的 DEPLOYMENT_PROFILE"):
            detect_deployment_profile()

    def test_conflict_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DEPLOYMENT_PROFILE and DEPLOY_PROFILE disagree → ValueError."""
        monkeypatch.setenv("DEPLOYMENT_PROFILE", "cloud_api")
        monkeypatch.setattr("app.core.config.settings.DEPLOY_PROFILE", "local")
        with pytest.raises(ValueError, match="部署档案冲突"):
            detect_deployment_profile()

    def test_consistent_config_no_conflict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DEPLOYMENT_PROFILE and DEPLOY_PROFILE agree → OK."""
        monkeypatch.setenv("DEPLOYMENT_PROFILE", "cloud_api")
        monkeypatch.setattr("app.core.config.settings.DEPLOY_PROFILE", "production")
        profile = detect_deployment_profile()
        assert profile == DeploymentProfile.CLOUD_API

    def test_depends_on_deploy_profile_local(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DEPLOY_PROFILE=local → LOCAL_IMPORT."""
        monkeypatch.delenv("DEPLOYMENT_PROFILE", raising=False)
        monkeypatch.setattr("app.core.config.settings.DEPLOY_PROFILE", "local")
        profile = detect_deployment_profile()
        assert profile == DeploymentProfile.LOCAL_IMPORT

    def test_depends_on_deploy_profile_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DEPLOY_PROFILE=production → CLOUD_API."""
        monkeypatch.delenv("DEPLOYMENT_PROFILE", raising=False)
        monkeypatch.setattr("app.core.config.settings.DEPLOY_PROFILE", "production")
        profile = detect_deployment_profile()
        assert profile == DeploymentProfile.CLOUD_API

    def test_app_env_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """APP_ENV=production with no explicit profile → CLOUD_API."""
        monkeypatch.delenv("DEPLOYMENT_PROFILE", raising=False)
        monkeypatch.setattr("app.core.config.settings.DEPLOY_PROFILE", "")
        monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
        profile = detect_deployment_profile()
        assert profile == DeploymentProfile.CLOUD_API


class TestValidateProfileFlags:
    """validate_profile_flags() checks illegal combinations."""

    def test_cloud_api_gpu_prohibited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """cloud_api + OCR_USE_GPU=true → error."""
        from app.core.deployment_profile import validate_profile_flags

        monkeypatch.setenv("OCR_USE_GPU", "true")
        errors = validate_profile_flags(DeploymentProfile.CLOUD_API)
        assert len(errors) >= 1
        assert any("GPU" in e for e in errors)

    def test_local_import_no_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """local_import profile → no errors from illegal combinations."""
        from app.core.deployment_profile import validate_profile_flags

        monkeypatch.setenv("OCR_USE_GPU", "true")
        errors = validate_profile_flags(DeploymentProfile.LOCAL_IMPORT)
        assert len(errors) == 0
