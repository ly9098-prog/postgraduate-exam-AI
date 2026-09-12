"""Tests for deployment profile flag validation."""


from app.core.deployment_profile import DeploymentProfile, validate_profile_flags


class TestInvalidProfileFlagCombinations:
    """validate_profile_flags tests."""

    def test_validate_local_ok(self):
        """LOCAL_IMPORT has no illegal flag combinations by default."""
        errors = validate_profile_flags(DeploymentProfile.LOCAL_IMPORT)
        assert errors == []

    def test_validate_cloud_api_no_conflict(self, monkeypatch):
        """CLOUD_API passes when no conflicting env vars are set."""
        # Remove potential conflicting env vars
        monkeypatch.delenv("OCR_USE_GPU", raising=False)
        monkeypatch.delenv("STRUCTURE_FREEZE_MODE", raising=False)
        monkeypatch.delenv("CONTROL_PLANE_MODE", raising=False)
        errors = validate_profile_flags(DeploymentProfile.CLOUD_API)
        assert errors == []

    def test_validate_cloud_api_gpu_conflict(self, monkeypatch):
        """CLOUD_API + OCR_USE_GPU=true is an illegal combination."""
        monkeypatch.setenv("OCR_USE_GPU", "true")
        errors = validate_profile_flags(DeploymentProfile.CLOUD_API)
        assert any("GPU" in e for e in errors)
