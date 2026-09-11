"""Render structured tables as native Word tables with real merged cells."""

from __future__ import annotations

import logging

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.table import Table, _Cell

from app.services.export.table_model import TableBlock, TableCell, TextAlign

logger = logging.getLogger(__name__)

_TABLE_WIDTH_FRAC = 0.95
_TABLE_FONT = "SimSun"
_TABLE_FONT_EA = "SimSun"
_TABLE_FONT_SIZE = Pt(9)
_TABLE_HEADER_FONT_SIZE = Pt(9)


def render_table_to_docx(
    doc: Document, block: TableBlock, body_width_cm: float = 17.0
) -> Table:
    """Render a ``TableBlock`` with rowspan/colspan preserved."""
    if not block.rows or block.column_count <= 0:
        return _empty_table(doc)

    row_count = block.row_count
    col_count = block.column_count
    table = doc.add_table(rows=row_count, cols=col_count)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _set_table_borders(table)
    _set_column_widths(table, block, body_width_cm)

    for row_idx, col_idx, table_cell in block.iter_anchors():
        if row_idx >= row_count or col_idx >= col_count:
            continue
        end_row = min(row_count - 1, row_idx + table_cell.row_span - 1)
        end_col = min(col_count - 1, col_idx + table_cell.col_span - 1)
        word_cell = table.cell(row_idx, col_idx)
        if end_row > row_idx or end_col > col_idx:
            word_cell = word_cell.merge(table.cell(end_row, end_col))
        _fill_cell(word_cell, table_cell)
        word_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        if table_cell.is_header:
            _style_header_cell(word_cell)

    for row in table.rows:
        _prevent_row_break(row)
    # Keeping every row with the next one can make long tables impossible to
    # paginate.  Only keep the header row attached to the first data row.
    if block.has_header and table.rows:
        _keep_row_with_next(table.rows[0])
    return table


def _set_column_widths(table: Table, block: TableBlock, body_width_cm: float) -> None:
    total_width = body_width_cm * _TABLE_WIDTH_FRAC
    if len(block.column_widths) == block.column_count and sum(block.column_widths) > 0:
        weights = [max(0.05, float(value)) for value in block.column_widths]
        total_weight = sum(weights)
        widths = [total_width * weight / total_weight for weight in weights]
    else:
        widths = [total_width / block.column_count] * block.column_count
    for col_idx, width in enumerate(widths):
        for row in table.rows:
            row.cells[col_idx].width = Cm(width)


def _fill_cell(word_cell: _Cell, table_cell: TableCell) -> None:
    word_cell.text = ""
    paragraphs = word_cell.paragraphs
    first = True
    for block in table_cell.content or [{"type": "text", "text": ""}]:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "text")
        if block_type == "newline":
            first = False
            continue
        text = str(block.get("text") or block.get("alt") or "")
        paragraph = paragraphs[0] if first and paragraphs else word_cell.add_paragraph()
        first = False
        paragraph.paragraph_format.space_before = Pt(1)
        paragraph.paragraph_format.space_after = Pt(1)
        paragraph.paragraph_format.line_spacing = 1.05
        paragraph.alignment = {
            TextAlign.LEFT: WD_ALIGN_PARAGRAPH.LEFT,
            TextAlign.CENTER: WD_ALIGN_PARAGRAPH.CENTER,
            TextAlign.RIGHT: WD_ALIGN_PARAGRAPH.RIGHT,
        }.get(table_cell.alignment, WD_ALIGN_PARAGRAPH.LEFT)
        if block_type in {"image", "math_image", "formula_image"}:
            text = text or str(block.get("url") or "[图片]")
        run = paragraph.add_run(text)
        run.font.size = _TABLE_FONT_SIZE
        run.font.name = _TABLE_FONT
        _set_east_asian(run, _TABLE_FONT_EA)


def _style_header_cell(word_cell: _Cell) -> None:
    for paragraph in word_cell.paragraphs:
        for run in paragraph.runs:
            run.bold = True
            run.font.size = _TABLE_HEADER_FONT_SIZE
    tc_pr = word_cell._tc.get_or_add_tcPr()
    shading = tc_pr.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        tc_pr.append(shading)
    shading.set(qn("w:fill"), "F2F2F2")
    shading.set(qn("w:val"), "clear")


def _set_table_borders(table: Table) -> None:
    tbl_pr = table._tbl.tblPr
    existing = tbl_pr.find(qn("w:tblBorders"))
    if existing is not None:
        tbl_pr.remove(existing)
    borders = OxmlElement("w:tblBorders")
    for border_name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = OxmlElement(f"w:{border_name}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "4")
        border.set(qn("w:space"), "0")
        border.set(qn("w:color"), "777777")
        borders.append(border)
    tbl_pr.append(borders)


def _keep_row_with_next(row) -> None:
    for cell in row.cells:
        for paragraph in cell.paragraphs:
            p_pr = paragraph._p.get_or_add_pPr()
            if p_pr.find(qn("w:keepWithNext")) is None:
                p_pr.append(OxmlElement("w:keepWithNext"))


def _prevent_row_break(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:cantSplit")) is None:
        tr_pr.append(OxmlElement("w:cantSplit"))


def _set_east_asian(run, font_name: str) -> None:
    rpr = run._r.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)


def _empty_table(doc: Document) -> Table:
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "(空表格)"
    return table
