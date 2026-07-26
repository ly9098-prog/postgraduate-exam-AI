"""Sprint 4C: Cloud Gateway E2E — profile-restricted adapter registration.

Verifies cloud_api profile does not register local adapters.
"""

from __future__ import annotations

from app.core.deployment_profile import DeploymentProfile


class TestCloudGatewayProfileRestricted:
    """Verify cloud_api profile gateway restricts local adapter registration."""

    def test_cloud_gateway_importable(self):
        """OCRGateway is importable."""
        from app.features.ocr_gateway import OCRGateway
        assert OCRGateway is not None

    def test_cloud_gateway_no_local_adapter(self):
        """OCRGateway(profile='cloud_api') does not register local paddleocr.

        Note: AdapterRegistry.__len__ makes empty registries falsy, so
        ``registry or AdapterRegistry()`` creates a NEW registry.  We read
        backends from ``gw._registry`` instead of the passed-in object.
        """
        from app.features.ocr_adapter import AdapterRegistry
        from app.features.ocr_gateway import OCRGateway

        registry = AdapterRegistry()
        gw = OCRGateway(registry=registry, mode="shadow", profile=DeploymentProfile.CLOUD_API)

        backends = {a.capabilities.backend for a in gw._registry.list_ocr()}
        assert "paddleocr" not in backends, (
            f"Local 'paddleocr' must not be registered for cloud_api. "
            f"Found: {backends}"
        )

    def test_local_profile_registers_local_adapter(self):
        """OCRGateway(profile='local_import') does register local paddleocr."""
        from app.features.ocr_adapter import AdapterRegistry
        from app.features.ocr_gateway import OCRGateway

        registry = AdapterRegistry()
        gw = OCRGateway(registry=registry, mode="shadow", profile=DeploymentProfile.LOCAL_IMPORT)

        backends = {a.capabilities.backend for a in gw._registry.list_ocr()}
        assert "paddleocr" in backends, (
            f"Local 'paddleocr' must be registered for local_import. "
            f"Found: {backends}"
        )

    def test_cloud_gateway_route_decision_type(self):
        """GatewayRouteDecision has expected fields."""
        from app.features.ocr_gateway import GatewayRouteDecision

        decision = GatewayRouteDecision(
            selected_backend="paddleocr-vl",
            confidence=0.8,
            reason_codes=["SELECTED:paddleocr-vl"],
            capabilities_met=True,
            fallback_chain=["paddleocr-vl", "paddleocr"],
        )

        assert decision.selected_backend == "paddleocr-vl"
        assert decision.confidence == 0.8
        assert decision.capabilities_met is True
        assert len(decision.fallback_chain) == 2

    def test_cloud_gateway_construction(self):
        """OCRGateway can be constructed with cloud_api profile."""
        from app.features.ocr_gateway import OCRGateway

        gw = OCRGateway(mode="shadow", profile=DeploymentProfile.CLOUD_API)
        assert gw.mode == "shadow"
        assert gw.is_shadow is True
        assert gw.is_gateway is False

    def test_cloud_gateway_mode_properties(self):
        """OCRGateway mode/is_shadow/is_gateway properties work."""
        from app.features.ocr_gateway import OCRGateway

        g1 = OCRGateway(mode="legacy", profile=DeploymentProfile.LOCAL_IMPORT)
        assert g1.is_shadow is False
        assert g1.is_gateway is False

        g2 = OCRGateway(mode="shadow", profile=DeploymentProfile.LOCAL_IMPORT)


        g3 = OCRGateway(mode="gateway", profile=DeploymentProfile.LOCAL_IMPORT)
        assert g3.is_shadow is False
        assert g3.is_gateway is True

    def test_gateway_route_decision_defaults(self):
        """GatewayRouteDecision has sensible defaults."""
        from app.features.ocr_gateway import GatewayRouteDecision

        d = GatewayRouteDecision()
        assert d.selected_backend == ""
        assert d.confidence == 0.0
        assert d.capabilities_met is False
        assert d.fallback_chain == []
        assert d.reason_codes == []

    def test_required_ocr_capabilities_defaults(self):
        """RequiredOCRCapabilities has text and bbox enabled by default."""
        from app.features.ocr_gateway import RequiredOCRCapabilities

        caps = RequiredOCRCapabilities()
        assert caps.text is True
        assert caps.bbox is True
        assert caps.layout is False
        assert caps.formula is False
        assert caps.code is False
        assert caps.offline is False

    def test_cloud_gateway_with_constructor_mode(self):
        """OCRGateway can be constructed with gateway mode."""
        from app.features.ocr_gateway import OCRGateway

        gw = OCRGateway(mode="gateway", profile=DeploymentProfile.CLOUD_API)
        assert gw.is_gateway is True
        assert gw._profile == DeploymentProfile.CLOUD_API
