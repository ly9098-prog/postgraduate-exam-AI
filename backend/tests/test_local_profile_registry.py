"""Local Profile Registry — Verify local profile adapter registration."""
from __future__ import annotations

from app.features.ocr_gateway import OCRGateway


def test_local_registry_allows_local():
    """local_import gateway may register local PaddleOCR backend."""
    gw = OCRGateway(mode="shadow", profile="local_import")
    backends = gw._registry.list_ocr()
    # Local adapter registration is optional (depends on PaddleOCR availability)
    # The key assertion is that the gateway allows local backend in principle
    assert gw._get_forbidden_fallback() == []
