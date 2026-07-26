"""Render ``TableBlock`` as a PDF table via fpdf2.

Provides basic 2D table rendering.  Merged cells are not supported
in PDF output (fpdf2 limitation) — the cell content is repeated
or the layout is simplified.  For full table capabilities use
the DOCX exporter.
"""

from __future__ import annotations

import logging

from app.services.export.table_model import TableBlock, TextAlign

logger = logging.getLogger(__name__)

# Max chars per cell before truncation
_MAX_CELL_CHARS = 200
# Max table width in mm
_TABLE_W_MM = 170


def render_table_to_pdf(pdf, block: TableBlock) -> None:
    """Render a ``TableBlock`` into a PDF document using fpdf2 table.

    Falls back to a simple multi-line text representation if the table
    is too complex or empty.
    """
    if not block.rows or block.column_count == 0:
        _render_fallback(pdf, block)
        return

    col_count = block.column_count
    col_w = _TABLE_W_MM / col_count

    try:
        # Build header + body data
        headers: list[str] = []
        body: list[list[str]] = []

        for row_idx, row in enumerate(block.rows):
            row_data: list[str] = []
            for cell in row.cells:
                text = _cell_text(cell)
                if cell.is_header and row_idx == 0:
                    headers.append(text)
                else:
                    row_data.append(text)

            if row_idx == 0 and headers:
                continue  # already captured
            if row_data:
                # Pad to column count
                while len(row_data) < col_count:
                    row_data.append("")
                body.append(row_data[:col_count])

        # Register table font if not done
        _ensure_font(pdf)

        # Render
        if headers:
            pdf.set_font("WenQuanYi", "B", 8)
            pdf.set_fill_color(232, 237, 242)
            pdf.cell(col_w, 6, headers[0], border=1, align="C", fill=True)
            for h in headers[1:]:
                pdf.cell(col_w, 6, h, border=1, align="C", fill=True)
            pdf.ln()

        pdf.set_font("WenQuanYi", "", 8)
        for row_data in body:
            for i, cell_text in enumerate(row_data):
                pdf.cell(col_w, 5.5, cell_text[:min(len(cell_text), _MAX_CELL_CHARS)], border=1, align="L")
            pdf.ln()

    except Exception:
        logger.warning("PDF table rendering failed, falling back to text")
        _render_fallback(pdf, block)


def _cell_text(cell) -> str:
    """Extract plain text from a TableCell."""
    texts = [
        b.get("text", "") for b in cell.content
        if b.get("type") == "text"
    ]
    return " ".join(texts)


def _ensure_font(pdf) -> None:
    """Register Chinese font if not already set."""
    try:
        pdf.set_font("WenQuanYi", "", 8)
    except Exception:
        pass


def _render_fallback(pdf, block: TableBlock) -> None:
    """Fallback: render table as plain text."""
    pdf.set_font("WenQuanYi", "", 7)
    pdf.set_text_color(100, 100, 100)
    for row in block.rows:
        texts = [_cell_text(c) for c in row.cells]
        pdf.multi_cell(_TABLE_W_MM, 4, text=" | ".join(texts), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
