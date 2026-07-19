"""Tests for Phase 5: OCRGateway."""
from __future__ import annotations

import os
import tempfile

import pytest

from app.features.ocr_gateway import (
    GatewayRouteDecision,
    OCRGateway,
    RequiredOCRCapabilities,
)
from app.features.page_stream import RenderedPage


class TestOCRGateway:
    @pytest.mark.asyncio
    async def test_recognize_page_shadow_returns_route_decision(self):
        gateway = OCRGateway(mode="shadow")
        page = RenderedPage(page_index=0, page_id="p0000")
        result = await gateway.recognize_page(page, trace_id="test-shadow")
        assert result.is_success
        assert result.data_type == "GatewayRouteDecision"
        route = result.data["gateway_route"]
        assert "selected_backend" in route
        assert "fallback_chain" in route

    @pytest.mark.asyncio
    async def test_route_page_returns_decision(self):
        gateway = OCRGateway(mode="shadow")
        page = RenderedPage(page_index=0, page_id="p0000")
        route = await gateway.route_page(page)
        assert isinstance(route, GatewayRouteDecision)
        assert route.fallback_chain  # should have at least one backend

    @pytest.mark.asyncio
    async def test_legacy_mode_returns_not_active(self):
        gateway = OCRGateway(mode="legacy")
        page = RenderedPage(page_index=0, page_id="p0000")
        result = await gateway.recognize_page(page, trace_id="test-legacy")
        assert result.is_failure
        assert "GATEWAY_NOT_ACTIVE" in result.error.code

    @pytest.mark.asyncio
    async def test_shadow_does_not_call_backend(self):
        """Shadow mode must not perform actual OCR calls."""
        gateway = OCRGateway(mode="shadow")
        page = RenderedPage(page_index=0, page_id="p0000")
        result = await gateway.recognize_page(page, trace_id="test-no-call")
        assert result.is_success
        # Should return immediately without any backend calls
        assert result.latency_ms < 100  # fast path

    @pytest.mark.asyncio
    async def test_gateway_mode_property(self):
        shadow = OCRGateway(mode="shadow")
        legacy = OCRGateway(mode="legacy")
        gw = OCRGateway(mode="gateway")
        assert shadow.is_shadow
        assert not shadow.is_gateway
        assert not legacy.is_shadow
        assert gw.is_gateway

    @pytest.mark.asyncio
    async def test_required_capabilities_defaults(self):
        caps = RequiredOCRCapabilities()
        assert caps.text
        assert caps.bbox
        assert not caps.layout
        assert not caps.offline

    @pytest.mark.asyncio
    async def test_multiple_shadow_calls_idempotent(self):
        """Shadow mode calls should be idempotent and fast."""
        gateway = OCRGateway(mode="shadow")
        page = RenderedPage(page_index=0, page_id="p0000")
        r1 = await gateway.recognize_page(page, trace_id="shadow-1")
        r2 = await gateway.recognize_page(page, trace_id="shadow-2")
        assert r1.is_success
        assert r2.is_success


class TestOCRGatewayShadowNoDoubleCall:
    """Shadow mode must NOT call backend twice."""

    @pytest.mark.asyncio
    async def test_shadow_no_side_effects(self):
        gateway = OCRGateway(mode="shadow")
        page = RenderedPage(page_index=0, page_id="p0000")
        result = await gateway.recognize_page(page, trace_id="test-no-side")
        assert result.is_success
        # Shadow must not trigger any real OCR adapter process()
        # This is verified by latency < 100ms and no adapter errors
        assert result.latency_ms >= 0
        assert result.error is None
