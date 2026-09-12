"""Cloud OCR No Local Fallback — Verify cloud profile never falls back to local OCR."""
from __future__ import annotations

from app.core.deployment_profile import DeploymentProfile
from app.features.ocr_gateway import OCRGateway


def test_cloud_gateway_denies_local_fallback():
    gw = OCRGateway(mode="shadow", profile=DeploymentProfile.CLOUD_API)
    forbidden = gw._get_forbidden_fallback()
    assert "paddleocr" in forbidden
    assert "paddleocr-vl" not in forbidden  # remote is OK


def test_cloud_gateway_forbidden_fallback_is_enforced():
    gw = OCRGateway(mode="shadow", profile=DeploymentProfile.CLOUD_API)
    # If fallback chain somehow contains local backends, they must be filtered
    chain = ["paddleocr", "remote_api"]
    result = gw._enforce_fallback_policy(chain)
    assert "paddleocr" not in result
    assert "remote_api" in result


def test_local_gateway_allows_local_fallback():
    gw = OCRGateway(mode="shadow", profile=DeploymentProfile.LOCAL_IMPORT)
    chain = ["paddleocr", "paddleocr-vl", "rule_fallback"]
    result = gw._enforce_fallback_policy(chain)
    assert result == chain
