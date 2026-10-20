"""Preserve actual run font XML and OMML raw-text fallback behavior."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from app.services.export import omml_converter
from app.services.export.docx_fonts import set_east_asian_font


@pytest.mark.parametrize("font", [
    "SimSun", "SimHei", "DengXian", "Times New Roman", "Consolas", "合成字体",
])
def test_east_asian_font_creates_one_font_element_and_updates_in_place(font):
    run = Document().add_paragraph().add_run("合成题目")
    assert run._r.rPr is None
    set_east_asian_font(run, "previous")
    first = run._r.rPr.find(qn("w:rFonts"))
    set_east_asian_font(run, font)
    assert run._r.rPr.find(qn("w:rFonts")) is first
    assert len(run._r.rPr.findall(qn("w:rFonts"))) == 1
    assert first.get(qn("w:eastAsia")) == font
    assert run.text == "合成题目"


def test_font_update_preserves_latin_attributes_other_run_properties_and_text():
    run = Document().add_paragraph().add_run("synthetic")
    run.font.name = "Times New Roman"
    run.font.size = Pt(11)
    run.bold = True
    run.italic = True
    fonts = run._r.rPr.find(qn("w:rFonts"))
    fonts.set(qn("w:cs"), "custom-complex-script")
    set_east_asian_font(run, "SimSun")
    assert fonts.get(qn("w:ascii")) == "Times New Roman"
    assert fonts.get(qn("w:hAnsi")) == "Times New Roman"
    assert fonts.get(qn("w:cs")) == "custom-complex-script"
    assert fonts.get(qn("w:eastAsia")) == "SimSun"
    assert run.font.size == Pt(11)
    assert run.bold and run.italic
    assert run.text == "synthetic"


@pytest.mark.parametrize("scenario", ["no_omml", "insert_failure", "png_failure", "png_disabled"])
def test_raw_formula_fallback_keeps_text_size_and_both_font_attributes(monkeypatch, scenario):
    monkeypatch.setattr(omml_converter, "latex_to_omml_xml", lambda *args: None)
    png = Mock(return_value=None)
    monkeypatch.setattr(omml_converter, "render_latex_to_png", png)
    if scenario == "insert_failure":
        monkeypatch.setattr(omml_converter, "latex_to_omml_xml", lambda *args: b"synthetic")
        monkeypatch.setattr(
            omml_converter, "insert_omml_into_paragraph",
            Mock(side_effect=ValueError("synthetic insert failure")),
        )
    if scenario == "png_failure":
        png.side_effect = ValueError("synthetic image failure")
    paragraph = Document().add_paragraph()
    result = omml_converter.render_latex_as_omml_or_fallback(
        "synthetic_formula", False, paragraph, fallback_png=scenario != "png_disabled",
    )
    assert result is False
    assert paragraph.text == " [公式] synthetic_formula "
    assert len(paragraph.runs) == 1
    run = paragraph.runs[0]
    assert run.font.name == "SimSun"
    assert run.font.size == Pt(8)
    fonts = run._r.rPr.find(qn("w:rFonts"))
    assert fonts.get(qn("w:ascii")) == "SimSun"
    assert fonts.get(qn("w:hAnsi")) == "SimSun"
    assert fonts.get(qn("w:eastAsia")) == "SimSun"
    if scenario == "png_disabled":
        png.assert_not_called()
    else:
        png.assert_called_once_with("synthetic_formula", False)
