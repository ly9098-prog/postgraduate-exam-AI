"""Tests for table model, parser, and DOCX table renderer."""

from __future__ import annotations

import io
import zipfile

from app.services.export.table_model import TableBlock, TextAlign
from app.services.export.table_parser import (
    parse_html_table,
    parse_markdown_table,
    parse_table,
)
from app.services.export.table_renderer import render_table_to_docx


class TestTableModel:
    def test_empty_block(self):
        b = TableBlock()
        assert b.row_count == 0
        assert b.column_count == 0
        assert not b.has_header

    def test_from_rows(self):
        b = TableBlock.from_rows(
            headers=["Name", "Score"],
            data=[["Alice", "95"], ["Bob", "87"]],
        )
        assert b.row_count == 3
        assert b.column_count == 2
        assert b.has_header

    def test_to_dict(self):
        b = TableBlock.from_rows(
            headers=["A", "B"],
            data=[["1", "2"]],
        )
        d = b.to_dict()
        assert d["row_count"] == 2
        assert d["column_count"] == 2
        assert d["has_header"] is True


class TestMarkdownTableParser:
    def test_basic_table(self):
        md = "| Name | Age |\n|------|-----|\n| Alice | 25 |\n| Bob | 30 |\n"
        blocks = parse_markdown_table(md)
        assert len(blocks) == 1
        b = blocks[0]
        assert b.row_count == 3
        assert b.column_count == 2
        assert b.has_header

    def test_no_tables_returns_empty(self):
        assert parse_markdown_table("just text") == []
        assert parse_markdown_table("") == []

    def test_alignment_detection(self):
        md = "| L | C | R |\n|:---|:---:|---:|\n| a | b | c |\n"
        blocks = parse_markdown_table(md)
        cells = blocks[0].rows[1].cells
        assert cells[0].alignment == TextAlign.LEFT
        assert cells[1].alignment == TextAlign.CENTER
        assert cells[2].alignment == TextAlign.RIGHT


class TestHtmlTableParser:
    def test_basic_html_table(self):
        html = "<table><tr><th>Name</th><th>Score</th></tr><tr><td>Alice</td><td>95</td></tr></table>"
        blocks = parse_html_table(html)
        assert len(blocks) == 1
        b = blocks[0]
        assert b.row_count == 2
        assert b.column_count == 2
        assert b.has_header

    def test_colspan_rowspan(self):
        html = '<table><tr><td colspan="2" rowspan="2">Merged</td></tr></table>'
        blocks = parse_html_table(html)
        cell = blocks[0].rows[0].cells[0]
        assert cell.col_span == 2
        assert cell.row_span == 2

    def test_align_attribute(self):
        html = '<table><tr><td align="center">Centered</td></tr></table>'
        blocks = parse_html_table(html)
        cell = blocks[0].rows[0].cells[0]
        assert cell.alignment == TextAlign.CENTER


class TestDocxTableRenderer:
    """Test native Word table rendering via Open XML inspection."""

    def test_table_creates_w_tbl(self):
        from docx import Document
        doc = Document()
        block = TableBlock.from_rows(
            headers=["Q", "A"],
            data=[["1+1=?", "2"], ["2+2=?", "4"]],
        )
        render_table_to_docx(doc, block)

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        with zipfile.ZipFile(buf) as z:
            doc_xml = z.read("word/document.xml").decode("utf-8")
            assert "<w:tbl>" in doc_xml
            assert '<w:tc>' in doc_xml
            # Header cell should exist
            assert "Q" in doc_xml or "A" in doc_xml

    def test_empty_block_creates_placeholder(self):
        from docx import Document
        doc = Document()
        block = TableBlock()
        render_table_to_docx(doc, block)

        buf = io.BytesIO()
        doc.save(buf)
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            doc_xml = z.read("word/document.xml").decode("utf-8")
            assert "<w:tbl>" in doc_xml

    def test_table_borders_present(self):
        from docx import Document
        doc = Document()
        block = TableBlock.from_rows(
            headers=["A"],
            data=[["1"]],
        )
        render_table_to_docx(doc, block)

        buf = io.BytesIO()
        doc.save(buf)
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            doc_xml = z.read("word/document.xml").decode("utf-8")
            assert "w:tblBorders" in doc_xml


class TestAutoParse:
    def test_auto_detect_markdown(self):
        md = "| H |\n|---|\n| v |\n"
        blocks = parse_table(md)
        assert len(blocks) == 1
        assert blocks[0].column_count == 1

    def test_auto_detect_html(self):
        html = "<table><tr><td>x</td></tr></table>"
        blocks = parse_table(html)
        assert len(blocks) == 1

    def test_auto_no_match_returns_empty(self):
        assert parse_table("plain text") == []
