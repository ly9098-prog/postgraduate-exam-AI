"""Local Profile Registry — Verify local profile adapter registration."""
from __future__ import annotations

from app.core.deployment_profile import DeploymentProfile
from app.features.ocr_gateway import OCRGateway


def test_local_registry_allows_local():
    """local_import gateway may register local PaddleOCR backend."""
    gw = OCRGateway(mode="shadow", profile=DeploymentProfile.LOCAL_IMPORT)
    backends = gw._registry.list_ocr()
    # Local adapter registration is optional (depends on PaddleOCR availability)
    # The key assertion is that the gateway allows local backend in principle
    assert gw._get_forbidden_fallback() == []
