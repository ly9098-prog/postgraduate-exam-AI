"""Unified structured-table model shared by PDF and DOCX exporters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator


class TextAlign(Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


@dataclass
class TableCell:
    """A single logical cell. ``content`` uses the common segment contract."""

    content: list[dict] = field(default_factory=list)
    row_span: int = 1
    col_span: int = 1
    is_header: bool = False
    alignment: TextAlign = TextAlign.LEFT
    bbox: list[float] | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        self.row_span = max(1, int(self.row_span or 1))
        self.col_span = max(1, int(self.col_span or 1))

    def __bool__(self) -> bool:
        return bool(self.content)

    @property
    def text(self) -> str:
        parts: list[str] = []
        for block in self.content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "newline":
                parts.append("\n")
            else:
                value = block.get("text") or block.get("alt") or ""
                if value:
                    parts.append(str(value))
        return "".join(parts).strip()


@dataclass
class TableRow:
    cells: list[TableCell] = field(default_factory=list)


@dataclass
class TableBlock:
    """Format-agnostic table representation consumed by exporters."""

    rows: list[TableRow] = field(default_factory=list)
    caption: str = ""
    source_format: str = "unknown"
    confidence: float = 1.0
    requires_review: bool = False
    source_pages: list[int] = field(default_factory=list)
    table_id: str = ""
    column_widths: list[float] = field(default_factory=list)

    @property
    def column_count(self) -> int:
        max_cols = 0
        occupied: set[tuple[int, int]] = set()
        for row_idx, row in enumerate(self.rows):
            col = 0
            for cell in row.cells:
                while (row_idx, col) in occupied:
                    col += 1
                max_cols = max(max_cols, col + cell.col_span)
                for rr in range(row_idx, row_idx + cell.row_span):
                    for cc in range(col, col + cell.col_span):
                        occupied.add((rr, cc))
                col += cell.col_span
        return max_cols

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def has_header(self) -> bool:
        return any(c.is_header for r in self.rows for c in r.cells)

    def iter_anchors(self) -> Iterator[tuple[int, int, TableCell]]:
        """Yield logical cell anchors with span-aware grid coordinates."""
        occupied: set[tuple[int, int]] = set()
        for row_idx, row in enumerate(self.rows):
            col = 0
            for cell in row.cells:
                while (row_idx, col) in occupied:
                    col += 1
                yield row_idx, col, cell
                for rr in range(row_idx, row_idx + cell.row_span):
                    for cc in range(col, col + cell.col_span):
                        occupied.add((rr, cc))
                col += cell.col_span

    def occupancy_grid(self) -> list[list[tuple[int, int, TableCell] | None]]:
        columns = self.column_count
        grid: list[list[tuple[int, int, TableCell] | None]] = [
            [None for _ in range(columns)] for _ in range(self.row_count)
        ]
        for row, col, cell in self.iter_anchors():
            for rr in range(row, min(self.row_count, row + cell.row_span)):
                for cc in range(col, min(columns, col + cell.col_span)):
                    grid[rr][cc] = (row, col, cell)
        return grid

    @staticmethod
    def from_rows(headers: list[str], data: list[list[str]]) -> "TableBlock":
        block = TableBlock()
        if headers:
            block.rows.append(
                TableRow(
                    cells=[
                        TableCell(
                            content=[{"type": "text", "text": str(value)}],
                            is_header=True,
                        )
                        for value in headers
                    ]
                )
            )
        for row_data in data:
            block.rows.append(
                TableRow(
                    cells=[
                        TableCell(content=[{"type": "text", "text": str(value)}])
                        for value in row_data
                    ]
                )
            )
        return block

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "caption": self.caption,
            "source_format": self.source_format,
            "confidence": self.confidence,
            "requires_review": self.requires_review,
            "source_pages": self.source_pages,
            "column_count": self.column_count,
            "row_count": self.row_count,
            "has_header": self.has_header,
            "column_widths": self.column_widths,
            "rows": [
                {
                    "cells": [
                        {
                            "text": cell.text,
                            "content": cell.content,
                            "row_span": cell.row_span,
                            "col_span": cell.col_span,
                            "is_header": cell.is_header,
                            "alignment": cell.alignment.value,
                            "bbox": cell.bbox,
                            "confidence": cell.confidence,
                        }
                        for cell in row.cells
                    ]
                }
                for row in self.rows
            ],
        }
