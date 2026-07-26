"""Unit tests for OCRCoordinator profile handling."""
from __future__ import annotations

from app.core.deployment_profile import DeploymentProfile


class TestOCRCoordinator:
    """OCRCoordinator must accept and pass DeploymentProfile to OCRGateway."""

    def test_init_with_profile(self) -> None:
        """OCRCoordinator can be initialized with a profile."""
        from app.features.coordinators import OCRCoordinator

        coordinator = OCRCoordinator(profile=DeploymentProfile.CLOUD_API)
        assert coordinator._profile == DeploymentProfile.CLOUD_API

    def test_init_without_profile(self) -> None:
        """OCRCoordinator can be initialized without profile (resolves at runtime)."""
        from app.features.coordinators import OCRCoordinator

        coordinator = OCRCoordinator()
        assert coordinator._profile is None

    def test_init_with_local_profile(self) -> None:
        """OCRCoordinator with LOCAL_IMPORT profile."""
        from app.features.coordinators import OCRCoordinator

        coordinator = OCRCoordinator(profile=DeploymentProfile.LOCAL_IMPORT)
        assert coordinator._profile == DeploymentProfile.LOCAL_IMPORT
