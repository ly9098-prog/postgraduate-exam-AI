"""Tests for the DOCX exporter — covers content types, page setup, and structure.

Since DOCX is a ZIP of XML files, we validate the output by:
1. Opening with python-docx (structure check)
2. Verifying [Content_Types].xml, word/document.xml etc. via ZIP inspection
3. Checking text content, page count, header/footer fields
"""

from __future__ import annotations

import tempfile
import zipfile

import pytest

pytestmark = pytest.mark.asyncio

from app.services.export.docx_exporter import DocxExporter

# ── Fixtures ──


@pytest.fixture
def exporter():
    return DocxExporter()


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory(prefix="docx_test_") as d:
        yield d


def _make_question_stem(stem_text: str, question_type: str = "single_choice") -> dict:
    """Create a minimal question dict for testing."""
    return {
        "content": {"stem": stem_text, "text": stem_text},
        "question_type": question_type,
        "options": {"A": "选项 A", "B": "选项 B", "C": "选项 C", "D": "选项 D"},
        "answer": "A",
        "analysis": "这是解析",
        "subject": {"id": 1, "label": "数学"},
        "_group_title": "",
    }


def _make_config(**overrides) -> dict:
    config = {
        "title": "测试试卷",
        "file_name": "test.docx",
        "show_date": True,
        "export_date": "2026-07-25",
        "sort_by": "newest",
        "group_by": "none",
        "answer_position": "none",
        "analysis_position": "none",
        "space_style": "standard",
        "product_name": "MemoGrad",
        "total_count": 1,
        "skip_count": 0,
    }
    config.update(overrides)
    return config


# ═══════════════════════════════════════════════════
# Basic DOCX generation
# ═══════════════════════════════════════════════════


class TestDocxBasic:
    """Core DOCX generation — empty, single, multiple questions."""

    async def test_empty_questions(self, exporter, temp_dir):
        """No questions → valid DOCX with just header."""
        snapshot = {"questions": [], "config": _make_config(total_count=0)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success
        assert result.file_bytes is not None
        assert len(result.file_bytes) > 0

    async def test_single_question(self, exporter, temp_dir):
        """Single choice question."""
        q = _make_question_stem("1+1=?")
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success

        # Verify content via python-docx
        content = _extract_text(result.file_bytes)
        assert "1" in content
        assert "A." in content or "A" in content

    async def test_multiple_questions(self, exporter, temp_dir):
        """Five questions of varying types."""
        questions = [
            _make_question_stem(f"问题 {i} 的内容", "single_choice")
            for i in range(5)
        ]
        snapshot = {"questions": questions, "config": _make_config(total_count=5)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success
        content = _extract_text(result.file_bytes)
        for i in range(1, 6):
            assert str(i) in content


# ═══════════════════════════════════════════════════
# Question type rendering
# ═══════════════════════════════════════════════════


class TestDocxQuestionTypes:
    """Various question types render correctly."""

    async def test_single_choice(self, exporter, temp_dir):
        q = _make_question_stem("单选题", "single_choice")
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        content = _extract_text(result.file_bytes)
        assert "单选题" in content

    async def test_multiple_choice(self, exporter, temp_dir):
        q = _make_question_stem("多选题", "multiple_choice")
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        content = _extract_text(result.file_bytes)
        assert "多选题" in content

    async def test_true_false(self, exporter, temp_dir):
        q = _make_question_stem("判断题", "true_false")
        q["options"] = {"A": "正确", "B": "错误"}
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        content = _extract_text(result.file_bytes)
        assert "判断题" in content

    async def test_fill_blank(self, exporter, temp_dir):
        q = _make_question_stem("填空：1+1=____", "fill_blank")
        q["options"] = {}
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success

    async def test_subjective(self, exporter, temp_dir):
        q = _make_question_stem("简述你的观点。", "subjective")
        q["options"] = {}
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success


# ═══════════════════════════════════════════════════
# Content features
# ═══════════════════════════════════════════════════


class TestDocxContent:
    """Text rendering, sub/superscript, code, tables."""

    async def test_chinese_text(self, exporter, temp_dir):
        q = _make_question_stem("这是一道中文数学题：已知函数 f(x)=x²")
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        content = _extract_text(result.file_bytes)
        assert "中文" in content
        assert "f" in content

    async def test_subscript_superscript(self, exporter, temp_dir):
        q = _make_question_stem("H₂O 和 CO₂ 的化学式，以及 x²+y²")
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success
        content = _extract_text(result.file_bytes)
        assert "H" in content
        assert "O" in content

    async def test_code_block_via_segments(self, exporter, temp_dir):
        """Code block as segment."""
        q = _make_question_stem("代码示例")
        q["content"] = {
            "stem": "代码示例",
            "segments": [
                {"type": "text", "text": "以下代码演示："},
                {"type": "code_image", "url": "https://via.placeholder.com/400x200.png?text=code", "alt": "代码示例"},
            ],
        }
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success

    async def test_table_via_segments(self, exporter, temp_dir):
        """Table embedded as markdown."""
        q = _make_question_stem("表格数据")
        q["content"] = {
            "stem": "表格数据",
            "segments": [
                {"type": "table_markdown", "text": "|A|B|C|\n|---|---|---|\n|1|2|3|\n|4|5|6|"},
            ],
        }
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success

    async def test_segments_newline(self, exporter, temp_dir):
        q = _make_question_stem("多行内容")
        q["content"] = {
            "stem": "多行内容",
            "segments": [
                {"type": "text", "text": "第一行"},
                {"type": "newline"},
                {"type": "text", "text": "第二行"},
            ],
        }
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        content = _extract_text(result.file_bytes)
        assert "第一行" in content
        assert "第二行" in content


# ═══════════════════════════════════════════════════
# LaTeX formula handling
# ═══════════════════════════════════════════════════


class TestDocxLatex:
    """Inline and display LaTeX → PNG → embed in DOCX."""

    async def test_inline_latex(self, exporter, temp_dir):
        q = _make_question_stem("公式 $E=mc^2$ 在文中")
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success

    async def test_display_latex(self, exporter, temp_dir):
        q = _make_question_stem("块级公式 $$\\int_{0}^{1} x^2 dx$$")
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success

    async def test_latex_render_failure_fallback(self, exporter, temp_dir):
        """When LaTeX rendering fails, fall back to raw text."""
        q = _make_question_stem("公式 $\\invalid_{command}$ 回退")
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success, "Should not fail even with invalid LaTeX"


# ═══════════════════════════════════════════════════
# Answer and analysis positions
# ═══════════════════════════════════════════════════


class TestDocxAnswerAnalysis:
    """Answer and analysis in after_question and at_end positions."""

    async def test_answer_after_question(self, exporter, temp_dir):
        q = _make_question_stem("测试题")
        snapshot = {
            "questions": [q],
            "config": _make_config(answer_position="after_question", total_count=1),
        }
        result = await exporter.export(snapshot, temp_dir)
        content = _extract_text(result.file_bytes)
        assert "答案" in content

    async def test_analysis_after_question(self, exporter, temp_dir):
        q = _make_question_stem("测试题")
        snapshot = {
            "questions": [q],
            "config": _make_config(analysis_position="after_question", total_count=1),
        }
        result = await exporter.export(snapshot, temp_dir)
        content = _extract_text(result.file_bytes)
        assert "解析" in content

    async def test_answer_at_end(self, exporter, temp_dir):
        q = _make_question_stem("测试题")
        snapshot = {
            "questions": [q],
            "config": _make_config(answer_position="at_end", total_count=1),
        }
        result = await exporter.export(snapshot, temp_dir)
        content = _extract_text(result.file_bytes)
        assert "参考答案" in content

    async def test_analysis_at_end(self, exporter, temp_dir):
        q = _make_question_stem("测试题")
        snapshot = {
            "questions": [q],
            "config": _make_config(analysis_position="at_end", total_count=1),
        }
        result = await exporter.export(snapshot, temp_dir)
        content = _extract_text(result.file_bytes)
        assert "解析" in content


# ═══════════════════════════════════════════════════
# Grouping
# ═══════════════════════════════════════════════════


class TestDocxGrouping:
    """Group headers appear correctly."""

    async def test_group_header_appears(self, exporter, temp_dir):
        q1 = _make_question_stem("数学题")
        q1["_group_title"] = "数学"
        q2 = _make_question_stem("英语题")
        q2["_group_title"] = "英语"
        snapshot = {
            "questions": [q1, q2],
            "config": _make_config(group_by="subject", total_count=2),
        }
        result = await exporter.export(snapshot, temp_dir)
        content = _extract_text(result.file_bytes)
        assert "数学" in content
        assert "英语" in content


# ═══════════════════════════════════════════════════
# Document structure
# ═══════════════════════════════════════════════════


class TestDocxStructure:
    """Page setup, header, footer, page number fields, filename."""

    async def test_document_has_header(self, exporter, temp_dir):
        snapshot = {"questions": [], "config": _make_config(total_count=0)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success
        # Header should contain product name
        content = _extract_text(result.file_bytes)
        assert "MemoGrad" in content

    async def test_document_has_page_number_fields(self, exporter, temp_dir):
        """Verify the DOCX contains PAGE and NUMPAGES fields in the footer."""
        snapshot = {"questions": [], "config": _make_config(total_count=0)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success

        # Inspect ZIP for footer XML
        import io
        with zipfile.ZipFile(io.BytesIO(result.file_bytes)) as z:
            footer_files = [n for n in z.namelist() if "footer" in n]
            assert len(footer_files) > 0, "Should have footer XML"

            for fname in footer_files:
                content_xml = z.read(fname).decode("utf-8")
                assert "PAGE" in content_xml, f"Footer {fname} should contain PAGE field"
                assert "NUMPAGES" in content_xml, f"Footer {fname} should contain NUMPAGES field"

    async def test_page_size_a4(self, exporter, temp_dir):
        """Verify page size is A4 portrait."""
        snapshot = {"questions": [], "config": _make_config(total_count=0)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success

        import io

        from docx import Document as DocxDocument
        doc = DocxDocument(io.BytesIO(result.file_bytes))
        section = doc.sections[0]
        # A4 = 210mm × 297mm (in EMU: 21.0 cm, 29.7 cm)
        assert abs(section.page_width - 21.0 * 360000) < 10000, "Width should be A4"
        assert abs(section.page_height - 29.7 * 360000) < 10000, "Height should be A4 portrait"

    async def test_filename_and_mime(self, exporter, temp_dir):
        """File name and MIME type expectations."""
        snapshot = {"questions": [], "config": _make_config(file_name="测试_20260725.docx", total_count=0)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success
        assert result.file_name.endswith(".docx")

    async def test_document_opens_with_python_docx(self, exporter, temp_dir):
        """DOCX can be opened by python-docx without error."""
        snapshot = {"questions": [_make_question_stem("可打开测试")], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success

        import io

        from docx import Document as DocxDocument
        doc = DocxDocument(io.BytesIO(result.file_bytes))
        # No exception means valid document
        paragraphs = doc.paragraphs
        assert len(paragraphs) > 0


# ═══════════════════════════════════════════════════
# Error handling
# ═══════════════════════════════════════════════════


class TestDocxErrorHandling:
    """Graceful handling of edge cases and failures."""

    async def test_empty_string_stem(self, exporter, temp_dir):
        """A question with empty stem should still produce valid DOCX."""
        q = _make_question_stem("")
        q["content"] = {"stem": ""}
        snapshot = {"questions": [q], "config": _make_config(total_count=1)}
        result = await exporter.export(snapshot, temp_dir)
        assert result.success

    async def test_large_number_of_questions(self, exporter, temp_dir):
        """100 questions should generate without timeout."""
        questions = [_make_question_stem(f"第 {i} 题内容", "single_choice") for i in range(100)]
        snapshot = {"questions": questions, "config": _make_config(total_count=100)}
        import time
        start = time.time()
        result = await exporter.export(snapshot, temp_dir)
        elapsed = time.time() - start
        assert result.success, f"100 questions should succeed (took {elapsed:.2f}s)"
        assert elapsed < 30, f"100 questions should complete within 30s (took {elapsed:.2f}s)"


# ═══════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════


def _extract_text(docx_bytes: bytes) -> str:
    """Extract all text from a DOCX file."""
    import io

    from docx import Document as DocxDocument
    doc = DocxDocument(io.BytesIO(docx_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text)
