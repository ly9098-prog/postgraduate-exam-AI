"""Test the live writer parser with synthetic inputs and real normalization helpers."""

import io
from unittest.mock import Mock

import pytest
from openpyxl import Workbook

from app.features import question_import_writer as writer

TEXT = (
    "1. Which statement about the CPU cache is correct?\n"
    "A. alpha\nB. beta\nC. gamma\nD. delta\n"
    "答案：B\n解析：The second statement is correct.\n"
)


def test_pdf_parser_keeps_options_answer_analysis_and_canonical_subject(monkeypatch):
    extract = Mock(return_value=TEXT)
    monkeypatch.setattr(writer, "_extract_pdf_text", extract)
    result = writer._parse_pdf(b"synthetic", "synthetic.pdf")
    extract.assert_called_once_with(b"synthetic")
    assert len(result) == 1
    row = result[0]
    assert row["question_type"] == "single_choice"
    assert row["subject"] == "computer_organization"
    assert row["answer"] == "B"
    assert row["options"] == "A:alpha\\nB:beta\\nC:gamma\\nD:delta"
    assert row["explanation"] == "The second statement is correct."
    assert "Which statement" in row["stem"]
    assert "second statement is correct" not in row["stem"]


def test_pdf_parser_rejects_empty_extraction(monkeypatch):
    monkeypatch.setattr(writer, "_extract_pdf_text", Mock(return_value=" \n"))
    with pytest.raises(ValueError, match="PDF 中未提取到文本内容"):
        writer._parse_pdf(b"synthetic", "empty.pdf")


def test_excel_parser_trims_values_keeps_zero_and_skips_empty_rows():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([" stem ", "answer", None])
    sheet.append(["  example question  ", " A ", 0])
    sheet.append([None, None, None])
    sheet.append(["second question", "B", None])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    assert writer._parse_excel(output.getvalue(), "synthetic.xlsx") == [
        {"stem": "example question", "answer": "A", "col_2": 0},
        {"stem": "second question", "answer": "B", "col_2": None},
    ]
