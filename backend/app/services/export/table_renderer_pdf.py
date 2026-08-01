"""Render structured tables to PDF with rowspan/colspan geometry."""

from __future__ import annotations

import logging
import math

from app.services.export.table_model import TableBlock, TableCell, TextAlign

logger = logging.getLogger(__name__)

_TABLE_W_MM = 170.0
_CELL_PADDING = 1.2
_LINE_H = 4.0
_MIN_ROW_H = 6.0
_MAX_CELL_CHARS = 4000


def render_table_to_pdf(pdf, block: TableBlock) -> None:
    """Draw a native grid with merged cells and page-aware row groups."""
    if not block.rows or block.column_count <= 0:
        _render_fallback(pdf, block)
        return

    try:
        table_width = min(float(getattr(pdf, "epw", _TABLE_W_MM)), _TABLE_W_MM)
        left = float(getattr(pdf, "l_margin", pdf.get_x()))
        col_widths = _column_widths(block, table_width)
        row_heights = _row_heights(pdf, block, col_widths)

        if block.caption:
            pdf.set_font_size(8)
            pdf.multi_cell(table_width, 4.5, text=block.caption, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
            pdf.ln(1)

        header_end = _header_row_end(block)
        groups = _row_groups(block)
        first_group = True
        for start, end in groups:
            group_height = sum(row_heights[start:end])
            page_bottom = float(getattr(pdf, "page_break_trigger", pdf.h - pdf.b_margin))
            remaining = page_bottom - pdf.get_y()
            repeat_header = not first_group and header_end > 0 and start >= header_end
            header_height = sum(row_heights[:header_end]) if repeat_header else 0.0
            if remaining < group_height + header_height:
                pdf.add_page()
            if repeat_header:
                _draw_rows(pdf, block, 0, header_end, left, pdf.get_y(), col_widths, row_heights)
                pdf.set_y(pdf.get_y() + sum(row_heights[:header_end]))
            y = pdf.get_y()
            _draw_rows(pdf, block, start, end, left, y, col_widths, row_heights)
            pdf.set_y(y + group_height)
            first_group = False
        pdf.ln(2)
    except Exception:
        logger.warning("PDF structured-table rendering failed; using text fallback", exc_info=True)
        _render_fallback(pdf, block)


def _draw_rows(
    pdf,
    block: TableBlock,
    start: int,
    end: int,
    left: float,
    top: float,
    col_widths: list[float],
    row_heights: list[float],
) -> None:
    anchors = [anchor for anchor in block.iter_anchors() if start <= anchor[0] < end]
    for row, col, cell in anchors:
        cell_end = min(block.row_count, row + cell.row_span)
        if cell_end > end:
            # Row groups are span-closed; this guard prevents malformed input
            # from drawing across a page boundary.
            cell_end = end
        x = left + sum(col_widths[:col])
        y = top + sum(row_heights[start:row])
        width = sum(col_widths[col:min(block.column_count, col + cell.col_span)])
        height = sum(row_heights[row:cell_end])

        if cell.is_header:
            pdf.set_fill_color(242, 242, 242)
            pdf.rect(x, y, width, height, style="DF")
        else:
            pdf.rect(x, y, width, height)

        text = _cell_text(cell)[:_MAX_CELL_CHARS]
        if not text:
            continue
        old_x, old_y = pdf.get_x(), pdf.get_y()
        pdf.set_xy(x + _CELL_PADDING, y + _CELL_PADDING)
        pdf.set_font_size(8)
        align = {
            TextAlign.LEFT: "L",
            TextAlign.CENTER: "C",
            TextAlign.RIGHT: "R",
        }.get(cell.alignment, "L")
        pdf.multi_cell(
            max(1.0, width - 2 * _CELL_PADDING),
            _LINE_H,
            text=text,
            border=0,
            align=align,
            new_x="LEFT",
            new_y="NEXT",
            wrapmode="CHAR",
        )
        pdf.set_xy(old_x, old_y)


def _column_widths(block: TableBlock, table_width: float) -> list[float]:
    if len(block.column_widths) == block.column_count and sum(block.column_widths) > 0:
        weights = [max(0.05, float(value)) for value in block.column_widths]
    else:
        # Estimate from content while keeping columns within a practical range.
        weights = [1.0] * block.column_count
        for _row, col, cell in block.iter_anchors():
            per_col = max(1.0, min(8.0, math.sqrt(max(1, len(_cell_text(cell)))))) / cell.col_span
            for index in range(col, min(block.column_count, col + cell.col_span)):
                weights[index] = max(weights[index], per_col)
    total = sum(weights)
    return [table_width * weight / total for weight in weights]


def _row_heights(pdf, block: TableBlock, col_widths: list[float]) -> list[float]:
    heights = [_MIN_ROW_H for _ in range(block.row_count)]
    spanning: list[tuple[int, int, float]] = []
    for row, col, cell in block.iter_anchors():
        width = sum(col_widths[col:min(block.column_count, col + cell.col_span)])
        needed = _text_height(pdf, _cell_text(cell), max(1.0, width - 2 * _CELL_PADDING)) + 2 * _CELL_PADDING
        needed = max(_MIN_ROW_H, needed)
        if cell.row_span <= 1:
            heights[row] = max(heights[row], needed)
        else:
            spanning.append((row, min(block.row_count, row + cell.row_span), needed))
    for start, end, needed in spanning:
        current = sum(heights[start:end])
        if current < needed and end > start:
            heights[end - 1] += needed - current
    return heights


def _text_height(pdf, text: str, width: float) -> float:
    if not text:
        return _LINE_H
    lines = 0
    for source_line in str(text).splitlines() or [""]:
        if not source_line:
            lines += 1
            continue
        current_width = 0.0
        lines += 1
        for char in source_line:
            char_width = max(0.1, float(pdf.get_string_width(char)))
            if current_width + char_width > width and current_width > 0:
                lines += 1
                current_width = char_width
            else:
                current_width += char_width
    return max(1, lines) * _LINE_H


def _row_groups(block: TableBlock) -> list[tuple[int, int]]:
    groups: list[tuple[int, int]] = []
    row = 0
    anchors = list(block.iter_anchors())
    while row < block.row_count:
        end = row + 1
        changed = True
        while changed:
            changed = False
            for anchor_row, _col, cell in anchors:
                if row <= anchor_row < end:
                    candidate = min(block.row_count, anchor_row + cell.row_span)
                    if candidate > end:
                        end = candidate
                        changed = True
        groups.append((row, end))
        row = end
    return groups


def _header_row_end(block: TableBlock) -> int:
    end = 0
    for index, row in enumerate(block.rows):
        if row.cells and all(cell.is_header for cell in row.cells):
            end = index + 1
        else:
            break
    return end


def _cell_text(cell: TableCell) -> str:
    return cell.text


def _render_fallback(pdf, block: TableBlock) -> None:
    try:
        pdf.set_font_size(7)
    except Exception:
        pass
    for row in block.rows:
        texts = [_cell_text(cell) for cell in row.cells]
        pdf.multi_cell(
            min(float(getattr(pdf, "epw", _TABLE_W_MM)), _TABLE_W_MM),
            4,
            text=" | ".join(texts),
            new_x="LMARGIN",
            new_y="NEXT",
            wrapmode="CHAR",
        )
