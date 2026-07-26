"""OCR Gateway Profile Routes — Verify profile-aware routing."""
from __future__ import annotations

from app.core.deployment_profile import DeploymentProfile
from app.features.ocr_gateway import GatewayRouteDecision, OCRGateway


def test_cloud_profile_no_local_backend():
    gw = OCRGateway(mode="shadow", profile=DeploymentProfile.CLOUD_API)
    assert gw._profile == DeploymentProfile.CLOUD_API
    forbidden = gw._get_forbidden_fallback()
    assert "paddleocr" in forbidden


def test_local_profile_allows_local():
    gw = OCRGateway(mode="shadow", profile=DeploymentProfile.LOCAL_IMPORT)
    assert gw._get_forbidden_fallback() == []


def test_cloud_fallback_filtered():
    gw = OCRGateway(mode="shadow", profile=DeploymentProfile.CLOUD_API)
    filtered = gw._enforce_fallback_policy(["paddleocr", "paddleocr-vl"])
    assert "paddleocr" not in filtered


def test_local_fallback_preserved():
    gw = OCRGateway(mode="shadow", profile=DeploymentProfile.LOCAL_IMPORT)
    chain = ["paddleocr", "paddleocr-vl", "rule_fallback"]
    preserved = gw._enforce_fallback_policy(chain)
    assert preserved == chain


def test_cloud_gateway_route_decision():
    d = GatewayRouteDecision(selected_backend="review", fallback_chain=["review"])
    assert d.selected_backend == "review"
    assert d.fallback_chain == ["review"]
