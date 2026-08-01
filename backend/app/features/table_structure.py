"""Canonical structured-table recovery for OCR/import pipelines.

The old pipeline stored tables as Markdown strings.  Markdown is retained only
as a compatibility projection; the source of truth is now a versioned segment
with rows, cells, spans, confidence, source coordinates and audit metadata.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha1
from html import unescape
from html.parser import HTMLParser
import json
import math
import re
from typing import Any, Iterable

TABLE_SEGMENT_TYPE = "table"
TABLE_SCHEMA_VERSION = "table.v2"
_MAX_ROWS = 500
_MAX_COLUMNS = 100
_MAX_SOURCE_CHARS = 50_000

_OPTION_LINE_RE = re.compile(r"^\s*[A-Da-d]\s*[.．、:：)）]\s*")
_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+(?:\s*:?-{3,}:?\s*\|?)?\s*$")
_MULTI_SPACE_RE = re.compile(r"\t+| {2,}")
_NUMERIC_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)%?$")
_HEADER_RE = re.compile(
    r"进程|到达时间|服务时间|优先级|页号|块号|页框|Cache|标记|有效位|"
    r"修改位|访问位|路由|下一跳|目标网络|掩码|编码|哈夫曼|频率|权值|"
    r"学号|姓名|成绩|科目|分数|年份|项目|数值|总计|合计|输入|输出|"
    r"状态|结果|名称|类型|说明|序号|时间|地址|容量|长度|次数"
)


@dataclass(slots=True)
class RestoredTable:
    rows: list[dict]
    caption: str = ""
    confidence: float = 0.0
    source_format: str = "unknown"
    source_text: str = ""
    source_page: int = 1
    source_pages: list[int] = field(default_factory=list)
    bbox: list[float] | None = None
    coordinate_space: str | None = None
    region_id: str | None = None
    signals: list[str] = field(default_factory=list)
    requires_review: bool = False
    source_image_url: str | None = None
    continuation: dict | None = None

    def to_segment(self) -> dict:
        rows, column_count, issues = normalize_table_rows(self.rows)
        confidence = max(0.0, min(1.0, float(self.confidence or 0.0)))
        requires_review = bool(self.requires_review or issues or confidence < 0.65)
        source_pages = sorted(set(self.source_pages or [self.source_page]))
        segment: dict[str, Any] = {
            "type": TABLE_SEGMENT_TYPE,
            "schema_version": TABLE_SCHEMA_VERSION,
            "table_id": _table_id(rows, source_pages, self.bbox, self.region_id),
            "caption": self.caption.strip(),
            "rows": rows,
            "row_count": len(rows),
            "column_count": column_count,
            "has_header": any(
                bool(cell.get("is_header"))
                for row in rows for cell in row.get("cells", [])
            ),
            "source_format": self.source_format,
            "source_page": source_pages[0] if source_pages else self.source_page,
            "source_pages": source_pages,
            "bbox": self.bbox,
            "coordinate_space": self.coordinate_space,
            "region_id": self.region_id,
            "confidence": round(confidence, 3),
            "requires_review": requires_review,
            "signals": list(dict.fromkeys(self.signals + issues)),
            "markdown": rows_to_markdown(rows),
        }
        if self.source_text:
            segment["source_text"] = self.source_text[:_MAX_SOURCE_CHARS]
        if self.source_image_url:
            segment["source_image_url"] = self.source_image_url
        if self.continuation:
            segment["continuation"] = self.continuation
        return segment


def restore_tables_from_source(
    source: str | dict | list,
    *,
    source_page: int = 1,
    bbox: Iterable[float] | None = None,
    coordinate_space: str | None = None,
    confidence: float | None = None,
    region_id: str | None = None,
    source_format: str = "auto",
) -> list[dict]:
    """Restore zero or more canonical table segments from OCR/VL source data."""
    if isinstance(source, dict):
        return _restore_from_mapping(
            source,
            source_page=source_page,
            bbox=bbox,
            coordinate_space=coordinate_space,
            confidence=confidence,
            region_id=region_id,
            source_format=source_format,
        )
    if isinstance(source, list):
        table = _table_from_tokens(
            source,
            source_page=source_page,
            bbox=bbox,
            coordinate_space=coordinate_space,
            confidence=confidence,
            region_id=region_id,
        )
        return [table.to_segment()] if table else []

    text = str(source or "").strip()
    if not text:
        return []

    fmt = source_format.lower()
    restored: list[RestoredTable] = []
    if fmt in {"auto", "html", "vl_html"} and _looks_like_html_table(text):
        restored.extend(_parse_html_tables(text))
    if fmt in {"auto", "markdown", "vl_markdown"} and _looks_like_markdown_table(text):
        restored.extend(_parse_markdown_tables(text))
    if not restored and fmt in {"auto", "text", "ocr_text", "unknown"}:
        restored.extend(_parse_plain_text_tables(text))

    result: list[dict] = []
    for table in restored:
        table.source_page = source_page
        table.source_pages = [source_page]
        table.bbox = _coerce_bbox(bbox)
        table.coordinate_space = coordinate_space
        table.region_id = region_id
        if confidence is not None:
            table.confidence = min(table.confidence or 1.0, float(confidence))
        result.append(table.to_segment())
    return deduplicate_table_segments(result)


def _restore_from_mapping(
    data: dict,
    *,
    source_page: int,
    bbox: Iterable[float] | None,
    coordinate_space: str | None,
    confidence: float | None,
    region_id: str | None,
    source_format: str,
) -> list[dict]:
    # Canonical v2 segment: validate and normalize rather than reparsing.
    if data.get("type") == TABLE_SEGMENT_TYPE and isinstance(data.get("rows"), list):
        rows, column_count, issues = normalize_table_rows(data.get("rows") or [])
        result = dict(data)
        result.update({
            "type": TABLE_SEGMENT_TYPE,
            "schema_version": TABLE_SCHEMA_VERSION,
            "rows": rows,
            "row_count": len(rows),
            "column_count": column_count,
            "has_header": any(c.get("is_header") for r in rows for c in r.get("cells", [])),
            "markdown": rows_to_markdown(rows),
            "requires_review": bool(data.get("requires_review") or issues),
            "signals": list(dict.fromkeys(list(data.get("signals") or []) + issues)),
        })
        result.setdefault("table_id", _table_id(rows, result.get("source_pages") or [source_page], result.get("bbox"), result.get("region_id")))
        return [result]

    # Structured provider response: {rows:[{cells:[...]}]} or {headers, rows}.
    if isinstance(data.get("rows"), list):
        rows_value = data.get("rows") or []
        if rows_value and isinstance(rows_value[0], dict) and "cells" in rows_value[0]:
            table = RestoredTable(
                rows=rows_value,
                caption=str(data.get("caption") or ""),
                confidence=float(confidence if confidence is not None else data.get("confidence") or 0.9),
                source_format=source_format if source_format != "auto" else "structured",
                source_text=json.dumps(data, ensure_ascii=False)[:_MAX_SOURCE_CHARS],
                source_page=source_page,
                source_pages=list(data.get("source_pages") or [source_page]),
                bbox=_coerce_bbox(bbox or data.get("bbox")),
                coordinate_space=coordinate_space or data.get("coordinate_space"),
                region_id=region_id or data.get("region_id"),
                signals=["structured_rows"],
            )
            return [table.to_segment()]
        headers = data.get("headers") or []
        rows = _rows_from_matrix(headers, rows_value)
        if rows:
            return [RestoredTable(
                rows=rows,
                confidence=float(confidence if confidence is not None else data.get("confidence") or 0.85),
                source_format="structured_matrix",
                source_page=source_page,
                source_pages=[source_page],
                bbox=_coerce_bbox(bbox or data.get("bbox")),
                coordinate_space=coordinate_space or data.get("coordinate_space"),
                region_id=region_id or data.get("region_id"),
                signals=["headers_rows"],
            ).to_segment()]

    # Paddle/VL mappings can expose text under several keys and tokens/boxes.
    tokens = data.get("tokens") or data.get("cells") or data.get("ocr_tokens")
    if isinstance(tokens, list):
        token_table = _table_from_tokens(
            tokens,
            source_page=source_page,
            bbox=bbox or data.get("bbox"),
            coordinate_space=coordinate_space or data.get("coordinate_space"),
            confidence=confidence if confidence is not None else data.get("confidence"),
            region_id=region_id or data.get("region_id"),
        )
        if token_table:
            return [token_table.to_segment()]

    for key, fmt in (
        ("html", "html"),
        ("table_html", "html"),
        ("markdown", "markdown"),
        ("table_markdown", "markdown"),
        ("text", "auto"),
        ("content", "auto"),
    ):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            restored = restore_tables_from_source(
                value,
                source_page=source_page,
                bbox=bbox or data.get("bbox"),
                coordinate_space=coordinate_space or data.get("coordinate_space"),
                confidence=confidence if confidence is not None else data.get("confidence"),
                region_id=region_id or data.get("region_id"),
                source_format=fmt if source_format == "auto" else source_format,
            )
            if restored:
                return restored

    for key in ("table", "data", "structure"):
        nested = data.get(key)
        if isinstance(nested, (dict, list)) and nested is not data:
            restored = restore_tables_from_source(
                nested,
                source_page=source_page,
                bbox=bbox or data.get("bbox"),
                coordinate_space=coordinate_space or data.get("coordinate_space"),
                confidence=confidence if confidence is not None else data.get("confidence"),
                region_id=region_id or data.get("region_id"),
                source_format=source_format,
            )
            if restored:
                return restored

    raw = data.get("raw_block") or data.get("raw_data")
    if isinstance(raw, dict) and raw is not data:
        return _restore_from_mapping(
            raw,
            source_page=source_page,
            bbox=bbox or data.get("bbox"),
            coordinate_space=coordinate_space or data.get("coordinate_space"),
            confidence=confidence if confidence is not None else data.get("confidence"),
            region_id=region_id or data.get("region_id"),
            source_format=source_format,
        )
    return []


class _HTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self._stack: list[dict] = []
        self._cell: dict | None = None
        self._caption = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {str(k).lower(): v for k, v in attrs}
        if tag == "table":
            self._stack.append({"rows": [], "caption": "", "current_row": None})
        elif not self._stack:
            return
        elif tag == "caption":
            self._caption = True
        elif tag == "tr":
            self._stack[-1]["current_row"] = []
        elif tag in {"td", "th"}:
            self._cell = {
                "text_parts": [],
                "row_span": _safe_span(attrs_dict.get("rowspan")),
                "col_span": _safe_span(attrs_dict.get("colspan")),
                "is_header": tag == "th",
                "alignment": _alignment(attrs_dict.get("align") or attrs_dict.get("style")),
            }
        elif tag == "br" and self._cell is not None:
            self._cell["text_parts"].append("\n")
        elif tag == "img" and self._cell is not None:
            alt = attrs_dict.get("alt") or attrs_dict.get("title")
            if alt:
                self._cell["text_parts"].append(str(alt))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self._stack:
            return
        if tag in {"td", "th"} and self._cell is not None:
            row = self._stack[-1].get("current_row")
            if isinstance(row, list):
                text = _clean_cell_text("".join(self._cell.pop("text_parts", [])))
                row.append(_make_cell(
                    text,
                    row_span=self._cell.get("row_span", 1),
                    col_span=self._cell.get("col_span", 1),
                    is_header=self._cell.get("is_header", False),
                    alignment=self._cell.get("alignment", "left"),
                ))
            self._cell = None
        elif tag == "tr":
            row = self._stack[-1].get("current_row")
            if isinstance(row, list) and row:
                self._stack[-1]["rows"].append({"cells": row})
            self._stack[-1]["current_row"] = None
        elif tag == "caption":
            self._caption = False
        elif tag == "table":
            table = self._stack.pop()
            if table.get("rows"):
                self.tables.append(table)

    def handle_data(self, data: str) -> None:
        if not self._stack:
            return
        if self._cell is not None:
            self._cell["text_parts"].append(data)
        elif self._caption:
            self._stack[-1]["caption"] += data


def _parse_html_tables(text: str) -> list[RestoredTable]:
    parser = _HTMLTableParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return []
    result: list[RestoredTable] = []
    for data in parser.tables:
        rows = data.get("rows") or []
        if not rows:
            continue
        result.append(RestoredTable(
            rows=rows,
            caption=_clean_cell_text(data.get("caption") or ""),
            confidence=0.97,
            source_format="html",
            source_text=text,
            signals=["html_table", "span_attributes" if _has_spans(rows) else "html_grid"],
        ))
    return result


def _parse_markdown_tables(text: str) -> list[RestoredTable]:
    lines = text.splitlines()
    result: list[RestoredTable] = []
    index = 0
    while index < len(lines) - 1:
        if "|" not in lines[index] or not _SEPARATOR_RE.match(lines[index + 1]):
            index += 1
            continue
        header = _split_markdown_row(lines[index])
        alignments = _parse_markdown_alignments(lines[index + 1])
        body: list[list[str]] = []
        end = index + 2
        while end < len(lines) and "|" in lines[end] and lines[end].strip():
            body.append(_split_markdown_row(lines[end]))
            end += 1
        target = max([len(header), *[len(row) for row in body]] or [0])
        # Single-column markdown tables are valid (e.g. label/value lists); the
        # separator regex already filters out non-table pipe lines.
        if target >= 1:
            rows: list[dict] = [{"cells": [
                _make_cell(value, is_header=True, alignment=alignments[i] if i < len(alignments) else "left")
                for i, value in enumerate(_pad_row(header, target))
            ]}]
            for row in body:
                rows.append({"cells": [
                    _make_cell(value, alignment=alignments[i] if i < len(alignments) else "left")
                    for i, value in enumerate(_pad_row(row, target))
                ]})
            result.append(RestoredTable(
                rows=rows,
                confidence=0.94,
                source_format="markdown",
                source_text="\n".join(lines[index:end]),
                signals=["markdown_separator", f"columns:{target}"],
            ))
        index = max(end, index + 1)
    return result


def _parse_plain_text_tables(text: str) -> list[RestoredTable]:
    raw_lines = text.splitlines()
    parsed: list[tuple[int, list[str], str]] = []
    for idx, raw in enumerate(raw_lines):
        line = raw.strip()
        if not line or _OPTION_LINE_RE.match(line):
            parsed.append((idx, [], raw))
            continue
        cells = _split_plain_row(line)
        parsed.append((idx, cells, raw))

    windows: list[list[tuple[int, list[str], str]]] = []
    current: list[tuple[int, list[str], str]] = []
    for item in parsed:
        if len(item[1]) >= 2:
            current.append(item)
        else:
            if len(current) >= 2:
                windows.append(current)
            current = []
    if len(current) >= 2:
        windows.append(current)

    restored: list[RestoredTable] = []
    for window in windows:
        counts = Counter(len(cells) for _, cells, _ in window)
        target, frequency = counts.most_common(1)[0]
        if target < 2 or frequency < 2:
            continue
        kept = [item for item in window if abs(len(item[1]) - target) <= 1]
        if len(kept) < 2:
            continue
        numeric_rows = sum(
            1 for _, cells, _ in kept
            if sum(bool(_NUMERIC_RE.match(cell.strip())) for cell in cells) >= 1
        )
        header_hits = len(_HEADER_RE.findall(" ".join(kept[0][1])))
        consistency = frequency / max(len(window), 1)
        confidence = 0.35 + min(0.25, consistency * 0.25)
        if len(kept) >= 3:
            confidence += 0.10
        if header_hits:
            confidence += 0.15
        if numeric_rows >= 2:
            confidence += 0.10
        if target >= 3:
            confidence += 0.05
        confidence = min(confidence, 0.92)
        if confidence < 0.50:
            continue

        has_header = bool(header_hits or _infer_header(kept[0][1], [row[1] for row in kept[1:]]))
        rows: list[dict] = []
        for row_idx, (_, cells, _) in enumerate(kept):
            padded = _pad_row(cells, target)
            rows.append({"cells": [
                _make_cell(value, is_header=has_header and row_idx == 0)
                for value in padded
            ]})
        source_text = "\n".join(item[2] for item in kept)
        restored.append(RestoredTable(
            rows=rows,
            confidence=confidence,
            source_format="ocr_text",
            source_text=source_text,
            signals=[
                f"stable_columns:{target}",
                f"rows:{len(rows)}",
                f"numeric_rows:{numeric_rows}",
                f"header_hits:{header_hits}",
            ],
            requires_review=confidence < 0.72,
        ))
    return restored


def _table_from_tokens(
    tokens: list,
    *,
    source_page: int,
    bbox: Iterable[float] | None,
    coordinate_space: str | None,
    confidence: float | None,
    region_id: str | None,
) -> RestoredTable | None:
    normalized: list[dict] = []
    for item in tokens:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("value") or item.get("content") or "").strip()
        box = _coerce_bbox(item.get("bbox") or item.get("box") or item.get("rect"))
        if not text or not box:
            continue
        normalized.append({
            "text": text,
            "bbox": box,
            "confidence": _safe_float(item.get("confidence") or item.get("score"), 0.5),
            "cx": (box[0] + box[2]) / 2,
            "cy": (box[1] + box[3]) / 2,
            "height": max(1.0, box[3] - box[1]),
        })
    if len(normalized) < 4:
        return None

    normalized.sort(key=lambda token: (token["cy"], token["cx"]))
    median_h = sorted(token["height"] for token in normalized)[len(normalized) // 2]
    tolerance = max(4.0, median_h * 0.65)
    row_groups: list[list[dict]] = []
    for token in normalized:
        if not row_groups:
            row_groups.append([token])
            continue
        avg_y = sum(t["cy"] for t in row_groups[-1]) / len(row_groups[-1])
        if abs(token["cy"] - avg_y) <= tolerance:
            row_groups[-1].append(token)
        else:
            row_groups.append([token])
    row_groups = [sorted(group, key=lambda token: token["cx"]) for group in row_groups if len(group) >= 2]
    if len(row_groups) < 2:
        return None

    counts = Counter(len(group) for group in row_groups)
    target, frequency = counts.most_common(1)[0]
    if target < 2 or frequency < 2:
        return None
    row_groups = [group for group in row_groups if abs(len(group) - target) <= 1]
    has_header = _infer_header(
        [token["text"] for token in row_groups[0]],
        [[token["text"] for token in group] for group in row_groups[1:]],
    )
    rows: list[dict] = []
    for row_idx, group in enumerate(row_groups):
        cells = []
        for token in group:
            cells.append(_make_cell(
                token["text"],
                is_header=has_header and row_idx == 0,
                bbox=token["bbox"],
                confidence=token["confidence"],
            ))
        while len(cells) < target:
            cells.append(_make_cell(""))
        rows.append({"cells": cells[:target]})

    avg_conf = sum(token["confidence"] for group in row_groups for token in group) / sum(len(group) for group in row_groups)
    return RestoredTable(
        rows=rows,
        confidence=min(0.95, float(confidence) if confidence is not None else avg_conf),
        source_format="ocr_tokens",
        source_page=source_page,
        source_pages=[source_page],
        bbox=_coerce_bbox(bbox),
        coordinate_space=coordinate_space,
        region_id=region_id,
        signals=[f"token_rows:{len(rows)}", f"stable_columns:{target}"],
        requires_review=avg_conf < 0.7,
    )


def normalize_table_rows(rows: list[dict]) -> tuple[list[dict], int, list[str]]:
    """Normalize cells/spans and report structural issues."""
    normalized_rows: list[dict] = []
    issues: list[str] = []
    occupied: dict[tuple[int, int], bool] = {}
    max_col = 0

    for row_index, raw_row in enumerate((rows or [])[:_MAX_ROWS]):
        raw_cells = raw_row.get("cells") if isinstance(raw_row, dict) else raw_row
        if not isinstance(raw_cells, list):
            issues.append(f"invalid_row:{row_index}")
            continue
        cells: list[dict] = []
        col = 0
        for raw_cell in raw_cells[:_MAX_COLUMNS]:
            while occupied.get((row_index, col)):
                col += 1
            cell = _normalize_cell(raw_cell)
            row_span = cell["row_span"]
            col_span = cell["col_span"]
            if col + col_span > _MAX_COLUMNS:
                col_span = max(1, _MAX_COLUMNS - col)
                cell["col_span"] = col_span
                issues.append("column_limit_clamped")
            for rr in range(row_index, min(_MAX_ROWS, row_index + row_span)):
                for cc in range(col, min(_MAX_COLUMNS, col + col_span)):
                    if occupied.get((rr, cc)):
                        issues.append(f"span_overlap:{row_index}:{col}")
                    occupied[(rr, cc)] = True
            cell["grid_col"] = col
            cells.append(cell)
            col += col_span
            max_col = max(max_col, col)
        # Keep logical rows that are occupied only by a rowspan from an earlier
        # anchor.  Dropping them would shorten the grid and silently clamp the
        # merged cell during export.
        row_has_span_occupancy = any(
            occupied.get((row_index, column)) for column in range(max(max_col, 1))
        )
        if cells or row_has_span_occupancy:
            normalized_rows.append({"cells": cells})

    # A provider may omit trailing empty rows covered entirely by a rowspan.
    max_occupied_row = max((row for row, _column in occupied), default=-1)
    while len(normalized_rows) <= max_occupied_row and len(normalized_rows) < _MAX_ROWS:
        normalized_rows.append({"cells": []})

    if len(rows or []) > _MAX_ROWS:
        issues.append("row_limit_truncated")
    if max_col == 0 and normalized_rows:
        max_col = max(sum(cell.get("col_span", 1) for cell in row["cells"]) for row in normalized_rows)
    return normalized_rows, max_col, list(dict.fromkeys(issues))


def validate_table_segment(segment: dict) -> list[str]:
    if not isinstance(segment, dict) or segment.get("type") != TABLE_SEGMENT_TYPE:
        return ["not_table_segment"]
    rows, columns, issues = normalize_table_rows(segment.get("rows") or [])
    if not rows:
        issues.append("empty_table")
    if columns < 2:
        issues.append("too_few_columns")
    declared_rows = segment.get("row_count")
    if declared_rows is not None and declared_rows != len(rows):
        issues.append("row_count_mismatch")
    declared_cols = segment.get("column_count")
    if declared_cols is not None and declared_cols != columns:
        issues.append("column_count_mismatch")
    return list(dict.fromkeys(issues))


def rows_to_markdown(rows: list[dict]) -> str:
    normalized, column_count, _ = normalize_table_rows(rows)
    if not normalized or column_count < 1:
        return ""
    grid = _rows_to_text_grid(normalized, column_count)
    if not grid:
        return ""
    header_index = 0
    has_header = any(cell.get("is_header") for cell in normalized[0].get("cells", []))
    if not has_header:
        # Markdown requires a header row; use empty labels without changing the
        # canonical table's header semantics.
        grid = [[""] * column_count] + grid
        header_index = 0
    lines = ["| " + " | ".join(_escape_markdown_cell(v) for v in grid[header_index]) + " |"]
    lines.append("| " + " | ".join(["---"] * column_count) + " |")
    for row in grid[header_index + 1:]:
        lines.append("| " + " | ".join(_escape_markdown_cell(v) for v in row) + " |")
    return "\n".join(lines)


def deduplicate_table_segments(segments: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for segment in segments:
        fingerprint = table_fingerprint(segment)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(segment)
    return result


def table_fingerprint(segment: dict) -> str:
    payload = {
        "rows": segment.get("rows") or [],
        "source_pages": segment.get("source_pages") or [segment.get("source_page")],
        "region_id": segment.get("region_id"),
    }
    return sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:20]


def merge_continued_table_segments(segments: list[dict]) -> list[dict]:
    """Merge compatible consecutive-page tables within one question."""
    tables = [s for s in segments if s.get("type") == TABLE_SEGMENT_TYPE]
    others = [s for s in segments if s.get("type") != TABLE_SEGMENT_TYPE]
    if len(tables) < 2:
        return segments
    tables.sort(key=lambda s: (s.get("source_page") or 0, s.get("table_id") or ""))
    merged: list[dict] = []
    for table in tables:
        if not merged or not _can_merge_tables(merged[-1], table):
            merged.append(table)
            continue
        previous = merged[-1]
        prev_rows = list(previous.get("rows") or [])
        next_rows = list(table.get("rows") or [])
        if _same_header(prev_rows, next_rows):
            next_rows = next_rows[1:]
        previous["rows"] = prev_rows + next_rows
        pages = sorted(set((previous.get("source_pages") or []) + (table.get("source_pages") or [])))
        previous["source_pages"] = pages
        previous["row_count"] = len(previous["rows"])
        previous["confidence"] = round(min(float(previous.get("confidence") or 0), float(table.get("confidence") or 0)), 3)
        previous["requires_review"] = bool(previous.get("requires_review") or table.get("requires_review"))
        previous["continuation"] = {
            "merged": True,
            "parts": int((previous.get("continuation") or {}).get("parts", 1)) + 1,
        }
        previous["markdown"] = rows_to_markdown(previous["rows"])
        previous["table_id"] = _table_id(previous["rows"], pages, previous.get("bbox"), previous.get("region_id"))
    return others + merged


def _can_merge_tables(first: dict, second: dict) -> bool:
    pages_a = first.get("source_pages") or [first.get("source_page") or 0]
    pages_b = second.get("source_pages") or [second.get("source_page") or 0]
    if not (
        first.get("column_count") == second.get("column_count")
        and max(pages_a) + 1 == min(pages_b)
        and first.get("column_count", 0) >= 2
    ):
        return False

    explicit = bool(
        (first.get("continuation") or {}).get("continues_to_next")
        or (second.get("continuation") or {}).get("continued_from_previous")
        or "continued_table" in (first.get("signals") or [])
        or "continued_table" in (second.get("signals") or [])
    )
    if explicit or _same_header(first.get("rows") or [], second.get("rows") or []):
        return True

    caption_a = str(first.get("caption") or "").strip()
    caption_b = str(second.get("caption") or "").strip()
    if caption_a and caption_b and caption_a == caption_b:
        return True

    # No explicit continuation marker, no repeated header and no matching
    # caption: do not merge on coordinates alone, otherwise two unrelated
    # tables that happen to sit at the bottom/top of adjacent pages would be
    # spliced into one and corrupt question content.
    return False


def _same_header(first_rows: list[dict], second_rows: list[dict]) -> bool:
    if not first_rows or not second_rows:
        return False
    first = [_cell_text(c) for c in first_rows[0].get("cells", [])]
    second = [_cell_text(c) for c in second_rows[0].get("cells", [])]
    return first == second and any(first)


def _rows_to_text_grid(rows: list[dict], column_count: int) -> list[list[str]]:
    grid = [["" for _ in range(column_count)] for _ in range(len(rows))]
    for row_idx, row in enumerate(rows):
        for cell in row.get("cells", []):
            col = int(cell.get("grid_col", 0))
            text = _cell_text(cell)
            for rr in range(row_idx, min(len(rows), row_idx + int(cell.get("row_span", 1)))):
                for cc in range(col, min(column_count, col + int(cell.get("col_span", 1)))):
                    if rr == row_idx and cc == col:
                        grid[rr][cc] = text
    return grid


def _normalize_cell(raw: Any) -> dict:
    if isinstance(raw, dict):
        content = raw.get("content")
        text = raw.get("text")
        if not isinstance(content, list):
            content = [{"type": "text", "text": str(text or raw.get("value") or "")}]
        clean_content = []
        for block in content:
            if isinstance(block, dict):
                item = dict(block)
                if item.get("type") == "text":
                    item["text"] = _clean_cell_text(item.get("text") or "")
                clean_content.append(item)
        return {
            "content": clean_content,
            "text": _content_text(clean_content),
            "row_span": _safe_span(raw.get("row_span") or raw.get("rowspan")),
            "col_span": _safe_span(raw.get("col_span") or raw.get("colspan")),
            "is_header": bool(raw.get("is_header")),
            "alignment": _alignment(raw.get("alignment") or raw.get("align")),
            "bbox": _coerce_bbox(raw.get("bbox")),
            "confidence": round(_safe_float(raw.get("confidence"), 1.0), 3),
        }
    return _make_cell(str(raw or ""))


def _make_cell(
    text: str,
    *,
    row_span: int = 1,
    col_span: int = 1,
    is_header: bool = False,
    alignment: str = "left",
    bbox: Iterable[float] | None = None,
    confidence: float = 1.0,
) -> dict:
    text = _clean_cell_text(text)
    return {
        "content": [{"type": "text", "text": text}],
        "text": text,
        "row_span": _safe_span(row_span),
        "col_span": _safe_span(col_span),
        "is_header": bool(is_header),
        "alignment": _alignment(alignment),
        "bbox": _coerce_bbox(bbox),
        "confidence": round(_safe_float(confidence, 1.0), 3),
    }


def _rows_from_matrix(headers: list, data: list) -> list[dict]:
    width = max([len(headers) if isinstance(headers, list) else 0, *[len(row) for row in data if isinstance(row, list)]] or [0])
    if width < 2:
        return []
    rows: list[dict] = []
    if headers:
        rows.append({"cells": [_make_cell(str(value), is_header=True) for value in _pad_row(list(headers), width)]})
    for row in data:
        if isinstance(row, list):
            rows.append({"cells": [_make_cell(str(value)) for value in _pad_row(row, width)]})
    return rows


def _split_plain_row(line: str) -> list[str]:
    if line.startswith("|") and line.endswith("|"):
        return _split_markdown_row(line)
    if "\t" in line:
        # Tabs are explicit delimiters; preserve interior empty cells.
        return _trim_outer_empty_cells([_clean_cell_text(part) for part in line.split("\t")])
    if re.search(r" {2,}", line):
        return [_clean_cell_text(part) for part in re.split(r" {2,}", line.strip())]
    # Unicode/ASCII box separators are high-confidence table delimiters.
    if any(sep in line for sep in ("│", "┃", "｜")):
        return _trim_outer_empty_cells([
            _clean_cell_text(part) for part in re.split(r"[│┃｜]", line)
        ])
    return []


def _trim_outer_empty_cells(cells: list[str]) -> list[str]:
    while cells and not cells[0]:
        cells = cells[1:]
    while cells and not cells[-1]:
        cells = cells[:-1]
    return cells


def _split_markdown_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|") and not value.endswith("\\|"):
        value = value[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
            current.append(char)
        elif char == "|":
            cells.append(_clean_cell_text("".join(current).replace("\\|", "|")))
            current = []
        else:
            current.append(char)
    cells.append(_clean_cell_text("".join(current).replace("\\|", "|")))
    return cells


def _parse_markdown_alignments(line: str) -> list[str]:
    parts = _split_markdown_row(line)
    result = []
    for part in parts:
        stripped = part.strip()
        if stripped.startswith(":") and stripped.endswith(":"):
            result.append("center")
        elif stripped.endswith(":"):
            result.append("right")
        else:
            result.append("left")
    return result


def _infer_header(first: list[str], following: list[list[str]]) -> bool:
    if not first:
        return False
    if _HEADER_RE.search(" ".join(first)):
        return True
    first_numeric = sum(bool(_NUMERIC_RE.match(value)) for value in first)
    later_numeric = sum(bool(_NUMERIC_RE.match(value)) for row in following[:3] for value in row)
    return first_numeric == 0 and later_numeric >= max(2, len(first))


def _has_spans(rows: list[dict]) -> bool:
    return any(
        int(cell.get("row_span", 1)) > 1 or int(cell.get("col_span", 1)) > 1
        for row in rows for cell in row.get("cells", [])
    )


def _table_id(rows: list[dict], pages: list, bbox: Any, region_id: Any) -> str:
    payload = json.dumps({"rows": rows, "pages": pages, "bbox": bbox, "region": region_id}, ensure_ascii=False, sort_keys=True, default=str)
    return f"tbl_{sha1(payload.encode()).hexdigest()[:16]}"


def _cell_text(cell: dict) -> str:
    return str(cell.get("text") or _content_text(cell.get("content") or []))


def _content_text(content: list[dict]) -> str:
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "newline":
            parts.append("\n")
        else:
            value = block.get("text") or block.get("alt") or ""
            if value:
                parts.append(str(value))
    return "".join(parts).strip()


def _clean_cell_text(value: Any) -> str:
    text = unescape(str(value or "")).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def _alignment(value: Any) -> str:
    text = str(value or "").lower()
    if "center" in text:
        return "center"
    if "right" in text:
        return "right"
    return "left"


def _safe_span(value: Any) -> int:
    try:
        return max(1, min(_MAX_COLUMNS, int(value or 1)))
    except (TypeError, ValueError):
        return 1


def _safe_float(value: Any, default: float) -> float:
    try:
        result = float(value)
        return default if math.isnan(result) or math.isinf(result) else result
    except (TypeError, ValueError):
        return default


def _coerce_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)):
        return None
    if len(value) == 8:
        try:
            xs = [float(value[i]) for i in range(0, 8, 2)]
            ys = [float(value[i]) for i in range(1, 8, 2)]
            return [min(xs), min(ys), max(xs), max(ys)]
        except (TypeError, ValueError):
            return None
    if len(value) != 4:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _looks_like_html_table(text: str) -> bool:
    return bool(re.search(r"<table\b", text, re.I))


def _looks_like_markdown_table(text: str) -> bool:
    lines = text.splitlines()
    return any(index + 1 < len(lines) and "|" in line and _SEPARATOR_RE.match(lines[index + 1]) for index, line in enumerate(lines))


def _pad_row(row: list, width: int) -> list[str]:
    values = [str(value or "") for value in row[:width]]
    return values + [""] * max(0, width - len(values))


def _escape_markdown_cell(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")
