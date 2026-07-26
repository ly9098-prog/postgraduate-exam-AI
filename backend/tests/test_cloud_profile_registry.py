"""Cloud Profile Registry — Verify cloud profile adapter registration."""
from __future__ import annotations

from app.core.deployment_profile import DeploymentProfile
from app.features.ocr_gateway import OCRGateway


def test_cloud_registry_skips_local():
    """cloud_api gateway should not register local PaddleOCR backend."""
    gw = OCRGateway(mode="shadow", profile=DeploymentProfile.CLOUD_API)
    backends = gw._registry.list_ocr()
    # May be empty if remote adapter not registered, but should NOT contain paddle
    for b in backends:
        if hasattr(b, "capabilities"):
            # paddleocr-vl is REMOTE (allowed), but full paddleocr is LOCAL (forbidden)
            assert b.capabilities.backend not in ("paddleocr",)
