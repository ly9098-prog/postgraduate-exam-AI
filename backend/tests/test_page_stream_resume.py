"""Resume test for PageStream.

Verifies that PageStream correctly resumes from valid artifacts
(does not re-render pages with matching checksums).
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from app.features.input_gateway import InputDocument
from app.features.page_stream import PageRenderer, PageStream, RenderedPage


class _ResumeTrackingRenderer(PageRenderer):
    """Renderer that tracks which pages were rendered (not resumed)."""

    def __init__(self):
        super().__init__()
        self.rendered_pages: list[int] = []

    def render_page(
        self, pdf_path: str, page_index: int, output_dir: str, dpi: int = 200,
    ) -> RenderedPage:
        self.rendered_pages.append(page_index)
        page = super()._fallback_render(
            page_index,
            os.path.join(output_dir, f"p{page_index:04d}.png"),
            dpi,
        )
        # Create a placeholder image so checksum can be computed
        img_path = page.image_path
        if img_path:
            os.makedirs(os.path.dirname(img_path), exist_ok=True)
            with open(img_path, "w") as f:
                f.write(f"placeholder p{page_index}")
        return page


class TestPageStreamResume:
    @pytest.mark.asyncio
    async def test_find_resumable_artifact_valid(self):
        """Valid artifacts should be detected as resumable."""
        with tempfile.TemporaryDirectory() as tmp:
            img_path = os.path.join(tmp, "p0000.png")
            with open(img_path, "w") as f:
                f.write("content for resume")

            checksum = self._compute_checksum(img_path)
            meta_path = os.path.join(tmp, "p0000.meta.json")
            with open(meta_path, "w") as f:
                json.dump({
                    "page_index": 0,
                    "page_id": "p0000",
                    "checksum": checksum,
                    "width": 100,
                    "height": 100,
                    "dpi": 200,
                    "pixel_count": 10000,
                    "schema_version": "1.0",
                }, f)

            doc = InputDocument(
                source_type="pdf",
                local_path="/tmp/resume_test.pdf",
                page_count=1,
                sha256="resume" + "0" * 59,
            )

            stream = PageStream(window_size=5, overlap=0)
            result = stream._find_resumable_artifact(doc, 0, img_path)
            assert result is not None
            assert result.checksum == checksum

    @pytest.mark.asyncio
    async def test_find_resumable_artifact_missing_image(self):
        stream = PageStream()
        doc = InputDocument(
            source_type="pdf",
            local_path="/tmp/missing.pdf",
            page_count=1,
            sha256="0" * 64,
        )
        result = stream._find_resumable_artifact(doc, 0, "/tmp/nonexistent.png")
        assert result is None

    @pytest.mark.asyncio
    async def test_checksum_mismatch_triggers_rerender(self):
        """Page with mismatched checksum should be re-rendered."""
        with tempfile.TemporaryDirectory() as tmp:
            # Create stale artifact
            img_path = os.path.join(tmp, "p0000.png")
            with open(img_path, "w") as f:
                f.write("stale content")

            stale_checksum = self._compute_checksum(img_path)
            meta_path = os.path.join(tmp, "p0000.meta.json")
            with open(meta_path, "w") as f:
                json.dump({
                    "page_index": 0,
                    "page_id": "p0000",
                    "checksum": stale_checksum,
                    "width": 100,
                    "height": 100,
                    "dpi": 200,
                    "pixel_count": 10000,
                    "schema_version": "1.0",
                }, f)

            # Now change the image so checksum no longer matches
            with open(img_path, "w") as f:
                f.write("modified content (checksum mismatch)")

            doc = InputDocument(
                source_type="pdf",
                local_path="/tmp/checksum_test.pdf",
                page_count=1,
                sha256="checksum" + "0" * 57,
            )

            renderer = _ResumeTrackingRenderer()
            stream = PageStream(window_size=3, overlap=0, renderer=renderer)
            try:
                stream._rendered_dir = tmp
                async for page in stream.pages(doc):
                    # Should have re-rendered with fresh checksum
                    assert page.checksum != stale_checksum
            finally:
                stream.close()

            # Should have re-rendered page 0
            assert 0 in renderer.rendered_pages

    @staticmethod
    def _compute_checksum(filepath: str) -> str:
        import hashlib
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
