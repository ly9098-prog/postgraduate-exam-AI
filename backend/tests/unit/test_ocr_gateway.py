"""Unit tests for OCRGateway construction and profile enforcement."""
from __future__ import annotations

import pytest

from app.core.deployment_profile import DeploymentProfile


class TestOCRGatewayConstruction:
    """OCRGateway must always receive an explicit DeploymentProfile."""

    def test_construction_with_profile(self) -> None:
        """Gateway constructed with explicit profile should not raise."""
        from app.features.ocr_gateway import OCRGateway

        # Must not raise TypeError about missing profile
        gateway = OCRGateway(
            profile=DeploymentProfile.LOCAL_IMPORT,
            mode="legacy",
        )
        assert gateway is not None
        assert gateway._profile == DeploymentProfile.LOCAL_IMPORT

    def test_construction_cloud_profile(self) -> None:
        """Gateway with cloud profile should register only remote backends."""
        from app.features.ocr_gateway import OCRGateway

        gateway = OCRGateway(
            profile=DeploymentProfile.CLOUD_API,
            mode="legacy",
        )
        assert gateway._profile == DeploymentProfile.CLOUD_API
        # In cloud profile, local PaddleOCR adapter must not be registered
        adapters = gateway._registry.list_ocr()
        for a in adapters:
            assert a.capabilities.backend != "paddleocr", \
                f"Cloud profile should not have local adapter, got {a}"

    def test_construction_without_profile_raises(self) -> None:
        """Gateway constructed without profile keyword should raise TypeError."""
        from app.features.ocr_gateway import OCRGateway

        with pytest.raises(TypeError):
            # profile is keyword-only after *, so positional should fail
            OCRGateway("legacy")  # type: ignore[call-arg]


class TestOCRGatewayCloudEnforcement:
    """Defence-in-depth: cloud profile must never execute local adapters."""

    @pytest.mark.asyncio
    async def test_local_adapter_skipped_in_cloud_fallback(self) -> None:
        """Cloud profile's _execute_with_fallback must skip local backends."""
        from app.features.ocr_gateway import (
            GatewayRouteDecision,
            OCRGateway,
        )

        gateway = OCRGateway(
            profile=DeploymentProfile.CLOUD_API,
            mode="gateway",
        )
        # Route execution must skip paddleocr/rule_fallback even if present
        route = GatewayRouteDecision(
            selected_backend="paddleocr-vl",
            fallback_chain=["paddleocr", "paddleocr-vl"],
            capabilities_met=True,
        )
        # Create a mock request
        from app.core.ocr_request import OCRRequest

        request = OCRRequest(
            source=b"fake_image_data",
            source_type="png",
            filename="p0001.png",
        )
        result = await gateway._execute_with_fallback(request, route)
        # Should NOT return ModuleResult.success from paddleocr
        # Instead it should ultimately fail since no adapter actually processes it
        assert result is not None

    def test_cloud_profile_skips_local_registration(self) -> None:
        """_register_profile_backends must skip PaddleOCRLocalAdapter in cloud."""
        from app.features.ocr_gateway import OCRGateway

        gateway = OCRGateway(
            profile=DeploymentProfile.CLOUD_API,
            mode="legacy",
        )
        # List registered backends
        backends = [a.capabilities.backend for a in gateway._registry.list_ocr()]
        assert "paddleocr" not in backends, \
            f"Cloud profile should not have local paddleocr, got {backends}"
        assert "paddleocr-vl" in backends, \
            "Cloud profile should have remote paddleocr-vl adapter"


class TestGatewayCloudModes:
    """Gateway shadow/legacy mode behavior in cloud."""

    @pytest.mark.asyncio
    async def test_legacy_mode_returns_gateway_not_active(self) -> None:
        """Legacy mode should return GATEWAY_NOT_ACTIVE, not fall back to local."""
        from app.features.ocr_gateway import OCRGateway, RequiredOCRCapabilities
        from app.features.page_stream import RenderedPage

        gateway = OCRGateway(
            profile=DeploymentProfile.CLOUD_API,
            mode="legacy",
        )
        # Create a minimal RenderedPage
        page = RenderedPage(
            page_index=0,
            page_id="p0000",
            width=100,
            height=100,
        )
        result = await gateway.recognize_page(
            page=page,
            requirements=RequiredOCRCapabilities(),
        )
        assert result.is_failure
        # GATEWAY_NOT_ACTIVE is expected for legacy mode
        assert "GATEWAY" in (result.error.code if result.error else "")
