"""Sprint 4B — DeploymentProfile detection and validation tests."""

from __future__ import annotations

import pytest

from app.core.deployment_profile import (
    DeploymentProfile,
    detect_deployment_profile,
    validate_profile_flags,
)


class TestDeploymentProfileDetection:
    def test_local_import_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEPLOYMENT_PROFILE", "local_import")
        assert detect_deployment_profile() == DeploymentProfile.LOCAL_IMPORT

    def test_cloud_api_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEPLOYMENT_PROFILE", "cloud_api")
        assert detect_deployment_profile() == DeploymentProfile.CLOUD_API

    def test_detect_from_deploy_profile_local(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("DEPLOYMENT_PROFILE", raising=False)
        monkeypatch.setattr(
            "app.core.deployment_profile.settings.DEPLOY_PROFILE", "local",
        )
        assert detect_deployment_profile() == DeploymentProfile.LOCAL_IMPORT

    def test_detect_from_deploy_profile_production(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("DEPLOYMENT_PROFILE", raising=False)
        monkeypatch.setattr(
            "app.core.deployment_profile.settings.DEPLOY_PROFILE", "production",
        )
        assert detect_deployment_profile() == DeploymentProfile.CLOUD_API

    def test_default_is_local_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEPLOYMENT_PROFILE", raising=False)
        monkeypatch.setattr(
            "app.core.deployment_profile.settings.DEPLOY_PROFILE", "",
        )
        monkeypatch.setattr(
            "app.core.deployment_profile.settings.APP_ENV", "development",
        )
        assert detect_deployment_profile() == DeploymentProfile.LOCAL_IMPORT


class TestValidateProfileFlags:
    def test_validate_profile_flags_cloud_ok(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("OCR_USE_GPU", raising=False)
        monkeypatch.delenv("STRUCTURE_FREEZE_MODE", raising=False)
        monkeypatch.delenv("CONTROL_PLANE_MODE", raising=False)
        errors = validate_profile_flags(DeploymentProfile.CLOUD_API)
        assert errors == []

    def test_validate_profile_flags_local_ok(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        errors = validate_profile_flags(DeploymentProfile.LOCAL_IMPORT)
        assert errors == []


class TestProfileEnumValues:
    def test_profile_enum_values(self) -> None:
        assert DeploymentProfile.LOCAL_IMPORT.value == "local_import"
        assert DeploymentProfile.CLOUD_API.value == "cloud_api"

    def test_profile_is_str_enum(self) -> None:
        assert isinstance(DeploymentProfile.LOCAL_IMPORT, str)
        assert DeploymentProfile.LOCAL_IMPORT == "local_import"
