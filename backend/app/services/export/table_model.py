"""Unified table data model shared by PDF and DOCX exporters.

``TableBlock`` is the format-agnostic representation consumed by both exporters.
Parsers in ``table_parser.py`` convert Markdown / HTML / segment-table data
into this model; renderers in each exporter convert it to the output format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TextAlign(Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


@dataclass
class TableCell:
    """A single cell in a table."""
    content: list[dict] = field(default_factory=list)
    row_span: int = 1
    col_span: int = 1
    is_header: bool = False
    alignment: TextAlign = TextAlign.LEFT

    def __bool__(self) -> bool:
        return bool(self.content)


@dataclass
class TableRow:
    """A single row in a table."""
    cells: list[TableCell] = field(default_factory=list)


@dataclass
class TableBlock:
    """Format-agnostic intermediate table representation."""
    rows: list[TableRow] = field(default_factory=list)
    caption: str = ""

    @property
    def column_count(self) -> int:
        return max(len(r.cells) for r in self.rows) if self.rows else 0

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def has_header(self) -> bool:
        return any(c.is_header for r in self.rows for c in r.cells)

    @staticmethod
    def from_rows(headers: list[str], data: list[list[str]]) -> TableBlock:
        """Build a simple table from header + data lists."""
        block = TableBlock()
        if headers:
            header_row = TableRow(
                cells=[TableCell(
                    content=[{"type": "text", "text": h}],
                    is_header=True,
                ) for h in headers]
            )
            block.rows.append(header_row)
        for row_data in data:
            row = TableRow(
                cells=[TableCell(
                    content=[{"type": "text", "text": str(c)}],
                ) for c in row_data]
            )
            block.rows.append(row)
        return block

    def to_dict(self) -> dict[str, Any]:
        """Serialise to dict for snapshot / test assertion use."""
        return {
            "caption": self.caption,
            "column_count": self.column_count,
            "row_count": self.row_count,
            "has_header": self.has_header,
            "rows": [
                {
                    "cells": [
                        {
                            "text": "".join(
                                b.get("text", "") for b in c.content
                                if b.get("type") == "text"
                            ),
                            "row_span": c.row_span,
                            "col_span": c.col_span,
                            "is_header": c.is_header,
                            "alignment": c.alignment.value,
                        }
                        for c in r.cells
                    ]
                }
                for r in self.rows
            ],
        }
