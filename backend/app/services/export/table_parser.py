"""Parse canonical/legacy table data into :class:`TableBlock`."""

from __future__ import annotations

import json
import re
from typing import Any

from app.features.table_structure import (
    TABLE_SEGMENT_TYPE,
    restore_tables_from_source,
)
from app.services.export.table_model import TableBlock, TableCell, TableRow, TextAlign


def parse_markdown_table(md_text: str) -> list[TableBlock]:
    return [
        block
        for segment in restore_tables_from_source(md_text, source_format="markdown")
        if (block := _block_from_structured_segment(segment)) is not None
    ]


def parse_html_table(html_text: str) -> list[TableBlock]:
    return [
        block
        for segment in restore_tables_from_source(html_text, source_format="html")
        if (block := _block_from_structured_segment(segment)) is not None
    ]


def parse_segment_table(seg_data: dict) -> TableBlock | None:
    """Parse canonical ``table`` or legacy ``table_markdown`` segments."""
    if not isinstance(seg_data, dict):
        return None
    seg_type = str(seg_data.get("type") or "").lower()
    if seg_type == TABLE_SEGMENT_TYPE and isinstance(seg_data.get("rows"), list):
        return _block_from_structured_segment(seg_data)

    # Legacy segment.  The old detector wrote ``markdown`` while exporters
    # incorrectly read only ``text``; support both during migration.
    raw: Any = (
        seg_data.get("markdown")
        or seg_data.get("text")
        or seg_data.get("content")
        or ""
    )
    if isinstance(raw, dict):
        restored = restore_tables_from_source(raw, source_format="auto")
    else:
        text = str(raw).strip()
        if text.startswith("{"):
            try:
                raw = json.loads(text)
            except (ValueError, json.JSONDecodeError):
                raw = text
        restored = restore_tables_from_source(raw, source_format="auto")
    if not restored:
        return None
    return _block_from_structured_segment(restored[0])


def parse_table(source: str | dict, source_type: str = "auto") -> list[TableBlock]:
    """Parse one or more tables from canonical, Markdown, HTML or OCR text."""
    source_type = str(source_type or "auto").lower()
    if source_type == "segment" and isinstance(source, dict):
        block = parse_segment_table(source)
        return [block] if block else []
    if isinstance(source, dict):
        if source.get("type") in {TABLE_SEGMENT_TYPE, "table_markdown"}:
            block = parse_segment_table(source)
            return [block] if block else []
        restored = restore_tables_from_source(source, source_format=source_type)
    else:
        restored = restore_tables_from_source(
            str(source or ""), source_format=source_type
        )
    return [
        block
        for segment in restored
        if (block := _block_from_structured_segment(segment)) is not None
    ]


def _block_from_structured_segment(segment: dict) -> TableBlock | None:
    rows_data = segment.get("rows") or []
    if not isinstance(rows_data, list) or not rows_data:
        return None
    rows: list[TableRow] = []
    for row_data in rows_data:
        raw_cells = row_data.get("cells") if isinstance(row_data, dict) else row_data
        if not isinstance(raw_cells, list):
            continue
        cells: list[TableCell] = []
        for raw_cell in raw_cells:
            if isinstance(raw_cell, dict):
                content = raw_cell.get("content")
                if not isinstance(content, list):
                    content = [
                        {"type": "text", "text": str(raw_cell.get("text") or "")}
                    ]
                alignment = _text_align(
                    raw_cell.get("alignment") or raw_cell.get("align")
                )
                cells.append(
                    TableCell(
                        content=[
                            dict(item) for item in content if isinstance(item, dict)
                        ],
                        row_span=_safe_int(
                            raw_cell.get("row_span") or raw_cell.get("rowspan"), 1
                        ),
                        col_span=_safe_int(
                            raw_cell.get("col_span") or raw_cell.get("colspan"), 1
                        ),
                        is_header=bool(raw_cell.get("is_header")),
                        alignment=alignment,
                        bbox=list(raw_cell.get("bbox"))
                        if isinstance(raw_cell.get("bbox"), (list, tuple))
                        else None,
                        confidence=_safe_float(raw_cell.get("confidence"), 1.0),
                    )
                )
            else:
                cells.append(
                    TableCell(content=[{"type": "text", "text": str(raw_cell or "")}])
                )
        # Empty logical rows can be covered by a rowspan anchored above.
        rows.append(TableRow(cells=cells))
    if not rows:
        return None
    return TableBlock(
        rows=rows,
        caption=str(segment.get("caption") or ""),
        source_format=str(segment.get("source_format") or "structured"),
        confidence=_safe_float(segment.get("confidence"), 1.0),
        requires_review=bool(segment.get("requires_review")),
        source_pages=[
            int(page)
            for page in (segment.get("source_pages") or [])
            if str(page).isdigit()
        ],
        table_id=str(segment.get("table_id") or ""),
        column_widths=[
            float(v)
            for v in (segment.get("column_widths") or [])
            if isinstance(v, (int, float))
        ],
    )


def _text_align(value: Any) -> TextAlign:
    text = str(value or "").lower()
    if "center" in text:
        return TextAlign.CENTER
    if "right" in text:
        return TextAlign.RIGHT
    return TextAlign.LEFT


def _safe_int(value: Any, default: int) -> int:
    try:
        return max(1, int(value or default))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _looks_like_html(text: str) -> bool:
    return bool(re.search(r"<table\b", text or "", re.IGNORECASE))


def _looks_like_markdown(text: str) -> bool:
    return bool(re.search(r"^\s*\|.+\|\s*\n\s*\|[-:| ]+\|", text or "", re.MULTILINE))
