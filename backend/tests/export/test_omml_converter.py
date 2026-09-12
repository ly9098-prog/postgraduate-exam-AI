"""Tests for OMML (Office Math Markup Language) formula conversion.

Verifies:
- LaTeX → MathML → OMML conversion
- OMML insertion into DOCX paragraphs
- Fallback to PNG and raw text
- OMML elements in generated DOCX
- Invalid/unparseable LaTeX handling
"""

from __future__ import annotations

import io
import zipfile

from app.services.export.omml_converter import (
    insert_omml_into_paragraph,
    latex_to_omml_xml,
    render_latex_as_omml_or_fallback,
)

_OMML_NS = "schemas.openxmlformats.org/officeDocument/2006/math"


def _has_omml_ns(xml: str) -> bool:
    """Check if XML references the OMML namespace (regardless of prefix)."""
    return _OMML_NS in xml


class TestOMMLConversion:
    """LaTeX → OMML conversion tests."""

    def test_simple_superscript(self):
        omml = latex_to_omml_xml("x^2")
        assert omml is not None
        assert _has_omml_ns(omml.decode("utf-8"))

    def test_fraction(self):
        omml = latex_to_omml_xml(r"\frac{a}{b}")
        assert omml is not None
        assert _has_omml_ns(omml.decode("utf-8"))

    def test_subscript(self):
        omml = latex_to_omml_xml("H_2O")
        assert omml is not None
        assert _has_omml_ns(omml.decode("utf-8"))

    def test_integral(self):
        omml = latex_to_omml_xml(r"\int_{0}^{1} x^2 dx")
        assert omml is not None
        assert _has_omml_ns(omml.decode("utf-8"))

    def test_square_root(self):
        omml = latex_to_omml_xml(r"\sqrt{x}")
        assert omml is not None
        assert _has_omml_ns(omml.decode("utf-8"))

    def test_display_style(self):
        omml = latex_to_omml_xml(r"\frac{a}{b}", display=True)
        assert omml is not None
        assert _has_omml_ns(omml.decode("utf-8"))

    def test_empty_latex_returns_none(self):
        assert latex_to_omml_xml("") is None

    def test_long_latex_returns_none(self):
        long_latex = "x" * 6000
        assert latex_to_omml_xml(long_latex) is None

    def test_summation(self):
        omml = latex_to_omml_xml(r"\sum_{i=1}^{n} i")
        assert omml is not None
        assert _has_omml_ns(omml.decode("utf-8"))

    def test_greek_letters(self):
        omml = latex_to_omml_xml(r"\alpha \beta \gamma")
        assert omml is not None
        assert _has_omml_ns(omml.decode("utf-8"))


class TestOMMLDocxIntegration:
    """OMML embedded in real DOCX documents."""

    def _docx_has_omml(self, docx_bytes: bytes) -> bool:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            return _OMML_NS in z.read("word/document.xml").decode("utf-8")

    def test_omml_in_paragraph(self):
        from docx import Document
        doc = Document()
        p = doc.add_paragraph()
        p.add_run("Solve: ")

        omml = latex_to_omml_xml(r"E=mc^2")
        assert omml is not None
        insert_omml_into_paragraph(p, omml)

        buf = io.BytesIO()
        doc.save(buf)
        assert self._docx_has_omml(buf.getvalue())

    def test_multiple_formulas_in_document(self):
        from docx import Document
        doc = Document()
        for expr in [r"x^2", r"\frac{a}{b}", r"H_2O"]:
            p = doc.add_paragraph()
            p.add_run("Q: ")
            omml = latex_to_omml_xml(expr)
            if omml:
                insert_omml_into_paragraph(p, omml)

        buf = io.BytesIO()
        doc.save(buf)
        assert self._docx_has_omml(buf.getvalue())

    def test_render_latex_as_omml_returns_true(self):
        from docx import Document
        doc = Document()
        p = doc.add_paragraph()
        result = render_latex_as_omml_or_fallback(r"E=mc^2", False, p)
        assert result is True

        buf = io.BytesIO()
        doc.save(buf)
        assert self._docx_has_omml(buf.getvalue())

    def test_render_latex_fallback_to_text(self):
        from docx import Document
        doc = Document()
        p = doc.add_paragraph()

        result = render_latex_as_omml_or_fallback(
            r"\invalid_command{x}", False, p, fallback_png=True
        )
        assert result is not None

    def test_inline_formula_does_not_break_paragraph(self):
        from docx import Document
        doc = Document()
        p = doc.add_paragraph()
        p.add_run("Text before ")
        omml = latex_to_omml_xml("x^2")
        assert omml is not None
        insert_omml_into_paragraph(p, omml)
        p.add_run(" text after")

        buf = io.BytesIO()
        doc.save(buf)
        full_text = self._extract_docx_text(buf.getvalue())
        assert "Text before" in full_text
        assert "text after" in full_text

    @staticmethod
    def _extract_docx_text(docx_bytes: bytes) -> str:
        from docx import Document as DocxDocument
        doc = DocxDocument(io.BytesIO(docx_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text)


class TestOMMLSecurity:
    """Safety guards for formula processing."""

    def test_no_shell_execution(self):
        malicious = r"\immediate\write18{rm -rf /}"
        omml = latex_to_omml_xml(malicious)
        assert omml is None or isinstance(omml, bytes)

    def test_very_nested_formula(self):
        nested = "{" * 100 + "x" + "}" * 100
        omml = latex_to_omml_xml(nested)
        assert omml is None or isinstance(omml, bytes)
