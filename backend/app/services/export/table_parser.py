"""Parse Markdown / HTML / segment-table data into ``TableBlock``.

Each parser function returns ``list[TableBlock]`` (a document can contain
multiple tables).  The exporters iterate over tables and render each one.
"""

from __future__ import annotations

import logging
import re

from app.services.export.table_model import TableBlock, TableCell, TableRow, TextAlign

logger = logging.getLogger(__name__)

# ── Markdown table regex ──────────────────────────────────────────────
# Captures the full table block including separator line.
_MD_TABLE_RE = re.compile(
    r"^\|(.+)\|\n\|([-:| ]+)\|\n((?:\|.*\|\n?)*)",
    re.MULTILINE,
)

_MD_CELL_SPLIT = re.compile(r"(?<!\\)\|")


def parse_markdown_table(md_text: str) -> list[TableBlock]:
    """Parse 0+ markdown tables from *md_text*.

    Handles:
    - Leading/trailing pipes
    - Alignment markers (---, :---, ---:, :---:)
    - Cell content with inline formatting markers
    """
    blocks: list[TableBlock] = []

    for match in _MD_TABLE_RE.finditer(md_text):
        block = TableBlock()
        header_line = match.group(1)
        separator_line = match.group(2)
        body_text = match.group(3)

        # Determine alignment from separator
        alignments = _parse_alignments(separator_line)

        # Header row
        headers = _split_cells(header_line)
        if headers:
            header_row = TableRow(cells=[
                TableCell(
                    content=[{"type": "text", "text": h.strip()}],
                    is_header=True,
                    alignment=alignments[i] if i < len(alignments) else TextAlign.LEFT,
                )
                for i, h in enumerate(headers)
            ])
            block.rows.append(header_row)

        # Body rows — handle each line individually
        for line in body_text.strip().split("\n"):
            line = line.strip()
            if not line or not line.startswith("|"):
                continue
            cells_text = _split_cells(line)
            if not cells_text:
                continue
            row = TableRow(cells=[
                TableCell(
                    content=[{"type": "text", "text": c.strip()}],
                    alignment=alignments[i] if i < len(alignments) else TextAlign.LEFT,
                )
                for i, c in enumerate(cells_text)
            ])
            block.rows.append(row)

        if block.rows:
            blocks.append(block)

    return blocks


def _split_cells(line: str) -> list[str]:
    """Split a pipe-delimited row line into cells."""
    parts = _MD_CELL_SPLIT.split(line)
    # First and last may be empty due to leading/trailing pipes
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def _parse_alignments(separator: str) -> list[TextAlign]:
    """Parse alignment from markdown separator line (e.g. ``:---``, ``:---:``)."""
    alignments: list[TextAlign] = []
    for part in separator.split("|"):
        part = part.strip()
        if not part:
            continue
        if part.startswith(":") and part.endswith(":"):
            alignments.append(TextAlign.CENTER)
        elif part.endswith(":"):
            alignments.append(TextAlign.RIGHT)
        else:
            alignments.append(TextAlign.LEFT)
    return alignments


# ── HTML table parsing ─────────────────────────────────────────────────
# Simple parser — does NOT run a full HTML parser.  Handles the subset
# produced by the admin / import pipeline.

_HTML_TABLE_RE = re.compile(
    r"<table[^>]*>(.*?)</table\s*>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_ROW_RE = re.compile(
    r"<tr[^>]*>(.*?)</tr\s*>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_CELL_RE = re.compile(
    r"<(th|td)[^>]*>(.*?)</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_ATTR_RE = re.compile(
    r'\b(rowspan|colspan|align)\s*=\s*"([^"]*)"',
    re.IGNORECASE,
)


def parse_html_table(html_text: str) -> list[TableBlock]:
    """Parse 0+ HTML tables from *html_text*.

    Supports:
    - ``<table>``, ``<tr>``, ``<th>``, ``<td>``
    - ``rowspan``, ``colspan`` attributes
    - ``align`` attribute on cells
    """
    blocks: list[TableBlock] = []

    for table_match in _HTML_TABLE_RE.finditer(html_text):
        block = TableBlock()
        inner = table_match.group(1)

        for row_match in _HTML_ROW_RE.finditer(inner):
            row_html = row_match.group(1)
            cells: list[TableCell] = []

            for cell_match in _HTML_CELL_RE.finditer(row_html):
                tag = cell_match.group(1).lower()
                cell_content = cell_match.group(2).strip()
                is_header = tag == "th"

                # Parse attributes
                row_span = 1
                col_span = 1
                alignment = TextAlign.LEFT

                for attr_match in _HTML_ATTR_RE.finditer(cell_match.group(0)):
                    attr_name = attr_match.group(1).lower()
                    attr_val = attr_match.group(2).lower()
                    if attr_name == "rowspan":
                        row_span = max(1, int(attr_val))
                    elif attr_name == "colspan":
                        col_span = max(1, int(attr_val))
                    elif attr_name == "align":
                        alignment = {
                            "left": TextAlign.LEFT,
                            "center": TextAlign.CENTER,
                            "right": TextAlign.RIGHT,
                        }.get(attr_val, TextAlign.LEFT)

                # Strip inner HTML tags from content
                content = re.sub(r"<[^>]+>", "", cell_content)

                cells.append(TableCell(
                    content=[{"type": "text", "text": content}],
                    row_span=row_span,
                    col_span=col_span,
                    is_header=is_header,
                    alignment=alignment,
                ))

            if cells:
                block.rows.append(TableRow(cells=cells))

        if block.rows:
            blocks.append(block)

    return blocks


# ── Segment-table parsing ──────────────────────────────────────────────

def parse_segment_table(seg_data: dict) -> TableBlock | None:
    """Parse a *segment* dict whose ``type`` is ``table_markdown``.

    The segment may contain raw markdown (``text`` key), a structured
    table dict with ``headers`` / ``rows`` keys, or a rich-text JSON
    table representation.
    """
    text = seg_data.get("text") or ""

    # Handle dict/structured text inline
    if isinstance(text, dict):
        data = text
        if "rows" in data or "headers" in data:
            return TableBlock.from_rows(
                headers=data.get("headers", []),
                data=data.get("rows", []),
            )
        return None

    # Handle JSON string representation
    raw = str(text).strip()
    if raw.startswith("{"):
        data = _try_json(raw)
        if data and ("rows" in data or "headers" in data):
            return TableBlock.from_rows(
                headers=data.get("headers", []),
                data=data.get("rows", []),
            )

    if not raw:
        return None

    # Try markdown-formatted text
    blocks = parse_markdown_table(raw)
    if blocks:
        return blocks[0]

    # Try HTML table
    html_blocks = parse_html_table(raw)
    return html_blocks[0] if html_blocks else None


def _try_json(text: str) -> dict | None:
    """Attempt to parse text as JSON."""
    import json
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


# ── Auto-detect ────────────────────────────────────────────────────────

def parse_table(source: str | dict, source_type: str = "auto") -> list[TableBlock]:
    """Parse a table from any supported source format.

    Args:
        source: The raw text or dict.
        source_type: ``"auto"``, ``"markdown"``, ``"html"``, or ``"segment"``.

    Returns:
        A (possibly empty) list of ``TableBlock``.
    """
    if source_type == "segment":
        if isinstance(source, dict):
            block = parse_segment_table(source)
            return [block] if block else []
        return []

    text = source if isinstance(source, str) else (source.get("text", "") if isinstance(source, dict) else str(source))

    if source_type == "html" or _looks_like_html(text):
        return parse_html_table(text)

    if source_type == "markdown" or _looks_like_markdown(text):
        return parse_markdown_table(text)

    # Auto: try markdown first, then html
    return parse_markdown_table(text) or parse_html_table(text)


def _looks_like_html(text: str) -> bool:
    return bool(re.search(r"<table[^>]*>", text, re.IGNORECASE))


def _looks_like_markdown(text: str) -> bool:
    return bool(re.search(r"^\|.+\|\n\|[-:| ]+\|", text, re.MULTILINE))
