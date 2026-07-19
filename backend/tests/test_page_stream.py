"""Tests for Phase 4: PageStream."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from app.features.input_gateway import InputDocument
from app.features.page_stream import DEFAULT_DPI, PageRenderer, PageStream, RenderedPage


class TestRenderedPage:
    def test_create_rendered_page(self):
        page = RenderedPage(
            page_index=0,
            page_id="p0000",
            image_path="/tmp/test.png",
            width=1654,
            height=2339,
        )
        assert page.page_index == 0


class TestPageRenderer:
    def test_fallback_render(self):
        renderer = PageRenderer()
        with tempfile.TemporaryDirectory() as tmp:
            page = renderer._fallback_render(0, os.path.join(tmp, "p0000.png"), DEFAULT_DPI)
            assert page.page_index == 0
            assert page.width == 1654
            assert page.height == 2339


class TestPageStream:
    @pytest.mark.asyncio
    async def test_window_size_property(self):
        stream = PageStream(window_size=3, overlap=1)
        assert stream.window_size == 3

    @pytest.mark.asyncio
    async def test_default_mode(self):
        stream = PageStream()
        assert stream.mode in ("legacy", "stream")

    @pytest.mark.asyncio
    async def test_single_page_document_iteration(self):
        doc = InputDocument(
            source_type="pdf",
            local_path="/tmp/nonexistent.pdf",
            page_count=1,
            sha256="a" * 64,
        )
        stream = PageStream(window_size=3, overlap=1)
        pages = []
        try:
            async for page in stream.pages(doc):
                pages.append(page)
            assert len(pages) == 1
            assert pages[0].page_index == 0
        finally:
            stream.close()

    @pytest.mark.asyncio
    async def test_multi_page_iteration_yields_all_pages(self):
        doc = InputDocument(
            source_type="pdf",
            local_path="/tmp/nonexistent2.pdf",
            page_count=10,
            sha256="b" * 64,
        )
        stream = PageStream(window_size=3, overlap=1)
        page_indices = []
        try:
            async for page in stream.pages(doc):
                page_indices.append(page.page_index)
            # Verify all 10 unique pages are covered (may have overlap duplicates)
            assert len(set(page_indices)) == 10
            assert sorted(set(page_indices)) == list(range(10))
        finally:
            stream.close()

    @pytest.mark.asyncio
    async def test_window_overlap_stride(self):
        """With window=3, overlap=1, stride=2, test iteration covers all pages."""
        doc = InputDocument(
            source_type="pdf",
            local_path="/tmp/overlap_test.pdf",
            page_count=5,
            sha256="c" * 64,
        )
        stream = PageStream(window_size=3, overlap=1)
        pages = []
        try:
            async for page in stream.pages(doc):
                pages.append(page)
            # window 0: p0, p1, p2
            # window 1: p2, p3, p4  (overlap on p2)
            # Total unique: p0, p1, p2, p3, p4 = 5 unique
            assert len(set(p.page_index for p in pages)) == 5
        finally:
            stream.close()

    @pytest.mark.asyncio
    async def test_render_fresh_creates_artifact(self):
        """Rendering a page should create metadata artifact."""
        doc = InputDocument(
            source_type="pdf",
            local_path="/tmp/fresh_test.pdf",
            page_count=2,
            sha256="d" * 64,
        )
        stream = PageStream(window_size=3, overlap=0)
        rendered_dir = ""
        try:
            async for page in stream.pages(doc):
                if not rendered_dir:
                    rendered_dir = stream._rendered_dir
                # Check metadata file was written
                meta_path = os.path.join(
                    rendered_dir, f"p{page.page_index:04d}.meta.json"
                )
                assert os.path.exists(meta_path)
        finally:
            stream.close()

    @pytest.mark.asyncio
    async def test_close_cleans_up(self):
        doc = InputDocument(
            source_type="pdf",
            local_path="/tmp/cleanup_test.pdf",
            page_count=1,
            sha256="e" * 64,
        )
        stream = PageStream(window_size=3, overlap=0)
        rendered_dir = ""
        try:
            async for page in stream.pages(doc):
                rendered_dir = stream._rendered_dir
        finally:
            stream.close()
        # After close, rendered_dir should be cleaned
        if rendered_dir:
            assert not os.path.exists(rendered_dir)

    @pytest.mark.asyncio
    async def test_closed_stream_raises(self):
        stream = PageStream()
        stream.close()
        with pytest.raises(RuntimeError, match="closed"):
            async for _ in stream.pages(
                InputDocument(source_type="pdf", local_path="/tmp/x.pdf", sha256="f" * 64)
            ):
                pass
