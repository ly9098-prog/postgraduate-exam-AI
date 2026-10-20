"""Shared DOCX font policy and run formatting, independent of document renderers."""

from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.run import Run

BODY_FONT = "SimSun"
BODY_FONT_EA = "SimSun"
HEADING_FONT = "SimHei"
EN_FONT = "Times New Roman"
CODE_FONT = "Consolas"
CODE_FONT_CJK = "DengXian"


def set_east_asian_font(run: Run, font_name: str) -> None:
    """Set the East-Asian font on a run via OOXML."""
    rpr = run._r.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)
