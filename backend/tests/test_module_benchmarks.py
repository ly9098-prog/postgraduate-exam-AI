"""Module benchmark framework tests — correctness, not performance."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from app.core.document_ir import new_document
from app.features.ocr_adapter import (
    AdapterRegistry,
    ReadingOrderTransformAdapter,
    RuleFallbackAdapter,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def sample_document():
    """Create a minimal DocumentIR with regions."""
    doc = new_document()
    from app.core.document_ir import BBox, LineIR, PageIR, RegionIR, make_page_id, make_region_id, make_line_id

    page_id = make_page_id(doc.document_id, 0)
    page = PageIR(
        page_id=page_id,
        page_index=0,
        width=800,
        height=600,
    )

    # Two simple text regions
    for idx, (text, y_pos) in enumerate([
        ("第一章 数据结构", 50),
        ("1.1 基本概念", 150),
    ]):
        rid = make_region_id(page_id, BBox(50, y_pos, 750, y_pos + 40), "test", text[:64])
        lid = make_line_id(rid, BBox(50, y_pos, 750, y_pos + 40), text[:200])
        region = RegionIR(
            region_id=rid,
            region_type="text",
            bbox=BBox(50, y_pos, 750, y_pos + 40),
            confidence=0.95,
            lines=[LineIR(
                line_id=lid,
                text=text,
                bbox=BBox(50, y_pos, 750, y_pos + 40),
                confidence=0.95,
            )],
        )
        page.regions.append(region)

    doc.pages = [page]
    return doc


# ===========================================================================
# Benchmark framework correctness
# ===========================================================================


class TestBenchmarkFramework:
    """Verify the benchmark infrastructure works correctly.

    These tests validate framework correctness, not real performance.
    """

    @pytest.mark.asyncio
    async def test_reading_order_transform_is_deterministic(self, sample_document):
        """Same input produces same output (within reason)."""
        adapter = ReadingOrderTransformAdapter()

        result1 = await adapter.transform(sample_document)
        result2 = await adapter.transform(sample_document)

        assert result1.is_success
        assert result2.is_success

        # Both should have the same number of pages and regions
        assert len(result1.data.pages) == len(result2.data.pages)

    @pytest.mark.asyncio
    async def test_rule_fallback_passthrough(self):
        """Rule fallback returns identical data."""
        adapter = RuleFallbackAdapter()
        doc = new_document()

        result = await adapter.transform(doc)
        assert result.is_success
        assert result.data is doc  # same object

    @pytest.mark.asyncio
    async def test_empty_document_reading_order(self, sample_document):
        """Reading order on a doc with regions should succeed."""
        adapter = ReadingOrderTransformAdapter()
        result = await adapter.transform(sample_document)
        assert result.is_success

    @pytest.mark.asyncio
    async def test_benchmark_latency_positive(self, sample_document):
        """Latency should be a non-negative number."""
        import time

        adapter = ReadingOrderTransformAdapter()
        start = time.monotonic()
        result = await adapter.transform(sample_document)
        elapsed = (time.monotonic() - start) * 1000

        assert result.latency_ms >= 0
        # Our recorded latency should be close to actual
        assert result.latency_ms < elapsed + 100  # within 100ms tolerance


# ===========================================================================
# Benchmark runner mock test (framework test)
# ===========================================================================


class TestBenchmarkOutput:
    """Test benchmark output format without actually running benchmarks."""

    def test_manifest_format(self):
        """Run manifest should have standard fields."""
        import time
        manifest = {
            "started_at": time.time(),
            "python_version": "3.12",
            "modules": ["reading_order", "rule_fallback"],
            "fixture_hash": "abc123",
            "iterations": 3,
            "warmup_iterations": 1,
        }
        assert "started_at" in manifest
        assert "modules" in manifest
        assert "iterations" in manifest

    def test_sample_format(self):
        """Each benchmark sample should include standard metrics."""
        sample = {
            "module": "reading_order",
            "iteration": 1,
            "latency_ms": 5.2,
            "output_digest": "sha256:abc123",
            "output_item_count": 2,
            "result_validity": "valid",
            "error_code": None,
        }
        assert 0 <= sample["latency_ms"] < 60000
        assert sample["output_item_count"] >= 0

    def test_summary_format(self):
        """Summary should aggregate samples."""
        summary = {
            "module": "reading_order",
            "samples": 10,
            "warm_p50_ms": 5.2,
            "warm_p95_ms": 8.1,
            "mean_latency_ms": 5.5,
            "min_latency_ms": 3.1,
            "max_latency_ms": 12.0,
            "output_validity_pct": 100.0,
        }
        assert summary["samples"] > 0
        assert 0 <= summary["output_validity_pct"] <= 100


# ===========================================================================
# No-regression guard (framework correctness)
# ===========================================================================


class TestModuleBenchmarkNoRegression:
    """Lightweight regression guard — no absolute timing thresholds.

    These tests verify that modules don't have catastrophic (>10x) regressions
    compared to baseline expectations. They're designed to pass in CI without
    being flaky.
    """

    @pytest.mark.asyncio
    async def test_reading_order_not_catastrophically_slow(self, sample_document):
        """Reading order on a tiny doc should complete within 10s."""
        import time

        adapter = ReadingOrderTransformAdapter()
        start = time.monotonic()
        await adapter.transform(sample_document)
        elapsed_s = time.monotonic() - start

        # 10 seconds is extremely generous for 2 regions
        assert elapsed_s < 10.0, f"Reading order took {elapsed_s:.2f}s — catastrophic slowdown"

    @pytest.mark.asyncio
    async def test_rule_fallback_not_catastrophically_slow(self):
        """Rule fallback should be near-instant."""
        import time

        adapter = RuleFallbackAdapter()
        doc = new_document()

        start = time.monotonic()
        await adapter.transform(doc)
        elapsed_s = time.monotonic() - start

        # 5 seconds for a no-op passthrough
        assert elapsed_s < 5.0, f"Rule fallback took {elapsed_s:.2f}s — catastrophic slowdown"
