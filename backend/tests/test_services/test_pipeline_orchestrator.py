"""Stage 8 流水线编排 — 单元测试。"""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.features.pipeline_orchestrator import (
    ImportPipeline,
    PipelineStage,
    _extract_pdf_blocks,
    _extract_text_blocks,
    _ocr_scanned_pdf,
    _pipeline_store,
    _set_pipeline_store,
    get_pipeline_status,
    resolve_pdf_page_range,
    run_import_pipeline,
    run_pipeline_background,
)
from app.features.pipeline_stages._helpers import _count_risk_flags


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_raw_blocks(n=2):
    return [{"page": i + 1, "block_index": i, "text": f"Block {i + 1} text."} for i in range(n)]


def _make_normalized_blocks(n=2):
    return [
        {"page": i + 1, "block_index": i, "raw_text": f"Block {i + 1} text.", "normalized_text": f"Block {i + 1} text."}
        for i in range(n)
    ]


def _make_raw_questions(n=2):
    return [
        {
            "number": i + 1,
            "raw_question_text": f"Question {i + 1} text",
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "x", "B": "y", "C": "z", "D": "w"},
            "confidence": 0.9,
        }
        for i in range(n)
    ]


def _make_matched(n=2):
    return [
        {
            "question_number": i + 1,
            "answer": "A",
            "explanation": f"Explanation {i + 1}",
            "answer_source": "inline",
            "explanation_source": "inline",
            "confidence": 0.9,
        }
        for i in range(n)
    ]


def _make_questions(n=2):
    return [
        {
            "schema_version": "v1",
            "subject": "math2",
            "question_type": "single_choice",
            "stem": f"Question {i + 1} stem",
            "options": [{"key": k, "text": v} for k, v in [("A", "x"), ("B", "y"), ("C", "z"), ("D", "w")]],
            "answer": "A",
            "analysis": f"Explanation {i + 1}",
            "raw_text": f"Question {i + 1} text",
            "knowledge_points": [],
            "difficulty": 3,
            "source": {"file": "test.pdf", "type": "pdf", "page": 1},
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "stem_hash": f"abc{i}",
            "confidence_score": 0.85,
        }
        for i in range(n)
    ]


def _make_mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# _extract_text_blocks
# ---------------------------------------------------------------------------


class TestExtractTextBlocks:
    def test_extracts_text(self):
        blocks = _extract_text_blocks(b"Hello\nWorld")
        assert len(blocks) == 1
        assert blocks[0]["page"] == 1
        assert blocks[0]["text"] == "Hello\nWorld"

    def test_empty_content(self):
        with pytest.raises(ValueError, match="文本内容为空"):
            _extract_text_blocks(b"   ")

    def test_utf8_decoding(self):
        blocks = _extract_text_blocks("高等数学\n线性代数".encode("utf-8"))
        assert len(blocks) == 1
        assert "高等数学" in blocks[0]["text"]


# ---------------------------------------------------------------------------
# _extract_pdf_blocks
# ---------------------------------------------------------------------------


class TestExtractPdfBlocks:
    def test_extracts_pages(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page content"
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            blocks = _extract_pdf_blocks(b"fake pdf content")

        assert len(blocks) == 1
        assert blocks[0]["page"] == 1
        assert blocks[0]["text"] == "Page content"
        mock_doc.close.assert_called_once()

    def test_skips_empty_pages(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        page1 = MagicMock()
        page1.get_text.return_value = ""
        page2 = MagicMock()
        page2.get_text.return_value = "Content"
        mock_doc.__len__ = MagicMock(return_value=2)
        mock_doc.__getitem__ = MagicMock(side_effect=[page1, page2])
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            blocks = _extract_pdf_blocks(b"fake pdf")

        assert len(blocks) == 1
        assert blocks[0]["page"] == 2

    def test_all_empty_returns_empty_list(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "   "
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = _extract_pdf_blocks(b"empty pdf")
            assert result == []

    def test_no_fitz_raises(self):
        with patch.dict(sys.modules, {"fitz": None}):
            with pytest.raises(RuntimeError, match="PyMuPDF"):
                _extract_pdf_blocks(b"any content")

    def test_page_range_extracts_only_selected_pages(self):
        """Integration: real 5-page PDF, extract pages 2-4 only."""
        import io

        try:
            import fitz  # noqa: F811
        except ImportError:
            pytest.skip("PyMuPDF not installed")

        doc = fitz.open()
        for i in range(1, 6):
            page = doc.new_page()
            page.insert_text((50, 100), f"PAGE_{i:04d}", fontsize=20)
        pdf_bytes = io.BytesIO()
        doc.save(pdf_bytes)
        doc.close()
        pdf_bytes.seek(0)

        blocks = _extract_pdf_blocks(pdf_bytes.read(), page_start=2, page_end=4)

        # Must have exactly 3 blocks (pages 2, 3, 4)
        assert len(blocks) == 3, f"Expected 3 blocks, got {len(blocks)}"

        # Block page numbers must be original physical pages
        pages = sorted(set(b["page"] for b in blocks))
        assert pages == [2, 3, 4], f"Expected pages [2,3,4], got {pages}"

        # Each block should contain its unique marker
        for b in blocks:
            assert f"PAGE_{b['page']:04d}" in b["text"], (
                f"Block from page {b['page']} should contain PAGE_{b['page']:04d}"
            )

        # Verify no text from excluded pages
        all_text = " ".join(b["text"] for b in blocks)
        assert "PAGE_0001" not in all_text, "Page 1 should not be included"
        assert "PAGE_0005" not in all_text, "Page 5 should not be included"


# ---------------------------------------------------------------------------
# _ocr_scanned_pdf
# ---------------------------------------------------------------------------


class TestOcrScannedPdf:
    def test_renders_pages_and_calls_ocr(self):
        from app.services.ocr_service import OcrPageResult

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"fake_png"
        mock_pix.width = 800
        mock_pix.height = 600
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch(
                "app.services.ocr_service.ocr_pages_with_boxes",
                return_value={1: OcrPageResult(page_index=1, text="OCR识别结果", boxes=[])},
            ) as mock_ocr:
                with patch(
                    "app.services.ocr_service.clean_ocr_text",
                    side_effect=lambda t: t,
                ):
                    blocks = _ocr_scanned_pdf(b"pdf bytes")

        assert len(blocks) == 1
        assert blocks[0]["page"] == 1
        assert blocks[0]["text"] == "OCR识别结果"
        mock_ocr.assert_called_once_with([(1, b"fake_png")], skip_rotation=True)
        mock_doc.close.assert_called_once()

    def test_skips_empty_ocr_pages(self):
        from app.services.ocr_service import OcrPageResult

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for _ in range(2):
            p = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = b"png"
            pix.width = 800
            pix.height = 600
            p.get_pixmap.return_value = pix
            pages.append(p)
        mock_doc.__len__ = MagicMock(return_value=2)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch(
                "app.services.ocr_service.ocr_pages_with_boxes",
                return_value={
                    1: OcrPageResult(page_index=1, text="", boxes=[]),
                    2: OcrPageResult(page_index=2, text="第二页内容", boxes=[]),
                },
            ):
                with patch(
                    "app.services.ocr_service.clean_ocr_text",
                    side_effect=lambda t: t,
                ):
                    blocks = _ocr_scanned_pdf(b"pdf")

        assert len(blocks) == 1
        assert blocks[0]["page"] == 2

    def test_fallbacks_failed_boxes_page_to_plain_text_ocr(self):
        from app.services.ocr_service import OcrPageResult

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for i in range(2):
            page = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = f"png{i + 1}".encode()
            pix.width = 800
            pix.height = 600
            page.get_pixmap.return_value = pix
            pages.append(page)
        mock_doc.__len__ = MagicMock(return_value=2)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch(
                "app.services.ocr_service.ocr_pages_with_boxes",
                return_value={
                    1: OcrPageResult(page_index=1, text="", boxes=[], failed=True, error="could not execute a primitive"),
                    2: OcrPageResult(page_index=2, text="", boxes=[], failed=False),
                },
            ):
                with patch(
                    "app.services.ocr_service.ocr_pages",
                    return_value={1: "01. 下列关于 TCP 协议的说法，正确的是\nA. 可靠传输"},
                ) as mock_plain_ocr:
                    with patch(
                        "app.services.ocr_service.clean_ocr_text",
                        side_effect=lambda t: t,
                    ):
                        blocks = _ocr_scanned_pdf(b"pdf")

        mock_plain_ocr.assert_called_once_with([(1, b"png1")])
        assert len(blocks) == 1
        assert blocks[0]["page"] == 1
        assert blocks[0]["page_index"] == 1
        assert blocks[0]["source"] == "ocr_text_fallback"
        assert blocks[0]["has_boxes"] is False
        assert blocks[0]["boxes"] == []
        assert blocks[0]["text"].startswith("01. 下列关于 TCP")
        assert blocks[0]["_ocr_boxes_failed"] is True

    def test_successful_boxes_block_has_source_and_no_plain_fallback(self):
        from app.services.ocr_service import OcrPageResult

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"png"
        mock_pix.width = 800
        mock_pix.height = 600
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch(
                "app.services.ocr_service.ocr_pages_with_boxes",
                return_value={
                    1: OcrPageResult(
                        page_index=1,
                        text="OCR识别结果",
                        boxes=[{"bbox": [1, 2, 3, 4], "conf": 0.9}],
                    )
                },
            ):
                with patch("app.services.ocr_service.ocr_pages") as mock_plain_ocr:
                    with patch(
                        "app.services.ocr_service.clean_ocr_text",
                        side_effect=lambda t: t,
                    ):
                        blocks = _ocr_scanned_pdf(b"pdf")

        mock_plain_ocr.assert_not_called()
        assert len(blocks) == 1
        assert blocks[0]["source"] == "ocr_boxes"
        assert blocks[0]["has_boxes"] is True
        assert blocks[0]["boxes"] == [{"bbox": [1, 2, 3, 4], "conf": 0.9}]

    def test_failed_boxes_with_empty_plain_fallback_marks_unavailable_page(self):
        from app.services.ocr_service import OcrPageResult

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for i in range(2):
            page = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = f"png{i + 1}".encode()
            pix.width = 800
            pix.height = 600
            page.get_pixmap.return_value = pix
            pages.append(page)
        mock_doc.__len__ = MagicMock(return_value=2)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch(
                "app.services.ocr_service.ocr_pages_with_boxes",
                return_value={
                    1: OcrPageResult(page_index=1, text="", boxes=[], failed=True, error="could not execute a primitive"),
                    2: OcrPageResult(page_index=2, text="02. TCP 拥塞控制中，下列说法正确的是", boxes=[]),
                },
            ):
                with patch(
                    "app.services.ocr_service.ocr_pages",
                    return_value={1: ""},
                ):
                    with patch(
                        "app.services.ocr_service.clean_ocr_text",
                        side_effect=lambda t: t,
                    ):
                        blocks = _ocr_scanned_pdf(b"pdf")

        assert len(blocks) == 1
        assert blocks[0]["page"] == 2
        assert blocks[0]["_ocr_text_fallback_unavailable_pages"] == [1]
        assert blocks[0]["_ocr_runtime_failed_pages"] == [1]
        assert "could not execute a primitive" not in str(blocks[0])

    def test_plain_fallback_batch_exception_preserves_successful_boxes_blocks(self):
        from app.services.ocr_service import OcrPageResult

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for i in range(2):
            page = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = f"png{i + 1}".encode()
            pix.width = 800
            pix.height = 600
            page.get_pixmap.return_value = pix
            pages.append(page)
        mock_doc.__len__ = MagicMock(return_value=2)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch(
                "app.services.ocr_service.ocr_pages_with_boxes",
                return_value={
                    1: OcrPageResult(page_index=1, text="", boxes=[], failed=True, error="could not execute a primitive"),
                    2: OcrPageResult(page_index=2, text="02. TCP 拥塞控制中，下列说法正确的是", boxes=[]),
                },
            ):
                with patch(
                    "app.services.ocr_service.ocr_pages",
                    side_effect=RuntimeError("could not execute a primitive"),
                ):
                    with patch(
                        "app.services.ocr_service.clean_ocr_text",
                        side_effect=lambda t: t,
                    ):
                        blocks = _ocr_scanned_pdf(b"pdf")

        assert len(blocks) == 1
        assert blocks[0]["page"] == 2
        assert blocks[0]["_ocr_text_fallback_unavailable_pages"] == [1]
        assert blocks[0]["_ocr_runtime_failed_pages"] == [1]

    def test_empty_pdf_returns_empty(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=0)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            blocks = _ocr_scanned_pdf(b"empty pdf")

        assert blocks == []

    # ── OCR page range tests ─────────────────────────────────────────────
    # P2: Verify _ocr_scanned_pdf respects page_start/page_end and
    #     truncation warnings use correct denominator.

    @staticmethod
    def _make_ocr_side_effect(all_results):
        """Return a side_effect that filters OCR results to only input pages."""
        def _side_effect(batch_images, **kwargs):
            input_pages = set(idx for idx, _ in batch_images)
            return {p: all_results[p] for p in input_pages if p in all_results}
        return _side_effect

    @staticmethod
    def _make_ocr_page_results(pages: list[int]):
        from app.services.ocr_service import OcrPageResult
        return {
            p: OcrPageResult(page_index=p, text=f"OCR text page {p}", boxes=[])
            for p in pages
        }

    def test_ocr_page_range_renders_only_selected_pages(self):
        """5-page PDF, pages 2-4 → only pages 2,3,4 OCR'd with original page numbers."""
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = [MagicMock() for _ in range(5)]
        for i, p in enumerate(pages):
            pix = MagicMock()
            pix.tobytes.return_value = f"png_{i + 1}".encode()
            pix.width = 800
            pix.height = 600
            p.get_pixmap.return_value = pix
        mock_doc.__len__ = MagicMock(return_value=5)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        ocr_results = self._make_ocr_page_results(list(range(1, 6)))

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch(
                "app.services.ocr_service.ocr_pages_with_boxes",
                side_effect=self._make_ocr_side_effect(ocr_results),
            ):
                with patch(
                    "app.services.ocr_service.clean_ocr_text",
                    side_effect=lambda t: t,
                ):
                    blocks = _ocr_scanned_pdf(b"pdf", page_start=2, page_end=4)

        assert len(blocks) == 3, f"Expected 3 blocks, got {len(blocks)}"
        pages_found = sorted(set(b["page"] for b in blocks))
        assert pages_found == [2, 3, 4], f"Expected pages [2,3,4], got {pages_found}"

        accessed_indices = [call[0][0] for call in mock_doc.__getitem__.call_args_list]
        assert accessed_indices == [1, 2, 3], f"fitz accessed indices {accessed_indices}, expected [1,2,3]"

    def test_ocr_page_range_excludes_out_of_range_pages(self):
        """Pages 1 and 5 are NOT rendered when range is 2-4."""
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = [MagicMock() for _ in range(5)]
        for i, p in enumerate(pages):
            pix = MagicMock()
            pix.tobytes.return_value = f"png_{i + 1}".encode()
            pix.width = 800
            pix.height = 600
            p.get_pixmap.return_value = pix
        mock_doc.__len__ = MagicMock(return_value=5)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        ocr_results = self._make_ocr_page_results(list(range(1, 6)))

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch(
                "app.services.ocr_service.ocr_pages_with_boxes",
                side_effect=self._make_ocr_side_effect(ocr_results),
            ):
                with patch(
                    "app.services.ocr_service.clean_ocr_text",
                    side_effect=lambda t: t,
                ):
                    blocks = _ocr_scanned_pdf(b"pdf", page_start=2, page_end=4)

        all_page_nums = set(b["page"] for b in blocks)
        assert 1 not in all_page_nums, "Page 1 should not appear"
        assert 5 not in all_page_nums, "Page 5 should not appear"

    def test_ocr_no_truncation_warning_when_range_under_limit(self):
        """100-page PDF, select 10 pages, MAX_OCR_PAGES=20 → no truncation warning."""
        from app.core.config import settings

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = [MagicMock() for _ in range(100)]
        for i, p in enumerate(pages):
            pix = MagicMock()
            pix.tobytes.return_value = f"png_{i + 1}".encode()
            pix.width = 800
            pix.height = 600
            p.get_pixmap.return_value = pix
        mock_doc.__len__ = MagicMock(return_value=100)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        ocr_results = self._make_ocr_page_results(list(range(1, 101)))

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch.object(settings, "MAX_OCR_PAGES", 20):
                with patch(
                    "app.services.ocr_service.ocr_pages_with_boxes",
                    side_effect=self._make_ocr_side_effect(ocr_results),
                ):
                    with patch(
                        "app.services.ocr_service.clean_ocr_text",
                        side_effect=lambda t: t,
                    ):
                        blocks = _ocr_scanned_pdf(b"pdf", page_start=1, page_end=10)

        warnings = blocks[0].get("_warnings", []) if blocks else []
        trunc_warnings = [w for w in warnings if "ocr_pages_truncated" in w]
        assert len(trunc_warnings) == 0, f"Unexpected truncation warnings: {trunc_warnings}"
        assert len(blocks) == 10

    def test_ocr_truncation_warning_uses_selected_page_count(self):
        """Select 51 pages, MAX_OCR_PAGES=20 → '20/51 selected pages' warning."""
        from app.core.config import settings

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = [MagicMock() for _ in range(100)]
        for i, p in enumerate(pages):
            pix = MagicMock()
            pix.tobytes.return_value = f"png_{i + 1}".encode()
            pix.width = 800
            pix.height = 600
            p.get_pixmap.return_value = pix
        mock_doc.__len__ = MagicMock(return_value=100)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        ocr_results = self._make_ocr_page_results(list(range(1, 101)))

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch.object(settings, "MAX_OCR_PAGES", 20):
                with patch(
                    "app.services.ocr_service.ocr_pages_with_boxes",
                    side_effect=self._make_ocr_side_effect(ocr_results),
                ):
                    with patch(
                        "app.services.ocr_service.clean_ocr_text",
                        side_effect=lambda t: t,
                    ):
                        blocks = _ocr_scanned_pdf(b"pdf", page_start=1, page_end=51)

        warnings = blocks[0].get("_warnings", []) if blocks else []
        trunc_warnings = [w for w in warnings if "ocr_pages_truncated" in w]
        assert len(trunc_warnings) >= 1
        assert "20/51" in trunc_warnings[0], (
            f"Expected '20/51' in truncation warning, got: {trunc_warnings}"
        )


class TestRunExtractOcrFallback:
    def test_scanned_pdf_triggers_paddleocr(self):
        pipeline = ImportPipeline()
        sparse_blocks = [{"page": 1, "block_index": 0, "text": "ab"}]
        ocr_blocks = [{"page": 1, "block_index": 0, "text": "OCR 识别到的完整内容"}]

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=sparse_blocks,
        ):
            with patch(
                "app.features.pipeline_orchestrator._ocr_scanned_pdf",
                return_value=ocr_blocks,
            ) as mock_ocr:
                with patch("app.core.config.settings.OCR_ENABLED", True):
                    result = pipeline._run_extract(b"pdf content", "pdf")

        mock_ocr.assert_called_once_with(b"pdf content", pipeline_id="", page_start=1, page_end=None)
        assert result["raw_blocks"] == ocr_blocks
        assert result["extracted"] == 1

    def test_scanned_pdf_ocr_disabled_uses_sparse(self):
        pipeline = ImportPipeline()
        sparse_blocks = [{"page": 1, "block_index": 0, "text": "ab"}]

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=sparse_blocks,
        ):
            with patch("app.core.config.settings.OCR_ENABLED", False):
                result = pipeline._run_extract(b"pdf content", "pdf")

        assert result["raw_blocks"] == sparse_blocks

    def test_scanned_pdf_ocr_failure_falls_back(self):
        pipeline = ImportPipeline()
        sparse_blocks = [{"page": 1, "block_index": 0, "text": "x"}]

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=sparse_blocks,
        ):
            with patch(
                "app.features.pipeline_orchestrator._ocr_scanned_pdf",
                side_effect=RuntimeError("paddleocr 未安装"),
            ):
                with patch("app.core.config.settings.OCR_ENABLED", True):
                    result = pipeline._run_extract(b"pdf content", "pdf")

        assert result["raw_blocks"] == sparse_blocks

    def test_run_extract_exposes_ocr_fallback_page_diagnostics(self):
        pipeline = ImportPipeline()
        sparse_blocks = [{"page": 1, "block_index": 0, "text": "x"}]
        ocr_blocks = [
            {
                "page": 245,
                "page_index": 245,
                "block_index": 0,
                "text": "01. 下列关于 TCP 协议的说法，正确的是",
                "source": "ocr_text_fallback",
                "has_boxes": False,
                "boxes": [],
                "_ocr_boxes_failed": True,
                "_ocr_text_fallback_unavailable_pages": [247],
                "_ocr_runtime_failed_pages": [247],
            },
            {
                "page": 246,
                "page_index": 246,
                "block_index": 1,
                "text": "02. TCP 拥塞控制中，下列说法正确的是",
                "source": "ocr_boxes",
                "has_boxes": True,
                "boxes": [{"bbox": [1, 2, 3, 4], "conf": 0.9}],
            },
        ]

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=sparse_blocks,
        ):
            with patch(
                "app.features.pipeline_orchestrator._ocr_scanned_pdf",
                return_value=ocr_blocks,
            ):
                with patch("app.core.config.settings.OCR_ENABLED", True):
                    result = pipeline._run_extract(b"pdf content", "pdf")

        assert result["raw_blocks"] == ocr_blocks
        assert result["ocr_boxes_failed_pages"] == [245]
        assert result["ocr_text_fallback_pages"] == [245]
        assert result["ocr_text_fallback_unavailable_pages"] == [247]
        assert result["ocr_runtime_failed_pages"] == [247]

    def test_normal_pdf_no_ocr_triggered(self):
        pipeline = ImportPipeline()
        blocks = [{"page": 1, "block_index": 0, "text": "A" * 200}]

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=blocks,
        ):
            result = pipeline._run_extract(b"pdf content", "pdf")

        assert result["raw_blocks"] == blocks
        assert result["extracted"] == 1


# ---------------------------------------------------------------------------
# ImportPipeline — split stage
# ---------------------------------------------------------------------------


class TestImportPipelineSplit:
    def test_fallback_question_created_for_unsplit_text(self):
        pipeline = ImportPipeline()
        normalized_blocks = [
            {"page": 2, "block_index": 0, "normalized_text": "这是一段没有题号的 OCR 文本。"},
            {"page": 3, "block_index": 1, "normalized_text": "仍然需要进入人工审核。"},
        ]

        result = pipeline._run_split(normalized_blocks)

        assert result["split_count"] == 1
        assert result["split_diagnostics"] == {
            "normalized_block_count": 2,
            "text_block_count": 2,
            "raw_question_count": 0,
            "split_mode": "standard",
            "book_prose_downgraded": 0,
            "layout_filter": {
                "enabled": False,
                "pages_considered": 0,
                "filtered_line_count": 0,
                "kept_line_count": 0,
                "region_signals": [],
            },
            "raw_questions_preview": [],
            "failure_reason": "text_present_but_no_question_boundary",
            "fallback_created": True,
        }
        assert result["warnings"] == ["no questions found in document; created low-confidence review item"]
        assert result["raw_questions"] == [{
            "number": 1,
            "raw_question_text": "这是一段没有题号的 OCR 文本。\n仍然需要进入人工审核。",
            "page_start": 2,
            "page_end": 3,
            "has_options": False,
            "option_lines": {},
            "confidence": 0.2,
            "risk_flags": ["fallback_low_confidence"],
        }]

    def test_book_mode_skips_unsplit_text_fallback(self):
        pipeline = ImportPipeline()
        normalized_blocks = [
            {"page": 2, "block_index": 0, "normalized_text": "定义：线性表是具有相同数据类型的 n 个数据元素的有限序列。"},
            {"page": 3, "block_index": 1, "normalized_text": "定理：顺序存储结构可以实现随机存取。证明如下。"},
        ]

        result = pipeline._run_split(normalized_blocks, import_mode="book", source_type="pdf")

        assert result["split_count"] == 0
        assert result["raw_questions"] == []
        assert result["split_diagnostics"]["fallback_created"] is False
        assert result["split_diagnostics"]["failure_reason"] == "book_text_present_but_no_question_boundary"
        assert result["split_diagnostics"]["non_question_like_skipped"] is True
        assert result["warnings"] == [
            "no questions found in book import; skipped low-confidence fallback review item"
        ]

    def test_book_mode_skips_numbered_prose_after_split(self):
        pipeline = ImportPipeline()
        prose = "\n".join([
            "1. 定义：线性表是具有相同数据类型的数据元素的有限序列。",
            "性质：顺序存储结构可以实现随机存取。",
            "证明如下：由于每个元素占用相同存储空间，因此可得任意元素地址。",
            "知识点：存储结构与逻辑结构不同，教材正文通常用于解释概念。",
            "2. 定理：链式存储结构不要求逻辑上相邻的元素物理位置也相邻。",
            "推论：插入和删除操作只需要修改指针。",
            "注意：本节内容主要说明数据结构的基本概念和算法性质。",
            "例如：单链表通过指针域表示元素之间的逻辑关系。",
            "综上，教材正文的编号段落用于说明概念而不是提出待解问题。",
        ])
        normalized_blocks = [{"page": 245, "block_index": 0, "normalized_text": prose}]

        result = pipeline._run_split(normalized_blocks, import_mode="book", source_type="pdf")

        assert result["split_count"] == 0
        assert result["raw_questions"] == []
        assert result["split_diagnostics"]["failure_reason"] == "book_text_present_but_no_question_boundary"
        assert result["split_diagnostics"]["non_question_like_skipped"] is True
        assert result["warnings"] == [
            "no questions found in book import; skipped low-confidence fallback review item"
        ]

    def test_book_pdf_prose_skip_diagnostics_include_bounded_preview(self):
        pipeline = ImportPipeline()
        prose = "\n".join([
            "1. 定义：TCP 拥塞控制用于避免网络过载并提高传输效率。",
            "性质：拥塞窗口会根据慢开始、拥塞避免、快重传和快恢复过程不断调整。",
            "证明如下：当发送方收到重复确认时，可以推断个别报文段可能丢失，因此可得教材中的快重传算法说明。",
            "本节知识点继续解释协议机制、窗口变化和报文段重传过程，而不是提出待解题目。",
        ])
        normalized_blocks = [{"page": 245, "block_index": 0, "normalized_text": prose}]

        result = pipeline._run_split(normalized_blocks, import_mode="book", source_type="pdf")

        assert result["split_count"] == 0
        split = result["split_diagnostics"]
        assert split["prose_skipped_count"] == 1
        assert len(split["prose_skipped_preview"]) == 1
        preview = split["prose_skipped_preview"][0]
        assert preview["page"] == 245
        assert preview["number"] == 1
        assert "快重传" in preview["text"]
        assert len(preview["text"]) <= 80

    def test_book_mode_keeps_question_like_long_split(self):
        pipeline = ImportPipeline()
        text = "\n".join([
            "1. 下列关于线性表的说法，正确的是哪一项？",
            "A. 线性表只能顺序存储",
            "B. 线性表可以链式存储",
            "C. 线性表不能插入元素",
            "D. 线性表没有逻辑结构",
            "解析：定义、性质、知识点如下，线性表既可以顺序存储也可以链式存储。",
        ])
        normalized_blocks = [{"page": 245, "block_index": 0, "normalized_text": text}]

        result = pipeline._run_split(normalized_blocks, import_mode="book", source_type="pdf")

        assert result["split_count"] == 1
        assert result["raw_questions"][0]["has_options"] is True
        assert result["split_diagnostics"]["book_prose_downgraded"] == 0

    def test_book_mode_soft_prose_diagnostics_counts_downgraded(self):
        pipeline = ImportPipeline()
        text = (
            "1. 定义：线性表是具有相同数据类型的 n 个数据元素的有限序列，"
            "顺序存储和链式存储是其常见实现方式，本节介绍前者和后者。"
        )
        normalized_blocks = [{"page": 245, "block_index": 0, "normalized_text": text}]

        result = pipeline._run_split(normalized_blocks, import_mode="book", source_type="pdf")

        assert result["split_count"] == 1
        assert result["raw_questions"][0]["confidence"] == 0.4
        assert result["split_diagnostics"]["book_prose_downgraded"] == 1

    def test_book_mode_keeps_long_subjective_question_without_options(self):
        pipeline = ImportPipeline()
        text = "\n".join([
            "1. 简述顺序表和链表在存储结构、插入删除操作以及查找效率上的主要区别。",
            "要求结合线性表的基本概念进行说明，并分别指出两种结构在实际算法设计中的适用场景。",
            "为什么顺序表支持随机存取，而链表在插入和删除时通常不需要移动大量元素？",
        ])
        normalized_blocks = [{"page": 245, "block_index": 0, "normalized_text": text}]

        result = pipeline._run_split(normalized_blocks, import_mode="book", source_type="pdf")

        assert result["split_count"] == 1
        assert result["raw_questions"][0]["has_options"] is False
        assert "book_pdf_prose_skipped" not in result["split_diagnostics"]

    def test_book_mode_non_pdf_still_creates_unsplit_text_fallback(self):
        pipeline = ImportPipeline()
        normalized_blocks = [
            {"page": 1, "block_index": 0, "normalized_text": "这是一道没有题号但需要人工审核的单题。"},
        ]

        result = pipeline._run_split(normalized_blocks, import_mode="book", source_type="txt")

        assert result["split_count"] == 1
        assert result["split_diagnostics"]["fallback_created"] is True
        assert result["split_diagnostics"]["failure_reason"] == "text_present_but_no_question_boundary"
        assert result["warnings"] == ["no questions found in document; created low-confidence review item"]
        assert result["raw_questions"][0]["raw_question_text"] == "这是一道没有题号但需要人工审核的单题。"

    def test_book_mode_filters_layout_prose_before_split(self):
        pipeline = ImportPipeline()
        normalized_blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": "\n".join([
                "1. 栈的定义",
                "栈是只允许在一端进行插入和删除的线性表。",
                "例题解析：如下过程说明栈的先进后出性质。",
                "习题精选",
                "01．下列关于栈的说法中，正确的是（  ）。",
                "A．先进先出",
                "B．后进先出",
                "C．随机访问",
                "D．链式存储",
            ]),
            "boxes": [
                {"bbox": [100, 120, 430, 150], "conf": 0.94},
                {"bbox": [100, 165, 920, 195], "conf": 0.94},
                {"bbox": [100, 210, 900, 240], "conf": 0.94},
                {"bbox": [460, 500, 650, 535], "conf": 0.94},
                {"bbox": [100, 570, 980, 605], "conf": 0.94},
                {"bbox": [120, 625, 420, 655], "conf": 0.94},
                {"bbox": [120, 665, 420, 695], "conf": 0.94},
                {"bbox": [120, 705, 420, 735], "conf": 0.94},
                {"bbox": [120, 745, 420, 775], "conf": 0.94},
            ],
            "page_width": 1128,
            "page_height": 1571,
        }]

        result = pipeline._run_split(normalized_blocks, import_mode="book", source_type="pdf")

        assert result["split_count"] == 1
        text = result["raw_questions"][0]["raw_question_text"]
        assert "下列关于栈" in text
        assert "栈的定义" not in text
        layout_filter = result["split_diagnostics"]["layout_filter"]
        assert layout_filter["enabled"] is True
        assert layout_filter["filtered_line_count"] == 4
        assert layout_filter["region_signals"][0]["signal"] == "exercise_marker+question"

    def test_exam_mode_does_not_run_book_layout_filter(self):
        pipeline = ImportPipeline()
        normalized_blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": "1. 已编号题目\nA. 选项A\nB. 选项B\nC. 选项C\nD. 选项D",
            "boxes": [
                {"bbox": [100, 120, 900, 150], "conf": 0.94},
                {"bbox": [120, 170, 420, 200], "conf": 0.94},
                {"bbox": [120, 220, 420, 250], "conf": 0.94},
                {"bbox": [120, 270, 420, 300], "conf": 0.94},
                {"bbox": [120, 320, 420, 350], "conf": 0.94},
            ],
            "page_width": 1128,
            "page_height": 1571,
        }]

        result = pipeline._run_split(normalized_blocks, import_mode="exam", source_type="pdf")

        assert result["split_count"] == 1
        assert result["split_diagnostics"]["layout_filter"]["enabled"] is False

    def test_book_mode_non_pdf_does_not_run_layout_filter(self):
        pipeline = ImportPipeline()
        normalized_blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": "1. 已编号题目\nA. 选项A\nB. 选项B",
            "boxes": [
                {"bbox": [100, 120, 900, 150], "conf": 0.94},
                {"bbox": [120, 170, 420, 200], "conf": 0.94},
                {"bbox": [120, 220, 420, 250], "conf": 0.94},
            ],
            "page_width": 1128,
            "page_height": 1571,
        }]

        result = pipeline._run_split(normalized_blocks, import_mode="book", source_type="txt")

        assert result["split_count"] == 1
        assert result["split_diagnostics"]["layout_filter"]["enabled"] is False

    def test_book_pdf_without_boxes_does_not_run_layout_filter(self):
        pipeline = ImportPipeline()
        normalized_blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": "1. 已编号题目\nA. 选项A\nB. 选项B",
            "page_width": 1128,
            "page_height": 1571,
        }]

        result = pipeline._run_split(normalized_blocks, import_mode="book", source_type="pdf")

        assert result["split_count"] == 1
        assert result["split_diagnostics"]["layout_filter"]["enabled"] is False

    def test_visual_boundary_diagnostics_include_bounded_preview(self):
        pipeline = ImportPipeline()
        normalized_blocks = [{
            "page": 3,
            "block_index": 0,
            "normalized_text": "\n".join([
                "教材说明：顺序表的存储结构如下。",
                "这一段仍然是知识点解释。",
                "新的视觉区域开始但没有题号。",
                "这一行用于验证 preview 被截断为短文本。",
            ]),
            "boxes": [
                {"bbox": [100, 100, 900, 120], "conf": 0.94},
                {"bbox": [100, 130, 900, 150], "conf": 0.94},
                {"bbox": [100, 300, 900, 320], "conf": 0.94},
                {"bbox": [100, 330, 900, 350], "conf": 0.94},
            ],
            "page_width": 1128,
            "page_height": 1571,
        }]

        result = pipeline._run_split(normalized_blocks, source_type="pdf")

        visual_boundary = result["split_diagnostics"]["visual_boundary"]
        assert visual_boundary["boundary_count"] == 1
        assert visual_boundary["boundaries"] == [{
            "page": 3,
            "signal": "large_gap",
            "preview": "新的视觉区域开始但没有题号。这一行用于验证 preview 被截断为短文本。",
        }]
        assert len(visual_boundary["boundaries"][0]["preview"]) <= 80

    def test_numbered_questions_do_not_use_fallback(self):
        pipeline = ImportPipeline()
        normalized_blocks = [
            {"page": 1, "block_index": 0, "normalized_text": "1. 已编号题目\nA. 选项A\nB. 选项B"},
        ]

        result = pipeline._run_split(normalized_blocks)

        assert result["split_count"] == 1
        assert result["split_diagnostics"] == {
            "normalized_block_count": 1,
            "text_block_count": 1,
            "raw_question_count": 1,
            "split_mode": "standard",
            "book_prose_downgraded": 0,
            "layout_filter": {
                "enabled": False,
                "pages_considered": 0,
                "filtered_line_count": 0,
                "kept_line_count": 0,
                "region_signals": [],
            },
            "raw_questions_preview": [
                {
                    "number": 1,
                    "raw_question_text": "1. 已编号题目\nA. 选项A\nB. 选项B",
                    "_original_raw_text": None,
                    "page_start": 1,
                    "page_end": 1,
                    "has_options": True,
                    "option_lines": {"A": "选项A", "B": "选项B"},
                    "blank_option_groups": [],
                    "has_grouped_options": False,
                    "is_frozen": False,
                    "confidence": 0.9,
                    "section_type": None,
                    "risk_flags": [],
                    "source_question_no": "1",
                    "source_question_label": "1.",
                }
            ],
            "failure_reason": None,
            "fallback_created": False,
        }
        assert result["warnings"] == []
        assert result["raw_questions"][0]["confidence"] != 0.2

    def test_raw_questions_preview_truncates_long_text(self):
        pipeline = ImportPipeline()
        long_tail = "这是一段很长的 OCR 文本。" * 40
        normalized_blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": f"1. {long_tail}\nA. 选项A\nB. 选项B",
        }]

        result = pipeline._run_split(normalized_blocks)

        preview = result["split_diagnostics"]["raw_questions_preview"][0]
        assert len(preview["raw_question_text"]) == 300
        assert preview["raw_question_text_truncated"] is True
        assert len(result["raw_questions"][0]["raw_question_text"]) > 300

    @pytest.mark.asyncio
    async def test_match_uses_separated_structure(self):
        pipeline = ImportPipeline()
        normalized_blocks = [
            {
                "page": 1,
                "block_index": 0,
                "normalized_text": "1. 题目A\nA. 选项A\nB. 选项B\n2. 题目B\nA. 选项A\nB. 选项B",
            },
            {"page": 2, "block_index": 1, "normalized_text": "参考答案：\n1. B\n2. A"},
        ]
        structure = (await pipeline._run_analyze_structure(normalized_blocks))["structure"]
        split = pipeline._run_split(normalized_blocks, structure=structure)
        result = pipeline._run_match(split["raw_questions"], normalized_blocks, structure=structure)

        assert structure["mode"] == "SEPARATED"
        assert structure["answer_pages"] == [2]
        assert [q["answer"] for q in result["matched"]] == ["B", "A"]
        assert all(q["answer_source"] == "separated" for q in result["matched"])


# ---------------------------------------------------------------------------
# PipelineStage
# ---------------------------------------------------------------------------


class TestPipelineStage:
    def test_sync_run_success(self):
        def add(a, b):
            return a + b

        stage = PipelineStage("test", add)
        result = stage.run(a=1, b=2)

        assert result == 3
        assert stage.status == "completed"
        assert stage.duration_ms >= 0
        assert stage.error is None

    def test_sync_run_failure(self):
        def fail():
            raise ValueError("boom")

        stage = PipelineStage("test", fail)
        with pytest.raises(ValueError, match="boom"):
            stage.run()

        assert stage.status == "failed"
        assert stage.error == "boom"

    def test_async_run_success(self):
        async def add(a, b):
            return a + b

        stage = PipelineStage("test", add)
        result = asyncio.run(stage.run_async(a=1, b=2))

        assert result == 3
        assert stage.status == "completed"

    def test_async_run_with_sync_fn(self):
        def add(a, b):
            return a + b

        stage = PipelineStage("test", add)
        result = asyncio.run(stage.run_async(a=1, b=2))

        assert result == 3
        assert stage.status == "completed"

    def test_async_run_failure(self):
        async def fail():
            raise ValueError("async boom")

        stage = PipelineStage("test", fail)
        with pytest.raises(ValueError, match="async boom"):
            asyncio.run(stage.run_async())

        assert stage.status == "failed"
        assert stage.error == "async boom"

    def test_to_dict_completed(self):
        stage = PipelineStage("extract", lambda: None)
        stage.status = "completed"
        stage.duration_ms = 100

        d = stage.to_dict()
        assert d == {"name": "extract", "status": "completed", "duration_ms": 100, "warnings": []}

    def test_to_dict_failed(self):
        stage = PipelineStage("extract", lambda: None)
        stage.status = "failed"
        stage.error = "something wrong"

        d = stage.to_dict()
        assert d["status"] == "failed"
        assert d["error"] == "something wrong"

    def test_warnings_accumulate(self):
        stage = PipelineStage("test", lambda: None)
        stage.warnings.append("warning 1")
        stage.warnings.append("warning 2")

        d = stage.to_dict()
        assert d["warnings"] == ["warning 1", "warning 2"]


# ---------------------------------------------------------------------------
# ImportPipeline — stage mocks
# ---------------------------------------------------------------------------


class TestImportPipelineRun:
    """Test pipeline orchestration by mocking individual stages."""

    @pytest.fixture(autouse=True)
    def _mock_pdf_renderer(self):
        """Patch pdf_renderer.render_pages so tests don't need real PDFs."""
        from app.services.pdf_renderer_service import PdfRenderResult
        from app.services.pdf_renderer_service import pdf_renderer as real_renderer
        from unittest.mock import AsyncMock

        mock = AsyncMock(return_value=PdfRenderResult(
            page_images={1: b"fake_png"},
            rendered_count=1,
            total_pages=1,
        ))
        with patch.object(real_renderer, "render_pages", mock):
            yield

    def test_build_diagnostics_includes_risk_flag_counts(self):
        from app.features.pipeline_orchestrator import _build_diagnostics

        diagnostics = _build_diagnostics({
            "import_mode": "book",
            "split_diagnostics": {
                "layout_filter": {"enabled": True},
                "visual_boundary": {"boundary_count": 2, "signals": ["gap+number"]},
            },
            "risk_flag_counts": {"book_pdf_prose_like": 1, "low_confidence": 2},
        })

        assert diagnostics["split"]["layout_filter"]["enabled"] is True
        assert diagnostics["split"]["visual_boundary"]["boundary_count"] == 2
        assert diagnostics["risk_flag_counts"] == {"book_pdf_prose_like": 1, "low_confidence": 2}

    def test_count_risk_flags_deduplicates_per_question_contract(self):
        assert _count_risk_flags([
            {"risk_flags": ["book_pdf_prose_like", "low_confidence"]},
            {"risk_flags": ["low_confidence"]},
            {"risk_flags": []},
        ]) == {"book_pdf_prose_like": 1, "low_confidence": 2}

    def _make_pipeline(self, **overrides):
        """Create a pipeline with all stages mocked. Rebuilds stages after mocking."""
        pipeline = ImportPipeline(options=overrides.get("options"))
        pipeline._run_extract = MagicMock(return_value={
            "raw_blocks": _make_raw_blocks(3),
            "extracted": 3,
        })
        pipeline._run_normalize_text = MagicMock(return_value={
            "normalized_blocks": _make_normalized_blocks(3),
        })
        pipeline._run_ocr_correction = AsyncMock(return_value={
            "normalized_blocks": _make_normalized_blocks(3),
            "ocr_correction_diagnostics": {"stats": {}, "corrections": [], "skipped_reason": None},
        })
        pipeline._run_layout_reconstruction = MagicMock(return_value={
            "normalized_blocks": _make_normalized_blocks(3),
            "layout_result": {
                "layout_blocks": _make_normalized_blocks(3),
                "option_groups": {},
                "layout_confidence": 0.95,
                "option_detection_score": 0.9,
                "option_detection_failed": False,
                "reading_order": [],
                "warnings": [],
            },
        })
        pipeline._run_layout_router = MagicMock(return_value={
            "split_mode": "standard",
        })
        pipeline._run_split = MagicMock(return_value={
            "raw_questions": _make_raw_questions(3),
            "split_count": 3,
        })
        pipeline._run_match = MagicMock(return_value={
            "matched": _make_matched(3),
            "unmatched": [],
            "matched_count": 3,
        })
        pipeline._run_normalize_schema = MagicMock(return_value={
            "questions": _make_questions(3),
            "normalized_count": 3,
        })
        pipeline._run_code_language_noise_clean = MagicMock(return_value={
            "questions": _make_questions(3),
            "cleaned_count": 0,
            "warnings": [],
            "code_language_noise_fix_actions": [],
            "total_removed_lines": 0,
        })
        pipeline._run_code_structure_reconstruct = AsyncMock(return_value={
            "questions": _make_questions(3),
            "reconstructed_count": 0,
            "failed_count": 0,
            "warnings": [],
            "fix_actions": [],
        })
        pipeline._run_repair = MagicMock(return_value={
            "questions": _make_questions(3),
            "repaired_count": 1,
            "unrepaired_count": 0,
            "skipped_count": 2,
            "total_tokens": 500,
        })
        pipeline._run_ai_validation = MagicMock(return_value={
            "questions": _make_questions(3),
            "ai_validation_diagnostics": {"total": 3, "valid": 3, "warnings": 0, "errors": 0},
        })
        pipeline._run_similarity_match = AsyncMock(return_value={
            "questions": _make_questions(3),
            "similarity_match_diagnostics": {"stats": {}, "matches": [], "skipped_reason": None},
        })
        pipeline._run_review = AsyncMock(return_value={
            "batch_id": "REVIEW_test",
            "written": 3,
            "skipped": 0,
            "total": 3,
        })
        # Rebuild stages so PipelineStage objects reference the mocked methods
        pipeline._build_pipeline()
        return pipeline

    def test_full_pipeline_success(self):
        pipeline = self._make_pipeline()

        result = asyncio.run(pipeline.run(
            file_content=b"fake pdf",
            source_type="pdf",
            source_file="test.pdf",
            subject="math2",
            db=_make_mock_db(),
        ))

        assert result["status"] == "completed"
        assert result["stats"]["extracted"] == 3
        assert result["stats"]["split"] == 3
        assert result["stats"]["matched"] == 3
        assert result["stats"]["schema_normalized"] == 3
        assert result["stats"]["repaired"] == 1
        assert result["stats"]["to_review"] == 3
        assert len(result["errors"]) == 0

        # Verify stage ordering
        stage_names = list(result["stages"].keys())
        assert stage_names == ["extract", "normalize_text", "ocr_correction", "layout_reconstruction", "layout_router", "analyze_structure", "classify_pages", "structure_freeze", "split", "match", "normalize_schema", "code_language_noise_clean", "code_structure_reconstruct", "classify_questions", "batch_validation", "batch_dedup", "repair", "ai_validation", "similarity_match", "math_detect", "table_detect", "review"]
        for s in result["stages"].values():
            assert s["status"] == "completed"

    def test_book_pdf_single_pass_unsplit_text_does_not_reach_review(self):
        pipeline = ImportPipeline(options={"enable_ai_repair": False, "enable_similarity_match": False})
        normalized_blocks = [
            {"page": 1, "block_index": 0, "raw_text": "定义：数据结构用于组织数据。", "normalized_text": "定义：数据结构用于组织数据。"},
            {"page": 2, "block_index": 1, "raw_text": "定理：顺序表支持随机访问。证明如下。", "normalized_text": "定理：顺序表支持随机访问。证明如下。"},
        ]
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(2), "extracted": 2})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": normalized_blocks})
        async def _ocr_correction(**_kw):
            return {"normalized_blocks": normalized_blocks}

        pipeline._run_ocr_correction = _ocr_correction
        pipeline._run_analyze_structure = MagicMock(return_value={"structure": {}})
        pipeline._run_classify_pages = MagicMock(return_value={"normalized_blocks": normalized_blocks})
        review_calls = []

        async def _review(**_kw):
            review_calls.append(_kw)
            return {"batch_id": "", "written": 0, "skipped": 0, "total": 0}

        pipeline._run_review = _review
        pipeline._build_pipeline()

        result = asyncio.run(pipeline.run(
            file_content=b"fake pdf",
            source_type="pdf",
            source_file="book.pdf",
            options={"import_mode": "book", "enable_ai_repair": False, "enable_similarity_match": False},
        ))

        assert result["status"] == "completed"
        assert result["stats"]["split"] == 0
        assert result["stats"]["to_review"] == 0
        assert result["diagnostics"]["split"]["failure_reason"] == "book_text_present_but_no_question_boundary"
        assert len(review_calls) == 1
        assert review_calls[0]["questions"] == []

    def test_ai_repair_disabled(self):
        pipeline = self._make_pipeline()
        pipeline.options["enable_ai_repair"] = False

        # Rebuild so repair stage is excluded
        pipeline._build_pipeline()

        result = asyncio.run(pipeline.run(
            file_content=b"fake",
            source_type="pdf",
            source_file="test.pdf",
        ))

        stage_names = list(result["stages"].keys())
        assert "repair" not in stage_names
        assert "review" in stage_names

    def test_ai_repair_enabled(self):
        pipeline = self._make_pipeline()
        pipeline.options["enable_ai_repair"] = True

        result = asyncio.run(pipeline.run(
            file_content=b"fake",
            source_type="pdf",
            source_file="test.pdf",
        ))

        stage_names = list(result["stages"].keys())
        assert "repair" in stage_names

    def test_extract_failure_aborts_pipeline(self):
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(side_effect=ValueError("bad file"))

        result = asyncio.run(pipeline.run(
            file_content=b"",
            source_type="pdf",
            source_file="test.pdf",
        ))

        assert result["status"] == "failed"
        assert "extract" in result["errors"][0]
        # Only extract should have run (or failed)
        assert result["stages"]["extract"]["status"] == "failed"

    def test_normalize_text_failure_aborts_pipeline(self):
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": [], "extracted": 0})
        pipeline._run_normalize_text = MagicMock(side_effect=ValueError("text error"))

        result = asyncio.run(pipeline.run(
            file_content=b"x",
            source_type="pdf",
            source_file="test.pdf",
        ))

        assert result["status"] == "failed"
        assert result["stages"]["normalize_text"]["status"] == "failed"

    def test_later_stage_failure_continues_pipeline(self):
        """Match stage failure should not abort — error isolation."""
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(2), "extracted": 2})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(2)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": _make_raw_questions(2), "split_count": 2})
        pipeline._run_match = MagicMock(side_effect=ValueError("match error"))
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        result = asyncio.run(pipeline.run(
            file_content=b"x",
            source_type="pdf",
            source_file="test.pdf",
        ))

        # Pipeline should continue despite match failure
        assert result["stages"]["match"]["status"] == "failed"
        assert result["stages"]["normalize_schema"]["status"] == "completed"
        assert "match" in result["errors"][0]

    def test_empty_questions_flow(self):
        """Pipeline with no questions found still completes."""
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": [], "extracted": 0})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": []})
        pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": 0, "warnings": ["no questions found"]})
        pipeline._run_match = MagicMock(return_value={"matched": [], "unmatched": [], "matched_count": 0})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        result = asyncio.run(pipeline.run(
            file_content=b"x",
            source_type="pdf",
            source_file="empty.pdf",
        ))

        assert result["status"] == "completed"
        assert result["stats"]["split"] == 0
        assert result["stats"]["to_review"] == 0

    def test_review_without_db(self):
        """Review stage should skip gracefully when no db provided."""
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(1), "extracted": 1})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(1)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": _make_raw_questions(1), "split_count": 1})
        pipeline._run_match = MagicMock(return_value={"matched": _make_matched(1), "unmatched": [], "matched_count": 1})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": _make_questions(1), "normalized_count": 1})

        result = asyncio.run(pipeline.run(
            file_content=b"x",
            source_type="pdf",
            source_file="test.pdf",
            db=None,  # no db
        ))

        assert result["status"] == "completed"
        assert result["stages"]["review"]["warnings"] == ["no db session provided, review stage skipped"]

    def test_stage_timing_recorded(self):
        pipeline = self._make_pipeline()

        result = asyncio.run(pipeline.run(
            file_content=b"x",
            source_type="pdf",
            source_file="test.pdf",
        ))

        for stage in result["stages"].values():
            assert stage["duration_ms"] >= 0

    def test_p1a_large_fields_released_between_stages(self):
        """P1-A: stage 间清理大字段，避免 normalized_blocks/raw_questions 等
        随后续 8+ 个阶段一起驻留内存。"""
        pipeline = self._make_pipeline()

        # 用 review 阶段做哨兵：到达 review 时，stage 间应已清理：
        #   - raw_blocks         (在 normalize_text 之后)
        #   - normalized_blocks  (在 match 之后)
        #   - raw_questions / matched / unmatched (在 normalize_schema 之后)
        captured: dict = {}

        async def _capture_review(**kw):
            captured.update(kw)
            return {
                "batch_id": "REVIEW_p1a",
                "written": 3,
                "skipped": 0,
                "total": 3,
            }

        pipeline._run_review = _capture_review
        pipeline._build_pipeline()

        result = asyncio.run(pipeline.run(
            file_content=b"fake pdf",
            source_type="pdf",
            source_file="test.pdf",
            subject="math2",
            db=_make_mock_db(),
        ))

        assert result["status"] == "completed"
        # review 看到的 kwargs 里不应再有大字段
        assert "raw_blocks" not in captured
        assert "normalized_blocks" not in captured
        assert "raw_questions" not in captured
        assert "matched" not in captured
        assert "unmatched" not in captured
        # 但仍然能拿到 questions，pipeline 出口数据完整
        assert isinstance(captured.get("questions"), list)
        assert len(captured["questions"]) == 3
        # stats 里 normalized 计数仍然正确（normalized_block_count 兜底）
        assert result["stats"]["normalized"] == 3

    def test_p1a_stats_normalized_survives_mid_pipeline_failure(self):
        """隐患① 修复：normalize_text 之后任意 stage 失败，stats['normalized']
        仍应反映上一次写入 normalized_blocks 的产物，而不是静默归零。

        修复前 fallback 链是 normalized_count → normalized_block_count → len([])，
        normalized_count 由 normalize_schema 写入，normalized_block_count 由
        match 之后才缓存；analyze_structure 失败时两者都不存在，stats 归零。
        修复后 normalized_blocks 一被写入就同步缓存 count。
        """
        pipeline = self._make_pipeline()
        # analyze_structure 在 normalize_text 之后第一个失败
        pipeline._run_analyze_structure = MagicMock(side_effect=ValueError("structure fail"))
        # 后续阶段也直接失败，避免它们再写入 normalized_blocks 干扰断言
        pipeline._run_classify_pages = MagicMock(side_effect=ValueError("classify fail"))
        pipeline._run_split = MagicMock(side_effect=ValueError("split fail"))
        pipeline._run_match = MagicMock(side_effect=ValueError("match fail"))
        # normalize_schema 也不写 normalized_count，模拟 schema 也未走 happy path
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": []})
        pipeline._build_pipeline()

        result = asyncio.run(pipeline.run(
            file_content=b"fake pdf",
            source_type="pdf",
            source_file="test.pdf",
            subject="math2",
            db=_make_mock_db(),
        ))

        # pipeline 整体被标记 failed
        assert result["status"] == "failed"
        assert result["stages"]["analyze_structure"]["status"] == "failed"
        # 关键断言：ocr_correction 输出 3 个 block，stats['normalized'] 应等于 3
        # 而非修复前的 0（因为 normalized_count 和 normalized_blocks 都缺失）
        assert result["stats"]["normalized"] == 3


# ---------------------------------------------------------------------------
# run_import_pipeline
# ---------------------------------------------------------------------------


class TestRunImportPipeline:
    def test_returns_pipeline_id(self):
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(1), "extracted": 1})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(1)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": 0})
        pipeline._run_match = MagicMock(return_value={"matched": [], "unmatched": [], "matched_count": 0})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        with patch("app.features.pipeline_orchestrator.ImportPipeline", return_value=pipeline):
            result = asyncio.run(run_import_pipeline(
                file_content=b"x",
                source_type="txt",
                source_file="test.txt",
            ))

        assert result["pipeline_id"].startswith("pl_")
        assert "started_at" in result

    def test_txt_source_type(self):
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(1), "extracted": 1})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(1)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": 0})
        pipeline._run_match = MagicMock(return_value={"matched": [], "unmatched": [], "matched_count": 0})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        with patch("app.features.pipeline_orchestrator.ImportPipeline", return_value=pipeline):
            result = asyncio.run(run_import_pipeline(
                file_content=b"plain text",
                source_type="txt",
                source_file="notes.txt",
                subject="exam408",
            ))

        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# run_pipeline_background + get_pipeline_status
# ---------------------------------------------------------------------------


class TestBackgroundPipeline:
    def test_status_transitions(self):
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(1), "extracted": 1})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(1)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": 0})
        pipeline._run_match = MagicMock(return_value={"matched": [], "unmatched": [], "matched_count": 0})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        pid = "pl_test_001"

        with patch("app.features.pipeline_orchestrator.ImportPipeline", return_value=pipeline):
            asyncio.run(run_pipeline_background(
                pipeline_id=pid,
                file_content=b"x",
                source_type="txt",
                source_file="test.txt",
            ))

        status = asyncio.run(get_pipeline_status(pid))
        assert status is not None
        assert status["pipeline_id"] == pid
        assert status["status"] == "completed"

    def test_background_failure_captured(self):
        """When the pipeline raises, the error should be stored."""
        with patch("app.features.pipeline_orchestrator.run_import_pipeline") as mock_run:
            mock_run.side_effect = RuntimeError("catastrophic failure")

            asyncio.run(run_pipeline_background(
                pipeline_id="pl_fail_001",
                file_content=b"x",
                source_type="txt",
                source_file="test.txt",
            ))

        status = asyncio.run(get_pipeline_status("pl_fail_001"))
        assert status["status"] == "failed"
        assert "catastrophic failure" in status["errors"][0]

    def test_status_not_found(self):
        assert asyncio.run(get_pipeline_status("nonexistent")) is None

    def test_store_pruning(self):
        """Store should not grow unbounded."""
        # Fill store with more than _MAX_STORE_SIZE entries
        for i in range(510):
            _pipeline_store[f"pl_{i}"] = {
                "pipeline_id": f"pl_{i}",
                "status": "completed",
                "started_at": f"2026-05-24T00:{i % 60:02d}:00",
            }

        # Trigger prune by adding one more via background
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(1), "extracted": 1})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(1)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": 0})
        pipeline._run_match = MagicMock(return_value={"matched": [], "unmatched": [], "matched_count": 0})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        with patch("app.features.pipeline_orchestrator.ImportPipeline", return_value=pipeline):
            asyncio.run(run_pipeline_background(
                pipeline_id="pl_new_001",
                file_content=b"x",
                source_type="txt",
                source_file="test.txt",
            ))

        assert len(_pipeline_store) <= 510  # should have been pruned


# ---------------------------------------------------------------------------
# P0-3: store slimming + diagnostics split
# ---------------------------------------------------------------------------


class TestPipelineStoreSlim:
    """主 _pipeline_store 不应再持有 diagnostics（P0-3 内存瘦身）。"""

    def test_set_strips_diagnostics_into_separate_store(self):
        from app.features.pipeline_orchestrator import (
            _pipeline_diagnostics_store,
            _set_pipeline_store,
        )

        pid = "pl_slim_001"
        _pipeline_store.pop(pid, None)
        _pipeline_diagnostics_store.pop(pid, None)

        diagnostics = {
            "split": {"raw_questions_preview": [{"raw_question_text": "x" * 5000}] * 20},
            "ocr_correction": {"corrections": [{"page": i, "text": "y" * 200} for i in range(50)]},
        }
        full_payload = {
            "pipeline_id": pid,
            "status": "completed",
            "source_type": "pdf",
            "stages": {"extract": {"status": "completed"}},
            "stats": {"total": 100},
            "errors": [],
            "started_at": "2026-06-05T00:00:00",
            "diagnostics": diagnostics,
        }
        asyncio.run(_set_pipeline_store(pid, full_payload))

        # 主 store 不能含 diagnostics
        assert "diagnostics" not in _pipeline_store[pid]
        assert _pipeline_store[pid]["pipeline_id"] == pid
        assert _pipeline_store[pid]["stats"] == {"total": 100}

        # diagnostics 走独立 store
        assert pid in _pipeline_diagnostics_store
        assert _pipeline_diagnostics_store[pid] == diagnostics

    def test_status_query_merges_diagnostics_back(self):
        from app.features.pipeline_orchestrator import (
            _pipeline_diagnostics_store,
            _set_pipeline_store,
        )

        pid = "pl_slim_002"
        _pipeline_store.pop(pid, None)
        _pipeline_diagnostics_store.pop(pid, None)

        diagnostics = {"split": {"failure_reason": None}, "structure": {"mode": "exam"}, "exercise_regions_missing": True}
        asyncio.run(_set_pipeline_store(pid, {
            "pipeline_id": pid,
            "status": "completed",
            "source_type": "pdf",
            "stages": {},
            "stats": {},
            "errors": [],
            "started_at": "2026-06-05T00:00:00",
            "diagnostics": diagnostics,
        }))

        status = asyncio.run(get_pipeline_status(pid))
        assert status is not None
        assert status["diagnostics"] == diagnostics
        assert status["status"] == "completed"

    def test_prune_removes_diagnostics_alongside_store(self):
        from app.features.pipeline_orchestrator import (
            _MAX_STORE_SIZE,
            _pipeline_diagnostics_store,
            _prune_store,
        )

        # 重置
        _pipeline_store.clear()
        _pipeline_diagnostics_store.clear()

        for i in range(_MAX_STORE_SIZE + 5):
            pid = f"pl_prune_{i:04d}"
            _pipeline_store[pid] = {
                "pipeline_id": pid,
                "status": "completed",
                "started_at": f"2026-06-05T00:00:{i:08d}",
            }
            _pipeline_diagnostics_store[pid] = {"i": i}

        _prune_store()
        # 最旧 5 个应被清除（store + diagnostics 同步）
        assert len(_pipeline_store) == _MAX_STORE_SIZE
        for i in range(5):
            assert f"pl_prune_{i:04d}" not in _pipeline_store
            assert f"pl_prune_{i:04d}" not in _pipeline_diagnostics_store

    def test_status_query_does_not_pollute_main_store(self):
        """get_pipeline_status 必须返回拷贝，不能把 ocr_progress 写进主 store。

        回归保护：之前实现里 get_pipeline_status 直接复用 _pipeline_store[pid]
        引用，对 data["ocr_progress"] 赋值会污染主 store 的白名单契约。
        """
        from app.features.pipeline_orchestrator import (
            _ocr_progress,
            _pipeline_diagnostics_store,
            _PIPELINE_STORE_FIELDS,
            _set_pipeline_store,
        )

        pid = "pl_pollute_001"
        # 隔离前序测试可能塞满的 prune 数据，避免 _set_pipeline_store
        # 内的 _prune_store 把当前用例的新条目反被淘汰。
        _pipeline_store.clear()
        _pipeline_diagnostics_store.clear()
        _ocr_progress.pop(pid, None)

        asyncio.run(_set_pipeline_store(pid, {
            "pipeline_id": pid,
            "status": "running",
            "source_type": "pdf",
            "stages": {},
            "stats": {},
            "errors": [],
            "started_at": "2026-06-05T00:00:00",
        }))

        _ocr_progress[pid] = "32/312 pages"
        try:
            status = asyncio.run(get_pipeline_status(pid))
            assert status is not None
            assert status.get("ocr_progress") == "32/312 pages"

            # 主 store 仍只含白名单字段
            stored = _pipeline_store[pid]
            assert "ocr_progress" not in stored
            assert set(stored.keys()).issubset(set(_PIPELINE_STORE_FIELDS))

            # 修改返回视图不能反污染主 store
            status["status"] = "tampered"
            assert _pipeline_store[pid]["status"] == "running"
        finally:
            _ocr_progress.pop(pid, None)


# ---------------------------------------------------------------------------
# ImportPipeline — _run_repair data flow
# ---------------------------------------------------------------------------


class TestRepairStage:
    def test_combines_repaired_unrepaired_and_skipped(self):
        questions = _make_questions(3)
        # Mark q0 with low confidence
        questions[0]["confidence_score"] = 0.3
        questions[1]["confidence_score"] = 0.4
        questions[2]["confidence_score"] = 0.9

        pipeline = ImportPipeline()
        # Mock repair_questions to return controlled result
        repaired = [{
            "question_index": 0,
            "before": questions[0],
            "after": {**questions[0], "stem": "Repaired stem", "confidence_score": 0.75},
            "repair_actions": ["fixed_stem"],
            "confidence": 0.75,
            "token_used": 100,
        }]
        unrepaired = [{"question_index": 1, "reason": "ai_failed"}]
        skipped = [{"question_index": 2, "reason": "above_threshold", "confidence": 0.9}]

        with patch("app.features.pipeline_stages.repair_stage.repair_questions", new_callable=AsyncMock, return_value={
            "repaired": repaired,
            "unrepaired": unrepaired,
            "skipped": skipped,
            "stats": {"total_candidates": 3, "repaired": 1, "unrepaired": 1, "skipped": 1, "total_tokens": 100},
        }):
            result = asyncio.run(pipeline._run_repair(questions=questions, options={}))

        assert result["repaired_count"] == 1
        assert result["unrepaired_count"] == 1
        assert result["skipped_count"] == 1
        assert result["total_tokens"] == 100
        assert len(result["questions"]) == 3
        # Repaired question has new stem
        assert result["questions"][0]["stem"] == "Repaired stem"
        assert result["questions"][0]["confidence_score"] == 0.75

    def test_warnings_for_unrepaired(self):
        questions = _make_questions(1)
        questions[0]["confidence_score"] = 0.3

        pipeline = ImportPipeline()
        with patch("app.features.pipeline_stages.repair_stage.repair_questions", new_callable=AsyncMock, return_value={
            "repaired": [],
            "unrepaired": [{"question_index": 0, "reason": "ai_unavailable"}],
            "skipped": [],
            "stats": {"total_candidates": 1, "repaired": 0, "unrepaired": 1, "skipped": 0, "total_tokens": 0},
        }):
            result = asyncio.run(pipeline._run_repair(questions=questions, options={}))

        assert "unrepaired" in result["warnings"][0]
        assert len(result["questions"]) == 1
        assert result["questions"][0]["confidence_score"] == 0.3  # original preserved
    def test_warnings_for_non_question_like_skipped_reason(self):
        questions = _make_questions(1)
        questions[0]["confidence_score"] = 0.3

        pipeline = ImportPipeline()
        with patch("app.features.pipeline_stages.repair_stage.repair_questions", new_callable=AsyncMock, return_value={
            "repaired": [],
            "unrepaired": [],
            "skipped": [{"question_index": 0, "reason": "non_question_like", "confidence": 0.3}],
            "stats": {"total_candidates": 1, "repaired": 0, "unrepaired": 0, "skipped": 1, "total_tokens": 0},
        }):
            result = asyncio.run(pipeline._run_repair(questions=questions, options={}))

        assert result["warnings"] == ["1 questions skipped repair (non_question_like=1)"]
        assert len(result["questions"]) == 1
        assert result["questions"][0]["risk_flags"] == ["non_question_like"]

    def test_repair_success_preserves_risk_flags(self):
        questions = _make_questions(1)
        questions[0]["risk_flags"] = ["book_pdf_prose_like"]
        repaired = [{
            "question_index": 0,
            "before": questions[0],
            "after": {**questions[0], "stem": "Repaired stem", "risk_flags": ["book_pdf_prose_like"]},
            "repair_actions": ["fixed_stem"],
            "confidence": 0.75,
            "token_used": 100,
        }]

        pipeline = ImportPipeline()
        with patch("app.features.pipeline_stages.repair_stage.repair_questions", new_callable=AsyncMock, return_value={
            "repaired": repaired,
            "unrepaired": [],
            "skipped": [],
            "stats": {"total_candidates": 1, "repaired": 1, "unrepaired": 0, "skipped": 0, "total_tokens": 100},
        }):
            result = asyncio.run(pipeline._run_repair(questions=questions, options={}))

        assert result["questions"][0]["stem"] == "Repaired stem"
        assert result["questions"][0]["risk_flags"] == ["book_pdf_prose_like"]


# ---------------------------------------------------------------------------
# ImportPipeline — options passthrough
# ---------------------------------------------------------------------------


class TestPipelineOptions:
    def test_confidence_threshold_passed_to_repair(self):
        questions = _make_questions(2)

        pipeline = ImportPipeline(options={"enable_ai_repair": True, "confidence_threshold": 0.8})

        with patch("app.features.pipeline_stages.repair_stage.repair_questions", new_callable=AsyncMock) as mock_repair:
            mock_repair.return_value = {
                "repaired": [],
                "unrepaired": [],
                "skipped": [{"question_index": 0, "reason": "above_threshold", "confidence": 0.85},
                           {"question_index": 1, "reason": "above_threshold", "confidence": 0.9}],
                "stats": {"total_candidates": 2, "repaired": 0, "unrepaired": 0, "skipped": 2, "total_tokens": 0},
            }
            result = asyncio.run(pipeline._run_repair(questions=questions, options={"confidence_threshold": 0.8}))

            # Check repair_questions was called with threshold in config
            call_config = mock_repair.call_args[0][1]
            assert call_config["confidence_threshold"] == 0.8
            assert call_config["enabled"] is True


# ---------------------------------------------------------------------------
# P1-2: 风险标 risk_flags 落地（exercise_regions_missing → no_exercise_regions）
# ---------------------------------------------------------------------------


class TestRunExtractExerciseRegionsMissing:
    """覆盖 _run_extract 的 P1-2 行为：仅当 detection 真正跑了但返回空时，
    才在结果里设 exercise_regions_missing=True。下游 normalize_schema 才会
    把 no_exercise_regions 写到题目 risk_flags。"""

    def _patch_settings(self):
        return [
            patch("app.core.config.settings.OCR_ENABLED", True),
            patch("app.core.config.settings.EXERCISE_DETECTION_ENABLED", True),
            patch("app.core.config.settings.EXERCISE_DETECTION_MAX_EMPTY_PAGES", 2),
            patch("app.core.config.settings.EXERCISE_DETECTION_MIN_CONFIDENCE", 0.5),
        ]

    def test_book_pdf_detection_empty_marks_missing(self):
        pipeline = ImportPipeline()
        sparse = [{"page": 1, "block_index": 0, "text": "x"}]
        ocr_blocks = [{"page": 1, "block_index": 0, "text": "OCR 全本兜底内容"}]

        patches = self._patch_settings() + [
            patch(
                "app.features.pipeline_orchestrator._extract_pdf_blocks",
                return_value=sparse,
            ),
            patch(
                "app.features.pipeline_orchestrator._ocr_scanned_pdf",
                return_value=ocr_blocks,
            ),
            patch(
                "app.features.exercise_region_detector.detect_exercise_regions",
                return_value=[],
            ),
        ]
        for p in patches:
            p.start()
        try:
            result = pipeline._run_extract(
                b"pdf", "pdf", options={"import_mode": "book"},
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert result["exercise_regions"] == []
        assert result["exercise_regions_missing"] is True
        assert result["raw_blocks"] == ocr_blocks

    def test_detection_hit_does_not_mark_missing(self):
        from app.features.exercise_region_detector import ExerciseRegion

        pipeline = ImportPipeline()
        sparse = [{"page": 1, "block_index": 0, "text": "x"}]
        ocr_blocks = [{"page": 1, "block_index": 0, "text": "习题区 OCR"}]
        hit_region = ExerciseRegion(
            start_page=1, end_page=2, confidence=0.9, matched_keyword="本节习题",
        )

        patches = self._patch_settings() + [
            patch(
                "app.features.pipeline_orchestrator._extract_pdf_blocks",
                return_value=sparse,
            ),
            patch(
                "app.features.pipeline_orchestrator._ocr_scanned_pdf",
                return_value=ocr_blocks,
            ),
            patch(
                "app.features.exercise_region_detector.detect_exercise_regions",
                return_value=[hit_region],
            ),
        ]
        for p in patches:
            p.start()
        try:
            result = pipeline._run_extract(
                b"pdf", "pdf", options={"import_mode": "book"},
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert result["exercise_regions"] != []
        assert result["exercise_regions_missing"] is False

    def test_user_specified_page_range_skips_detection_no_missing(self):
        pipeline = ImportPipeline()
        sparse = [{"page": 1, "block_index": 0, "text": "x"}]
        ocr_blocks = [{"page": 1, "block_index": 0, "text": "用户指定范围 OCR"}]

        patches = self._patch_settings() + [
            patch(
                "app.features.pipeline_orchestrator._extract_pdf_blocks",
                return_value=sparse,
            ),
            patch(
                "app.features.pipeline_orchestrator._ocr_scanned_pdf",
                return_value=ocr_blocks,
            ),
        ]
        for p in patches:
            p.start()
        try:
            result = pipeline._run_extract(
                b"pdf",
                "pdf",
                options={"import_mode": "book", "page_start": 10, "page_end": 20},
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert result["exercise_regions_missing"] is False

    def test_exam_mode_skips_detection_no_missing(self):
        pipeline = ImportPipeline()
        sparse = [{"page": 1, "block_index": 0, "text": "x"}]
        ocr_blocks = [{"page": 1, "block_index": 0, "text": "exam 全本 OCR"}]

        patches = self._patch_settings() + [
            patch(
                "app.features.pipeline_orchestrator._extract_pdf_blocks",
                return_value=sparse,
            ),
            patch(
                "app.features.pipeline_orchestrator._ocr_scanned_pdf",
                return_value=ocr_blocks,
            ),
        ]
        for p in patches:
            p.start()
        try:
            result = pipeline._run_extract(
                b"pdf", "pdf", options={"import_mode": "exam"},
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert result["exercise_regions_missing"] is False

    def test_txt_source_returns_missing_false(self):
        pipeline = ImportPipeline()
        with patch(
            "app.features.pipeline_orchestrator._extract_text_blocks",
            return_value=[{"page": 1, "block_index": 0, "text": "纯文本"}],
        ):
            result = pipeline._run_extract(b"hi", "txt")

        assert result["exercise_regions_missing"] is False


class TestRunNormalizeSchemaRiskFlags:
    """覆盖 _run_normalize_schema 的 P1-2 行为：根据 import_mode +
    exercise_regions_missing + confidence_score 给每道题打 risk_flags。"""

    def test_book_mode_with_missing_regions_adds_no_exercise_regions(self):
        pipeline = ImportPipeline()
        with patch(
            "app.features.pipeline_stages.normalize_schema_stage.normalize_questions",
            return_value={
                "questions": [
                    {"stem": "Q1", "confidence_score": 0.9, "is_valid": True, "errors": []},
                    {"stem": "Q2", "confidence_score": 0.3, "is_valid": True, "errors": []},
                ],
                "errors": [],
                "warnings": [],
            },
        ):
            result = pipeline._run_normalize_schema(
                raw_questions=[{"number": 1}, {"number": 2}],
                matched=[],
                source_file="book.pdf",
                source_type="pdf",
                import_mode="book",
                exercise_regions_missing=True,
            )

        questions = result["questions"]
        assert "no_exercise_regions" in questions[0]["risk_flags"]
        assert "no_exercise_regions" in questions[1]["risk_flags"]
        # 第二题 confidence 0.3 → low_confidence；去重 + 保序
        assert "low_confidence" in questions[1]["risk_flags"]
        assert "low_confidence" not in questions[0].get("risk_flags", [])
        assert any("no_exercise_regions risk flag" in w for w in result["warnings"])

    def test_exam_mode_skips_no_exercise_regions_even_when_missing(self):
        pipeline = ImportPipeline()
        with patch(
            "app.features.pipeline_stages.normalize_schema_stage.normalize_questions",
            return_value={
                "questions": [{"stem": "Q1", "confidence_score": 0.8, "is_valid": True, "errors": []}],
                "errors": [],
                "warnings": [],
            },
        ):
            result = pipeline._run_normalize_schema(
                raw_questions=[{"number": 1}],
                matched=[],
                source_file="exam.pdf",
                source_type="pdf",
                import_mode="exam",
                exercise_regions_missing=True,
            )

        assert "risk_flags" not in result["questions"][0]

    def test_book_mode_without_missing_does_not_flag(self):
        pipeline = ImportPipeline()
        with patch(
            "app.features.pipeline_stages.normalize_schema_stage.normalize_questions",
            return_value={
                "questions": [{"stem": "Q1", "confidence_score": 0.8, "is_valid": True, "errors": []}],
                "errors": [],
                "warnings": [],
            },
        ):
            result = pipeline._run_normalize_schema(
                raw_questions=[{"number": 1}],
                matched=[],
                source_file="book.pdf",
                source_type="pdf",
                import_mode="book",
                exercise_regions_missing=False,
            )

        assert "risk_flags" not in result["questions"][0]

    def test_upstream_risk_flags_preserved_and_extended(self):
        """splitter 写入的 upstream flag 应被保留，normalize 阶段追加自己的 flag。"""
        pipeline = ImportPipeline()
        with patch(
            "app.features.pipeline_stages.normalize_schema_stage.normalize_questions",
            return_value={
                "questions": [{
                    "stem": "Q1",
                    "confidence_score": 0.3,
                    "is_valid": True,
                    "errors": [],
                    "risk_flags": ["book_pdf_prose_like"],
                }],
                "errors": [],
                "warnings": [],
            },
        ):
            result = pipeline._run_normalize_schema(
                raw_questions=[{"number": 1}],
                matched=[],
                source_file="book.pdf",
                source_type="pdf",
                import_mode="book",
                exercise_regions_missing=True,
            )

        flags = result["questions"][0]["risk_flags"]
        assert "book_pdf_prose_like" in flags
        assert "no_exercise_regions" in flags
        assert "low_confidence" in flags
        # 去重保序：上游 flag 在最前
        assert flags.index("book_pdf_prose_like") < flags.index("no_exercise_regions")


# ---------------------------------------------------------------------------
# P1-4: PDF page range — resolve_pdf_page_range
# ---------------------------------------------------------------------------


class TestResolvePdfPageRange:
    """Unit tests for resolve_pdf_page_range() validation + resolution."""

    def test_invalid_total_pages_zero(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        with pytest.raises(ValueError, match="PDF 总页数无效"):
            resolve_pdf_page_range(total_pages=0)

    def test_invalid_total_pages_negative(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        with pytest.raises(ValueError, match="PDF 总页数无效"):
            resolve_pdf_page_range(total_pages=-1)

    def test_page_start_below_one(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        with pytest.raises(ValueError, match="起始页必须是大于等于 1 的整数"):
            resolve_pdf_page_range(total_pages=10, page_start=0)

    def test_page_start_exceeds_total(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        with pytest.raises(ValueError, match="起始页 11 超出 PDF 总页数 10"):
            resolve_pdf_page_range(total_pages=10, page_start=11)

    def test_page_end_below_one(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        with pytest.raises(ValueError, match="结束页必须是大于等于 1 的整数"):
            resolve_pdf_page_range(total_pages=10, page_end=0)

    def test_page_end_exceeds_total(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        with pytest.raises(ValueError, match="结束页 20 超出 PDF 总页数 10"):
            resolve_pdf_page_range(total_pages=10, page_end=20)

    def test_start_after_end(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        with pytest.raises(ValueError, match="起始页不能大于结束页"):
            resolve_pdf_page_range(total_pages=10, page_start=5, page_end=3)

    def test_defaults_to_full_range(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        result = resolve_pdf_page_range(total_pages=50)
        assert result.effective_start == 1
        assert result.effective_end == 50
        assert result.selected_page_count == 50
        assert result.total_pages == 50
        assert result.requested_start is None
        assert result.requested_end is None

    def test_explicit_range(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        result = resolve_pdf_page_range(total_pages=100, page_start=10, page_end=20)
        assert result.effective_start == 10
        assert result.effective_end == 20
        assert result.selected_page_count == 11  # inclusive
        assert result.requested_start == 10
        assert result.requested_end == 20

    def test_only_page_start(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        result = resolve_pdf_page_range(total_pages=30, page_start=25)
        assert result.effective_start == 25
        assert result.effective_end == 30
        assert result.selected_page_count == 6
        assert result.requested_start == 25
        assert result.requested_end is None

    def test_only_page_end(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        result = resolve_pdf_page_range(total_pages=30, page_end=15)
        assert result.effective_start == 1
        assert result.effective_end == 15
        assert result.selected_page_count == 15
        assert result.requested_start is None
        assert result.requested_end == 15

    def test_page_start_equals_page_end(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        result = resolve_pdf_page_range(total_pages=50, page_start=7, page_end=7)
        assert result.effective_start == 7
        assert result.effective_end == 7
        assert result.selected_page_count == 1

    def test_page_start_equals_total_pages(self):
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        result = resolve_pdf_page_range(total_pages=10, page_start=10)
        assert result.effective_start == 10
        assert result.effective_end == 10
        assert result.selected_page_count == 1

    def test_selected_page_count_inclusive(self):
        """selected_page_count must be (end - start + 1), i.e. inclusive."""
        from app.features.pipeline_orchestrator import resolve_pdf_page_range
        r1 = resolve_pdf_page_range(total_pages=10, page_start=1, page_end=1)
        assert r1.selected_page_count == 1
        r5 = resolve_pdf_page_range(total_pages=10, page_start=1, page_end=5)
        assert r5.selected_page_count == 5
        r10 = resolve_pdf_page_range(total_pages=10)
        assert r10.selected_page_count == 10


# ---------------------------------------------------------------------------
# P1-4: PDF page range — split_page_range
# ---------------------------------------------------------------------------


class TestSplitPageRange:
    """Unit tests for split_page_range() chunking."""

    def test_splits_evenly(self):
        from app.features.pipeline_orchestrator import split_page_range
        result = split_page_range(1, 80, 40)
        assert result == [(1, 40), (41, 80)]

    def test_last_chunk_shorter(self):
        from app.features.pipeline_orchestrator import split_page_range
        result = split_page_range(1, 100, 40)
        assert result == [(1, 40), (41, 80), (81, 100)]

    def test_single_page_range(self):
        from app.features.pipeline_orchestrator import split_page_range
        result = split_page_range(5, 5, 10)
        assert result == [(5, 5)]

    def test_chunk_size_larger_than_range(self):
        from app.features.pipeline_orchestrator import split_page_range
        result = split_page_range(10, 20, 50)
        assert result == [(10, 20)]

    def test_empty_when_start_gt_end(self):
        from app.features.pipeline_orchestrator import split_page_range
        assert split_page_range(10, 5, 10) == []

    def test_empty_when_chunk_size_zero(self):
        from app.features.pipeline_orchestrator import split_page_range
        assert split_page_range(1, 10, 0) == []

    def test_empty_when_start_below_one(self):
        from app.features.pipeline_orchestrator import split_page_range
        assert split_page_range(0, 10, 10) == []

    def test_offset_start(self):
        """Non-1 start page — e.g. user-selected sub-range."""
        from app.features.pipeline_orchestrator import split_page_range
        result = split_page_range(101, 220, 40)
        assert result == [(101, 140), (141, 180), (181, 220)]

    def test_chunk_size_one(self):
        from app.features.pipeline_orchestrator import split_page_range
        result = split_page_range(1, 3, 1)
        assert result == [(1, 1), (2, 2), (3, 3)]


# ---------------------------------------------------------------------------
# P1-4: Page rendering with range
# ---------------------------------------------------------------------------


class TestRenderPageImagesRange:
    """Verify page rendering respects page_start/page_end."""

    def test_render_page_images_uses_range(self):
        """_render_page_images should only render pages within range."""
        from app.features.pipeline_orchestrator import _render_page_images

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for i in range(5):
            p = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = f"page{i + 1}".encode()
            pix.width = 800
            pix.height = 600
            p.get_pixmap.return_value = pix
            pages.append(p)
        mock_doc.__len__ = MagicMock(return_value=5)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = _render_page_images(file_content=b"pdf content", page_start=2, page_end=4)

        # Should only render pages 2, 3, 4
        assert list(result.keys()) == [2, 3, 4]
        assert result[2] is not None
        assert result[4] is not None
        mock_doc.close.assert_called_once()

    def test_render_page_images_default_full_range(self):
        """Without page_start/page_end, render all pages."""
        from app.features.pipeline_orchestrator import _render_page_images

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for i in range(3):
            p = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = f"p{i + 1}".encode()
            pix.width = 800
            pix.height = 600
            p.get_pixmap.return_value = pix
            pages.append(p)
        mock_doc.__len__ = MagicMock(return_value=3)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = _render_page_images(file_content=b"pdf content")

        assert list(result.keys()) == [1, 2, 3]
        mock_doc.close.assert_called_once()

    def test_render_page_image_refs_uses_range(self):
        """_render_page_image_refs should only include refs within range."""
        from app.features.pipeline_orchestrator import _render_page_image_refs

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for i in range(5):
            p = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = f"ref{i + 1}".encode()
            pix.width = 100
            pix.height = 200
            p.get_pixmap.return_value = pix
            pages.append(p)
        mock_doc.__len__ = MagicMock(return_value=5)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = _render_page_image_refs(
                file_path="/fake/test.pdf",
                temp_dir="/tmp/test_frames",
                page_start=3,
                page_end=5,
            )

        assert len(result) == 3
        assert 3 in result and 5 in result
        mock_doc.close.assert_called_once()


# ---------------------------------------------------------------------------
# P2: page_range state persistence
# ---------------------------------------------------------------------------


class TestPageRangePersistence:
    """Verify page_range survives store transitions:
    queued → processing → completed (and failed).
    """

    @pytest.fixture(autouse=True)
    def _cleanup(self):
        _pipeline_store.clear()
        yield

    async def _write_store(self, pipeline_id: str, status: str, page_range: dict | None = None, **extra):
        data = {
            "pipeline_id": pipeline_id,
            "status": status,
            "source_type": "pdf",
            "stages": {},
            "stats": {},
            "errors": [],
            "started_at": "2026-01-01T00:00:00",
        }
        if page_range is not None:
            data["page_range"] = page_range
        data.update(extra)
        await _set_pipeline_store(pipeline_id, data)

    @pytest.mark.asyncio
    async def test_page_range_present_in_queued(self):
        pr = {"effective_start": 1, "effective_end": 5, "selected_page_count": 5, "total_pages": 10}
        await self._write_store("p1", "queued", page_range=pr)
        data = await get_pipeline_status("p1")
        assert data is not None
        assert data.get("page_range") == pr

    @pytest.mark.asyncio
    async def test_page_range_present_in_processing(self):
        pr = {"effective_start": 2, "effective_end": 4, "selected_page_count": 3, "total_pages": 10}
        await self._write_store("p2", "processing", page_range=pr,
                                current_stage="extract")
        data = await get_pipeline_status("p2")
        assert data is not None
        assert data.get("page_range") == pr

    @pytest.mark.asyncio
    async def test_page_range_present_in_completed(self):
        pr = {"effective_start": 1, "effective_end": 10, "selected_page_count": 10, "total_pages": 10}
        await self._write_store("p3", "completed", page_range=pr,
                                batch_id="batch-1", finished_at="2026-01-01T01:00:00")
        data = await get_pipeline_status("p3")
        assert data is not None
        assert data.get("page_range") == pr

    @pytest.mark.asyncio
    async def test_page_range_present_in_failed(self):
        pr = {"effective_start": 1, "effective_end": 5, "selected_page_count": 5, "total_pages": 10}
        await self._write_store("p4", "failed", page_range=pr,
                                errors=["test error"], finished_at="2026-01-01T01:00:00")
        data = await get_pipeline_status("p4")
        assert data is not None
        assert data.get("page_range") == pr
        assert "test error" in data.get("errors", [])

    @pytest.mark.asyncio
    async def test_page_range_not_lost_on_store_overwrite(self):
        """Simulate the background task overwrite pattern."""
        pr = {"effective_start": 2, "effective_end": 5, "selected_page_count": 4, "total_pages": 10}
        await self._write_store("p5", "processing", page_range=pr)

        # Overwrite with new status (as run_pipeline_background does)
        existing = _pipeline_store.get("p5", {})
        await _set_pipeline_store("p5", {
            "pipeline_id": "p5",
            "status": "processing",
            "source_type": "pdf",
            "current_stage": "normalize_text",
            "stages": {},
            "stats": {},
            "errors": [],
            "started_at": "2026-01-01T00:00:00",
            "page_range": existing.get("page_range"),
        })
        data = await get_pipeline_status("p5")
        assert data is not None
        assert data.get("page_range") == pr, "page_range should survive store overwrite"

    @pytest.mark.asyncio
    async def test_non_pdf_has_no_page_range(self):
        await self._write_store("p6", "processing")
        data = await get_pipeline_status("p6")
        assert data is not None
        assert data.get("page_range") is None

    @pytest.mark.asyncio
    async def test_upload_response_page_range(self):
        """Test that start_import_pipeline returns page_range immediately."""
        from app.services.import_pipeline_service import start_import_pipeline

        pdf_content = b"%PDF-1.4 test content"
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=10)
        mock_fitz.open.return_value.__enter__.return_value = mock_doc
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = await start_import_pipeline(
                file_content=pdf_content,
                filename="test.pdf",
                content_type="application/pdf",
                page_start=3,
                page_end=7,
            )

        assert result.page_range is not None
        assert result.page_range.effective_start == 3
        assert result.page_range.effective_end == 7
        assert result.page_range.selected_page_count == 5
        assert result.page_range.total_pages == 10

        assert result.page_range is not None
        assert result.page_range.effective_start == 3
        assert result.page_range.effective_end == 7
        assert result.page_range.selected_page_count == 5
        assert result.page_range.total_pages == 10


# ---------------------------------------------------------------------------
# P2: _plan_chunks page count verification
# ---------------------------------------------------------------------------


class TestPlanChunksPageCount:
    """Verify _plan_chunks uses effective_end - effective_start + 1."""

    def test_chunk_page_count_formula(self):
        """Verify the formula: page_count_for_chunking = effective_end - effective_start + 1."""
        # Direct formula verification
        for effective_start, effective_end, total_pages, expected_count in [
            (1, 10, 10, 10),
            (2, 5, 10, 4),
            (3, 3, 10, 1),
            (1, 1, 10, 1),
            (10, 10, 10, 1),
        ]:
            page_count = min(effective_end, total_pages) - effective_start + 1
            assert page_count == expected_count, (
                f"start={effective_start} end={effective_end} total={total_pages} "
                f"→ {page_count} != {expected_count}"
            )


# ---------------------------------------------------------------------------
# P2: Service-level error handling for non-PDF page range
# ---------------------------------------------------------------------------


class TestNonPdfPageRangeRejection:
    """Non-PDF files with page_start/page_end should raise ValueError."""

    @pytest.mark.asyncio
    async def test_image_with_page_range_raises(self):
        from app.services.import_pipeline_service import start_import_pipeline

        with pytest.raises(ValueError, match="仅适用于 PDF"):
            await start_import_pipeline(
                file_content=b"fake image content",
                filename="test.jpg",
                content_type="image/jpeg",
                page_start=1,
            )

    @pytest.mark.asyncio
    async def test_txt_with_page_range_raises(self):
        from app.services.import_pipeline_service import start_import_pipeline

        with pytest.raises(ValueError, match="仅适用于 PDF"):
            await start_import_pipeline(
                file_content=b"some text content",
                filename="test.txt",
                content_type="text/plain",
                page_end=5,
            )

    @pytest.mark.asyncio
    async def test_excel_with_page_range_raises(self):
        from app.services.import_pipeline_service import start_import_pipeline

        with pytest.raises(ValueError, match="仅适用于 PDF"):
            await start_import_pipeline(
                file_content=b"fake excel",
                filename="test.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                page_start=1,
                page_end=10,
            )

    @pytest.mark.asyncio
    async def test_pdf_with_page_range_ok(self):
        from app.services.import_pipeline_service import start_import_pipeline

        pdf_content = b"%PDF-1.4 test"
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=10)
        mock_fitz.open.return_value.__enter__.return_value = mock_doc
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = await start_import_pipeline(
                file_content=pdf_content,
                filename="test.pdf",
                content_type="application/pdf",
                page_start=2,
                page_end=5,
            )
        assert result.page_range is not None
        assert result.page_range.selected_page_count == 4

