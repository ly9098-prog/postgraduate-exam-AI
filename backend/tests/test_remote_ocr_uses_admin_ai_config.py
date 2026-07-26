"""Tests for OCRGateway using admin AI config — verify VL adapter is created with proper config."""

from __future__ import annotations

from app.core.deployment_profile import DeploymentProfile
from app.features.ocr_gateway import OCRGateway


class TestOCRGatewayDbConfig:
    """Verify OCRGateway accepts and uses resolved DB config."""

    def test_gateway_accepts_vl_config(self):
        """Gateway accepts VL API token/base_url/model from DB resolver."""
        gw = OCRGateway(
            vl_api_token="test-db-token",
            vl_base_url="https://test.api.example.com",
            vl_model="PaddleOCR-VL-Test",
            profile=DeploymentProfile.LOCAL_IMPORT,
        )
        assert gw._vl_api_token == "test-db-token"
        assert gw._vl_base_url == "https://test.api.example.com"
        assert gw._vl_model == "PaddleOCR-VL-Test"

    def test_gateway_vl_config_logged(self):
        """Gateway logs config presence without leaking token value."""
        gw = OCRGateway(
            vl_api_token="secret-token",
            vl_base_url="https://paddleocr.aistudio-app.com",
            vl_model="PaddleOCR-VL-1.6",
            profile=DeploymentProfile.LOCAL_IMPORT,
        )
        assert gw._vl_api_token == "secret-token"
        # The token value should not appear in repr
        gw_repr = repr(gw)
        assert "secret-token" not in gw_repr

    def test_gateway_empty_config_defaults(self):
        """Gateway with no config uses empty defaults (graceful degradation)."""
        gw = OCRGateway(profile=DeploymentProfile.LOCAL_IMPORT)
        assert gw._vl_api_token == ""
        assert gw._vl_base_url == ""
        assert gw._vl_model == "PaddleOCR-VL-1.6"

    def test_gateway_config_for_cloud_profile(self):
        """Cloud profile should not register local paddleocr."""
        gw = OCRGateway(profile=DeploymentProfile.CLOUD_API)
        assert gw._profile == DeploymentProfile.CLOUD_API
        allowed_backends = {a.capabilities.backend for a in gw._registry.list_ocr()}
        # cloud_api should NOT have "paddleocr" backend (local)
        registered_names = allowed_backends
        assert "paddleocr" not in registered_names, "cloud_api must not register local PaddleOCR"

    def test_gateway_config_for_local_profile(self):
        """Local profile should register local paddleocr."""
        gw = OCRGateway(profile=DeploymentProfile.LOCAL_IMPORT)
        allowed_backends = {a.capabilities.backend for a in gw._registry.list_ocr()}
        assert "paddleocr" in allowed_backends, "local_import must register local PaddleOCR"

    def test_gateway_forbidden_fallback_cloud(self):
        """Cloud profile forbids local fallback backends."""
        gw = OCRGateway(profile=DeploymentProfile.CLOUD_API)
        forbidden = gw._get_forbidden_fallback()
        assert "paddleocr" in forbidden
        assert "rule_fallback" in forbidden
        assert "paddleocr-vl" not in forbidden  # remote VL is allowed

    def test_gateway_forbidden_fallback_local(self):
        """Local profile has no forbidden fallbacks."""
        gw = OCRGateway(profile=DeploymentProfile.LOCAL_IMPORT)
        forbidden = gw._get_forbidden_fallback()
        assert len(forbidden) == 0
