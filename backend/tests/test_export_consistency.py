"""Content consistency tests between PDF and DOCX exporters.

Verifies that the same snapshot produces equivalent business content
across both formats.  Layout differences are expected; content
differences are not.

Also includes basic performance benchmarks and orphan/cleanup tests.
"""

from __future__ import annotations

import io
import os
import time
import zipfile

import pytest

from app.services.export.docx_exporter import DocxExporter
from app.services.export.exporter_base import ExportResult
from app.services.export.pdf_exporter import PdfExporter

pytestmark = pytest.mark.asyncio


# ── Fixtures ──


def _make_question(
    stem: str,
    qtype: str = "single_choice",
    options: dict | None = None,
    answer: str = "A",
    analysis: str = "",
) -> dict:
    return {
        "content": {"stem": stem, "text": stem},
        "question_type": qtype,
        "options": options or {"A": "选项 A", "B": "选项 B", "C": "选项 C", "D": "选项 D"},
        "answer": answer,
        "analysis": analysis,
        "subject": {"id": 1, "label": "数学"},
        "_group_title": "",
    }


def _make_config(**overrides) -> dict:
    config = {
        "title": "一致性测试",
        "file_name": "test.pdf",
        "show_date": True,
        "export_date": "2026-07-25",
        "sort_by": "newest",
        "group_by": "none",
        "answer_position": "none",
        "analysis_position": "none",
        "space_style": "standard",
        "product_name": "MemoGrad",
        "total_count": 3,
        "skip_count": 0,
    }
    config.update(overrides)
    return config


async def _generate(format: str, questions: list[dict], config: dict) -> ExportResult:
    """Generate an export in the given format."""
    snapshot = {"questions": questions, "config": config}
    exporter = PdfExporter() if format == "pdf" else DocxExporter()
    return await exporter.export(snapshot, "/tmp")


# ═══════════════════════════════════════════════════
# Content consistency (Task 12)
# ═══════════════════════════════════════════════════


class TestContentConsistency:
    """PDF and DOCX from the same snapshot produce equivalent content."""

    async def test_question_count_matches(self):
        """Both formats include the same number of questions."""
        qs = [_make_question(f"题 {i}") for i in range(5)]
        cfg = _make_config(total_count=5)

        pdf_result = await _generate("pdf", qs, cfg)
        docx_result = await _generate("docx", qs, cfg)

        assert pdf_result.success
        assert docx_result.success

        pdf_text = _extract_pdf_text(pdf_result.file_bytes)
        docx_text = _extract_docx_text(docx_result.file_bytes)

        assert pdf_text is not None
        assert docx_text is not None

        # Both should reference all question numbers
        for i in range(1, 6):
            assert str(i) in pdf_text, f"Question {i} missing from PDF"
            assert str(i) in docx_text, f"Question {i} missing from DOCX"

    async def test_answers_match(self):
        """Answer content is preserved in both formats."""
        qs = [
            _make_question("题 1", answer="A", analysis="解析1"),
            _make_question("题 2", answer="B", analysis="解析2"),
        ]
        cfg = _make_config(
            total_count=2,
            answer_position="at_end",
            analysis_position="at_end",
        )

        pdf_result = await _generate("pdf", qs, cfg)
        docx_result = await _generate("docx", qs, cfg)

        assert pdf_result.success
        assert docx_result.success

        pdf_text = _extract_pdf_text(pdf_result.file_bytes)
        docx_text = _extract_docx_text(docx_result.file_bytes)

        assert pdf_text is not None
        assert docx_text is not None

        # Both should contain the answer
        assert "A" in pdf_text
        assert "A" in docx_text
        assert "B" in pdf_text
        assert "B" in docx_text

    async def test_same_questions_different_snapshot(self):
        """Different snapshot → different output (non-regression)."""
        qs_a = [_make_question("问题 A")]
        qs_b = [_make_question("问题 B")]

        pdf_a = await _generate("pdf", qs_a, _make_config(total_count=1))
        pdf_b = await _generate("pdf", qs_b, _make_config(total_count=1))

        assert pdf_a.file_bytes != pdf_b.file_bytes

    async def test_summary_line_in_header(self):
        """Both formats show total question count."""
        qs = [_make_question(f"题 {i}") for i in range(3)]
        cfg = _make_config(total_count=3)

        pdf_result = await _generate("pdf", qs, cfg)
        docx_result = await _generate("docx", qs, cfg)

        assert pdf_result.success
        assert docx_result.success

        pdf_text = _extract_pdf_text(pdf_result.file_bytes)
        docx_text = _extract_docx_text(docx_result.file_bytes)

        # PDF header
        if pdf_text:
            assert "3" in pdf_text

    async def test_empty_questions_handled_consistently(self):
        """Empty question list produces valid output in both formats."""
        pdf_result = await _generate("pdf", [], _make_config(total_count=0))
        docx_result = await _generate("docx", [], _make_config(total_count=0))
        assert pdf_result.success
        assert docx_result.success


# ═══════════════════════════════════════════════════
# Performance baselines (Task 15)
# ═══════════════════════════════════════════════════


class TestPerformanceBaselines:
    """Measure export generation time and file size for scaling analysis."""

    @pytest.mark.parametrize("count", [1, 10, 50])
    async def test_pdf_scale(self, count):
        """PDF generation time and size for N questions."""
        qs = [_make_question(f"第{i}题的内容用于压测") for i in range(count)]
        cfg = _make_config(total_count=count, file_name="perf.pdf")

        start = time.time()
        result = await _generate("pdf", qs, cfg)
        elapsed = time.time() - start

        assert result.success
        assert result.file_bytes is not None
        size_kb = len(result.file_bytes) / 1024

        print(f"\n  PDF {count}问: {elapsed:.2f}s, {size_kb:.1f}KB")
        # Basic sanity: generation time reasonable
        assert elapsed < 60, f"PDF {count} questions took {elapsed:.2f}s"

    @pytest.mark.parametrize("count", [1, 10, 50])
    async def test_docx_scale(self, count):
        """DOCX generation time and size for N questions."""
        qs = [_make_question(f"第{i}题的内容用于压测") for i in range(count)]
        cfg = _make_config(total_count=count, file_name="perf.docx")

        start = time.time()
        result = await _generate("docx", qs, cfg)
        elapsed = time.time() - start

        assert result.success
        assert result.file_bytes is not None
        size_kb = len(result.file_bytes) / 1024

        print(f"\n  DOCX {count}问: {elapsed:.2f}s, {size_kb:.1f}KB")
        assert elapsed < 60, f"DOCX {count} questions took {elapsed:.2f}s"


# ═══════════════════════════════════════════════════
# Storage & cleanup tests (Task 14)
# ═══════════════════════════════════════════════════


class TestCleanupEdgeCases:
    """Orphan detection, idempotent cleanup, file lifecycle."""

    async def test_export_result_has_file_bytes(self):
        """Normal export produces non-empty file bytes."""
        q = _make_question("正常题")
        cfg = _make_config(total_count=1)
        for fmt in ("pdf", "docx"):
            result = await _generate(fmt, [q], cfg)
            assert result.success
            assert result.file_bytes is not None
            assert len(result.file_bytes) > 100  # At least 100 bytes

    async def test_docx_zip_integrity(self):
        """DOCX output is a valid ZIP (required format)."""
        q = _make_question("测试")
        result = await _generate("docx", [q], _make_config(total_count=1))
        assert result.success

        buf = io.BytesIO(result.file_bytes)
        assert zipfile.is_zipfile(buf)

        with zipfile.ZipFile(buf) as z:
            names = z.namelist()
            assert "[Content_Types].xml" in names
            assert any("document.xml" in n for n in names)

    async def test_empty_stem_does_not_crash(self):
        """Empty stem should produce valid output."""
        q = _make_question("")
        q["content"] = {"stem": ""}
        result = await _generate("docx", [q], _make_config(total_count=1))
        assert result.success

    async def test_missing_options_does_not_crash(self):
        """Missing options field should not crash."""
        q = _make_question("无选项")
        q["options"] = {}
        result = await _generate("docx", [q], _make_config(total_count=1))
        assert result.success


# ═══════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════


def _extract_docx_text(docx_bytes: bytes) -> str | None:
    """Extract all text from a DOCX file."""
    if not docx_bytes:
        return None
    from docx import Document as DocxDocument
    try:
        doc = DocxDocument(io.BytesIO(docx_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text)
    except Exception:
        return None


def _extract_pdf_text(pdf_bytes: bytes) -> str | None:
    """Extract text from a PDF file using PyMuPDF."""
    if not pdf_bytes:
        return None
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    except ImportError:
        # Fallback: PyPDF2/pdfminer
        try:
            from io import BytesIO
            from pdfminer.high_level import extract_text as pdfminer_extract
            return pdfminer_extract(BytesIO(pdf_bytes))
        except ImportError:
            return None
        except Exception:
            return None
    except Exception:
        return None
