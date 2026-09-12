"""OCR Adapter tests — contract, capabilities, registry, selector, lifecycle."""
from __future__ import annotations

import pytest

from app.core.ocr_request import OCRRequest
from app.features.ocr_adapter import (
    AdapterRegistry,
    AdapterSelector,
    PaddleOCRLocalAdapter,
    PaddleOCRVLDocumentAdapter,
    ReadingOrderTransformAdapter,
    RuleFallbackAdapter,
    create_default_adapter_registry,
)

# ===========================================================================
# Contract: all adapters must implement protocol properties
# ===========================================================================


class TestOcrAdapterContract:
    """All OcrAdapter implementations must satisfy the protocol."""

    def test_paddleocr_local_adapter_contract(self):
        adapter = PaddleOCRLocalAdapter(engine="paddleocr")
        cap = adapter.capabilities
        assert cap.backend == "paddleocr"
        assert cap.adapter_type == "ocr"
        assert cap.text is True
        assert cap.bbox is True
        assert cap.offline is True
        # Must accept PDF and images
        assert "application/pdf" in cap.supported_mime_types
        assert "image/png" in cap.supported_mime_types

    def test_paddleocr_vl_adapter_contract(self):
        adapter = PaddleOCRVLDocumentAdapter(api_token="test-token")
        cap = adapter.capabilities
        assert cap.backend == "paddleocr-vl"
        assert cap.adapter_type == "ocr"
        assert cap.text is True
        assert cap.layout is True
        assert cap.formula is True
        assert cap.offline is False
        assert cap.requires_network is True
        # VL does not support PDF directly
        assert "application/pdf" not in cap.supported_mime_types

    def test_reading_order_transform_contract(self):
        adapter = ReadingOrderTransformAdapter()
        cap = adapter.capabilities
        assert cap.backend == "reading_order"
        assert cap.adapter_type == "transform"
        assert cap.reading_order is True
        assert cap.offline is True
        assert cap.thread_safe is True

    def test_rule_fallback_contract(self):
        adapter = RuleFallbackAdapter()
        cap = adapter.capabilities
        assert cap.backend == "rule_fallback"
        assert cap.adapter_type == "transform"
        assert cap.offline is True
        assert cap.max_concurrency == 100


class TestAdapterCapabilitiesConsistency:
    """Capabilities must use tuple/frozenset (no mutable types)."""

    def test_layout_labels_are_tuple(self):
        adapter = PaddleOCRVLDocumentAdapter(api_token="t")
        assert isinstance(adapter.capabilities.layout_labels, tuple)

    def test_region_types_are_tuple(self):
        adapter = PaddleOCRVLDocumentAdapter(api_token="t")
        assert isinstance(adapter.capabilities.region_types, tuple)

    def test_devices_are_tuple(self):
        adapter = PaddleOCRLocalAdapter()
        assert isinstance(adapter.capabilities.supported_devices, tuple)

    def test_mime_types_are_tuple(self):
        adapter = PaddleOCRLocalAdapter()
        assert isinstance(adapter.capabilities.supported_mime_types, tuple)


# ===========================================================================
# Adapter lifecycle (close, double-close)
# ===========================================================================


class TestAdapterLifecycle:
    @pytest.mark.asyncio
    async def test_close_is_idempotent(self):
        adapter = ReadingOrderTransformAdapter()
        await adapter.close()
        await adapter.close()  # second close should not raise

    @pytest.mark.asyncio
    async def test_closed_adapter_returns_error(self):
        adapter = ReadingOrderTransformAdapter()
        await adapter.close()
        result = await adapter.transform(None)
        assert result.is_failure

    @pytest.mark.asyncio
    async def test_paddleocr_vl_close(self):
        adapter = PaddleOCRVLDocumentAdapter(api_token="test")
        await adapter.close()
        result = await adapter.process(
            OCRRequest(source=b"test", source_type="png")
        )
        assert result.is_failure
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_fallback_close(self):
        adapter = RuleFallbackAdapter()
        await adapter.close()
        result = await adapter.transform(None)
        assert result.is_failure


# ===========================================================================
# ReadingOrderTransform
# ===========================================================================


class TestReadingOrderTransform:
    @pytest.mark.asyncio
    async def test_transform_none_returns_failure(self):
        adapter = ReadingOrderTransformAdapter()
        result = await adapter.transform(None)
        assert result.is_failure

    @pytest.mark.asyncio
    async def test_transform_empty_document_is_ok(self):
        """Empty document (no pages) returns failure because no pages to process."""
        from app.core.document_ir import new_document

        adapter = ReadingOrderTransformAdapter()
        doc = new_document()
        result = await adapter.transform(doc)
        # Empty doc can't have reading order — should be failure
        assert result.is_failure


# ===========================================================================
# RuleFallback
# ===========================================================================


class TestRuleFallback:
    @pytest.mark.asyncio
    async def test_passthrough_returns_same_data(self):
        adapter = RuleFallbackAdapter()
        data = {"key": "value"}
        result = await adapter.transform(data)
        assert result.is_success
        assert result.data == data

    @pytest.mark.asyncio
    async def test_none_input_fails(self):
        adapter = RuleFallbackAdapter()
        result = await adapter.transform(None)
        assert result.is_failure


# ===========================================================================
# AdapterRegistry
# ===========================================================================


class TestAdapterRegistry:
    def test_empty_registry(self):
        registry = AdapterRegistry()
        assert len(registry) == 0
        assert registry.list_ocr() == []
        assert registry.list_transform() == []

    def test_register_ocr_adapter(self):
        registry = AdapterRegistry()
        adapter = PaddleOCRLocalAdapter()
        registry.register_ocr(adapter)
        assert len(registry) == 1
        assert registry.get_ocr("paddleocr") is adapter

    def test_register_transform(self):
        registry = AdapterRegistry()
        adapter = ReadingOrderTransformAdapter()
        registry.register_transform(adapter)
        assert len(registry) == 1
        assert registry.get_transform("reading_order") is adapter

    def test_get_nonexistent_returns_none(self):
        registry = AdapterRegistry()
        assert registry.get_ocr("nonexistent") is None
        assert registry.get_transform("nonexistent") is None

    @pytest.mark.asyncio
    async def test_registry_close_all(self):
        registry = AdapterRegistry()
        registry.register_ocr(PaddleOCRLocalAdapter())
        registry.register_transform(ReadingOrderTransformAdapter())
        await registry.close_all()
        assert len(registry) == 0

    def test_default_registry_contains_standard_adapters(self):
        registry = create_default_adapter_registry(vl_api_token="test")
        assert registry.get_ocr("paddleocr") is not None
        assert registry.get_ocr("paddleocr-vl") is not None
        assert registry.get_transform("reading_order") is not None
        assert registry.get_transform("rule_fallback") is not None
        assert len(registry) == 4


# ===========================================================================
# AdapterSelector
# ===========================================================================


class TestAdapterSelector:
    def create_registry(self) -> AdapterRegistry:
        registry = AdapterRegistry()
        registry.register_ocr(PaddleOCRLocalAdapter())
        registry.register_ocr(PaddleOCRVLDocumentAdapter(api_token="test"))
        registry.register_transform(ReadingOrderTransformAdapter())
        registry.register_transform(RuleFallbackAdapter())
        return registry

    def test_select_ocr_by_capability(self):
        registry = self.create_registry()
        selector = AdapterSelector(registry)
        selector.register_backend("paddleocr")
        selector.register_backend("paddleocr-vl")

        # PDF request should select local (local supports PDF, VL does not)
        req = OCRRequest(source=b"%PDF-content", source_type="pdf")
        adapter = selector.select_ocr(req)
        assert adapter is not None
        # Local adapter supports PDF
        cap = adapter.capabilities
        assert "application/pdf" in cap.supported_mime_types

    def test_select_ocr_preferred_backend(self):
        registry = self.create_registry()
        selector = AdapterSelector(registry)
        selector.register_backend("paddleocr")
        selector.register_backend("paddleocr-vl")

        req = OCRRequest(source=b"image-data", source_type="png")
        adapter = selector.select_ocr(req, preferred_backend="paddleocr-vl")
        assert adapter is not None
        assert adapter.capabilities.backend == "paddleocr-vl"

    def test_select_ocr_require_layout(self):
        registry = self.create_registry()
        selector = AdapterSelector(registry)
        selector.register_backend("paddleocr")
        selector.register_backend("paddleocr-vl")

        req = OCRRequest(source=b"image-data", source_type="png")
        # VL supports layout, local does not
        adapter = selector.select_ocr(req, require_layout=True)
        assert adapter is not None
        assert adapter.capabilities.layout is True
        assert adapter.capabilities.backend == "paddleocr-vl"

    def test_select_ocr_require_offline(self):
        registry = self.create_registry()
        selector = AdapterSelector(registry)
        selector.register_backend("paddleocr")
        selector.register_backend("paddleocr-vl")

        req = OCRRequest(source=b"data", source_type="pdf")
        adapter = selector.select_ocr(req, require_offline=True)
        assert adapter is not None
        assert adapter.capabilities.offline is True
        assert adapter.capabilities.backend == "paddleocr"

    def test_select_transform_reading_order(self):
        registry = self.create_registry()
        selector = AdapterSelector(registry)
        selector.register_backend("reading_order")
        selector.register_backend("rule_fallback")

        adapter = selector.select_transform(require_reading_order=True)
        assert adapter is not None
        assert adapter.capabilities.reading_order is True

    def test_select_first_transform_without_preference(self):
        """Without preference, returns the first healthy transform adapter."""
        registry = self.create_registry()
        selector = AdapterSelector(registry)
        selector.register_backend("reading_order")
        selector.register_backend("rule_fallback")

        adapter = selector.select_transform()
        assert adapter is not None
        # First registered transform is reading_order

    def test_select_no_match_returns_none(self):
        registry = AdapterRegistry()
        selector = AdapterSelector(registry)
        adapter = selector.select_ocr(OCRRequest(source=b"data", source_type="pdf"))
        assert adapter is None

    def test_circuit_breaker_blocks_unhealthy(self):
        registry = self.create_registry()
        selector = AdapterSelector(registry)
        selector.register_backend("paddleocr")

        # Record 3 failures to trip circuit breaker
        for _ in range(3):
            selector.record_failure("paddleocr")

        req = OCRRequest(source=b"data", source_type="pdf")
        adapter = selector.select_ocr(req)
        # Should return None because paddleocr is circuit-broken
        assert adapter is None

    def test_record_success_resets_failure_count(self):
        registry = self.create_registry()
        selector = AdapterSelector(registry)
        selector.register_backend("paddleocr")

        selector.record_failure("paddleocr")
        selector.record_success("paddleocr")

        req = OCRRequest(source=b"data", source_type="pdf")
        adapter = selector.select_ocr(req)
        assert adapter is not None

    def test_all_adapters_summary(self):
        registry = self.create_registry()
        selector = AdapterSelector(registry)

        summary = selector.all_adapters()
        assert "paddleocr" in summary
        assert "paddleocr-vl" in summary
        assert "reading_order" in summary
        assert "rule_fallback" in summary


# ===========================================================================
# Concurrent call tracking
# ===========================================================================


class TestConcurrentCallTracking:
    def test_concurrent_calls_tracked(self):
        registry = AdapterRegistry()
        registry.register_ocr(PaddleOCRLocalAdapter())
        selector = AdapterSelector(registry)
        selector.register_backend("paddleocr")

        selector.increment_concurrent("paddleocr")
        health = selector._health["paddleocr"]
        assert health.concurrent_calls == 1
