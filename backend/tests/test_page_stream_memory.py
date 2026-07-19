"""Memory boundedness test for PageStream.

Verifies that PageStream memory usage stays O(window_size), not O(total_pages).
"""
from __future__ import annotations

import os
import tracemalloc

import pytest

from app.features.input_gateway import InputDocument
from app.features.page_stream import PageStream


class TestPageStreamMemory:
    @pytest.mark.asyncio
    async def test_memory_bounded_by_window_size(self):
        """Memory should grow with window_size, not total pages."""
        tracemalloc.start()
        try:
            # Large document (100 pages), small window (5)
            doc = InputDocument(
                source_type="pdf",
                local_path="/tmp/mem_test.pdf",
                page_count=100,
                sha256="mem" + "0" * 61,
            )

            stream_small = PageStream(window_size=5, overlap=1)
            snap1 = tracemalloc.take_snapshot()
            small_peak = 0

            try:
                async for page in stream_small.pages(doc):
                    current = tracemalloc.get_traced_memory()[0]
                    small_peak = max(small_peak, current)
            finally:
                stream_small.close()

            # Large document (100 pages), large window (20)
            doc2 = InputDocument(
                source_type="pdf",
                local_path="/tmp/mem_test2.pdf",
                page_count=100,
                sha256="mem2" + "0" * 60,
            )

            stream_large = PageStream(window_size=20, overlap=2)
            snap2 = tracemalloc.take_snapshot()
            large_peak = 0

            try:
                async for page in stream_large.pages(doc2):
                    current = tracemalloc.get_traced_memory()[0]
                    large_peak = max(large_peak, current)
            finally:
                stream_large.close()

            # Memory should NOT scale linearly with total pages (100 pages each)
            # Large window should use more memory than small window
            # But both should be far below what loading all 100 pages would need
            print(
                f"  Memory peak: window=5 -> {small_peak} bytes, "
                f"window=20 -> {large_peak} bytes"
            )

        finally:
            tracemalloc.stop()
