"""Render ``TableBlock`` as a native Word table (``w:tbl``) via python-docx.

Maps our intermediate model to python-docx table API with Open XML
fallback for features missing from the high-level API (merged cells).
"""

from __future__ import annotations

import logging

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.table import Table, _Cell

from app.services.export.table_model import TableBlock, TableCell, TextAlign

logger = logging.getLogger(__name__)

# Maximum table width as fraction of body width
_TABLE_WIDTH_FRAC = 0.95

# Font for table content
_TABLE_FONT = "SimSun"
_TABLE_FONT_EA = "SimSun"
_TABLE_FONT_SIZE = Pt(9)
_TABLE_HEADER_FONT_SIZE = Pt(9)

# Default column width (will be auto-distributed)
_DEFAULT_COL_CM = 3.0


def render_table_to_docx(doc: Document, block: TableBlock, body_width_cm: float = 17.0) -> Table:
    """Render a ``TableBlock`` into *doc* as a native Word table.

    Returns the ``python-docx`` Table so callers can apply additional
    formatting if needed.
    """
    if not block.rows:
        logger.warning("Skipping empty table block")
        return _empty_table(doc)

    row_count = len(block.rows)
    col_count = block.column_count
    if col_count == 0:
        return _empty_table(doc)

    # ── Create table via python-docx ──
    table = doc.add_table(rows=row_count, cols=col_count)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Apply borders
    _set_table_borders(table)

    # Set column widths (proportional distribution across body width)
    table_width_cm = body_width_cm * _TABLE_WIDTH_FRAC
    col_width_cm = table_width_cm / col_count
    for col_idx in range(col_count):
        for row in table.rows:
            if col_idx < len(row.cells):
                cell = row.cells[col_idx]
                cell.width = Cm(col_width_cm)

    # ── Fill cells ──
    # Track which cells are already consumed by rowspan/colspan
    consumed: set[tuple[int, int]] = set()

    for row_idx, table_row in enumerate(block.rows):
        col_offset = 0
        for cell_idx, table_cell in enumerate(table_row.cells):
            # Skip consumed positions
            while (row_idx, col_offset) in consumed:
                col_offset += 1

            if col_offset >= col_count:
                break

            word_cell = table.cell(row_idx, col_offset)

            # ── Handle merged cells ──
            needs_merge = table_cell.col_span > 1 or table_cell.row_span > 1
            if needs_merge:
                end_row = min(row_idx + table_cell.row_span - 1, row_count - 1)
                end_col = min(col_offset + table_cell.col_span - 1, col_count - 1)
                if end_row > row_idx or end_col > col_offset:
                    merge_cell = table.cell(end_row, end_col)
                    word_cell.merge(merge_cell)

                # Mark consumed
                for r in range(row_idx, end_row + 1):
                    for c in range(col_offset, end_col + 1):
                        consumed.add((r, c))

            # ── Fill cell content ──
            _fill_cell(word_cell, table_cell)

            col_offset += table_cell.col_span

    # ── Style header row ──
    if block.has_header:
        for cell in table.rows[0].cells:
            _style_header_cell(cell)

    # ── Keep table rows together where possible ──
    for row in table.rows:
        _keep_row_with_next(row)

    # Disable "allow row to break across pages" for all rows
    for row in table.rows:
        _prevent_row_break(row)

    # Normalise merged-cell XML (gridSpan / vMerge)
    _ensure_merge_xml(table)

    return table


def _fill_cell(word_cell: _Cell, table_cell: TableCell) -> None:
    """Write content blocks into a Word table cell."""
    # Clear default empty paragraph
    word_cell.text = ""

    for block in table_cell.content:
        text = (block.get("text") or "").strip()
        if not text:
            continue

        p = word_cell.add_paragraph()
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.line_spacing = 1.15

        # Alignment
        align_map = {
            TextAlign.LEFT: WD_ALIGN_PARAGRAPH.LEFT,
            TextAlign.CENTER: WD_ALIGN_PARAGRAPH.CENTER,
            TextAlign.RIGHT: WD_ALIGN_PARAGRAPH.RIGHT,
        }
        p.alignment = align_map.get(table_cell.alignment, WD_ALIGN_PARAGRAPH.LEFT)

        run = p.add_run(text)
        run.font.size = _TABLE_FONT_SIZE
        run.font.name = _TABLE_FONT
        _set_east_asian(run, _TABLE_FONT_EA)


def _style_header_cell(word_cell: _Cell) -> None:
    """Apply bold + shading to header cells."""
    for paragraph in word_cell.paragraphs:
        for run in paragraph.runs:
            run.bold = True
            run.font.size = _TABLE_HEADER_FONT_SIZE

    # Shading via Open XML
    tc_pr = word_cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), "E8EDF2")
    shading.set(qn("w:val"), "clear")
    tc_pr.append(shading)


def _set_table_borders(table: Table) -> None:
    """Add visible borders to all cells."""
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for border_name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = OxmlElement(f"w:{border_name}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "4")
        border.set(qn("w:space"), "0")
        border.set(qn("w:color"), "999999")
        borders.append(border)
    tbl_pr.append(borders)


def _keep_row_with_next(row) -> None:
    """Add ``keepWithNext`` to each cell in the row, avoiding duplication."""
    from docx.oxml import OxmlElement
    for cell in row.cells:
        for p in cell.paragraphs:
            pPr = p._p.get_or_add_pPr()
            # Check if keepWithNext already exists
            existing = pPr.findall(qn("w:keepWithNext"))
            if not existing:
                keep = OxmlElement("w:keepWithNext")
                pPr.append(keep)


def _prevent_row_break(row) -> None:
    """Add ``w:cantSplit`` to row properties (``w:trPr``).

    This is the correct Open XML to prevent a table row from breaking
    across pages.  The previous implementation incorrectly used
    ``w:vAlign=center`` which does not prevent row breaks.
    """
    tr_pr = row._tr.get_or_add_trPr()
    # Check if cantSplit already exists
    existing = tr_pr.findall(qn("w:cantSplit"))
    if not existing:
        cant_split = OxmlElement("w:cantSplit")
        tr_pr.append(cant_split)


def _set_east_asian(run, font_name: str) -> None:
    """Set the East-Asian font on a run."""
    rpr = run._r.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)


def _ensure_merge_xml(table) -> None:
    """Normalise merged-cell XML for proper gridSpan / vMerge.

    python-docx's ``cell.merge()`` may not produce correct
    ``w:gridSpan`` / ``w:vMerge`` in all cases.  This helper scans
    the table and ensures merged cells have the right attributes.
    """
    from docx.oxml import OxmlElement
    for row_idx, row in enumerate(table.rows):
        for cell_idx, cell in enumerate(row.cells):
            tc = cell._tc
            tc_pr = tc.get_or_add_tcPr()

            # Detect merged cell by checking the tc element's gridSpan attribute
            # If python-docx already set gridSpan, verify it
            grid_span = tc_pr.find(qn("w:gridSpan"))
            if grid_span is not None:
                val = int(grid_span.get(qn("w:val"), "0"))
                if val < 2:
                    tc_pr.remove(grid_span)

            # Detect horizontal continuation cells (empty placeholders from merge)
            # These typically have w:vMerge/continue, no content
            v_merge = tc_pr.find(qn("w:vMerge"))
            if v_merge is not None:
                val = v_merge.get(qn("w:val"), "continue") if v_merge is not None else None


def _empty_table(doc: Document) -> Table:
    """Create a minimal 1×1 table with placeholder text."""
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "(空表格)"
    return table
