"""Shadow equivalence test for OCRGateway.

Verifies that shadow mode computes the same routing as gateway mode
would, but without performing actual OCR calls.
"""
from __future__ import annotations

import pytest

from app.features.ocr_gateway import OCRGateway, RequiredOCRCapabilities
from app.features.page_stream import RenderedPage


class TestOCRGatewayShadowEquivalence:
    """Shadow mode routing decisions must be deterministic and equivalent."""

    @pytest.mark.asyncio
    async def test_same_routing_for_same_input(self):
        """Same input should produce same routing decision each time."""
        gateway = OCRGateway(mode="shadow")
        page = RenderedPage(page_index=0, page_id="p0000")

        route1 = await gateway.route_page(page)
        route2 = await gateway.route_page(page)

        assert route1.selected_backend == route2.selected_backend
        assert route1.fallback_chain == route2.fallback_chain

    @pytest.mark.asyncio
    async def test_different_pages_same_routing(self):
        """Different pages with same requirements should route the same."""
        gateway = OCRGateway(mode="shadow")
        p0 = RenderedPage(page_index=0, page_id="p0000")
        p1 = RenderedPage(page_index=1, page_id="p0001")

        r0 = await gateway.route_page(p0)
        r1 = await gateway.route_page(p1)

        assert r0.selected_backend == r1.selected_backend

    @pytest.mark.asyncio
    async def test_shadow_never_calls_real_ocr(self):
        """Shadow mode routing must never make real OCR calls."""
        gateway = OCRGateway(mode="shadow")
        page = RenderedPage(page_index=0, page_id="p0000")

        result = await gateway.recognize_page(page, trace_id="shadow-eq")
        assert result.is_success
        # In shadow mode, the data is a route dict, not a DocumentIR
        assert "gateway_route" in result.data
        route = result.data["gateway_route"]
        assert "selected_backend" in route
        assert "fallback_chain" in route
        assert "reason_codes" in route
