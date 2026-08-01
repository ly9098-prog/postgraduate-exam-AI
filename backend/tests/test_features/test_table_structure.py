"""Tests for canonical table restoration (table_structure.py)."""

from __future__ import annotations

from app.features.table_structure import (
    merge_continued_table_segments,
    restore_tables_from_source,
)


def _segment(column_count: int, page: int, rows, **extra):
    base = {
        "type": "table",
        "schema_version": "table.v2",
        "rows": rows,
        "column_count": column_count,
        "row_count": len(rows),
        "source_pages": [page],
        "source_page": page,
        "signals": [],
        **extra,
    }
    return base


def _row(*texts):
    return {"cells": [{"text": t} for t in texts]}


class TestMarkdownRestore:
    def test_single_column_markdown(self):
        """P1 regression: single-column markdown tables must not be dropped."""
        tables = restore_tables_from_source("| H |\n|---|\n| v |", source_format="auto")
        assert len(tables) == 1
        assert tables[0]["column_count"] == 1
        assert tables[0]["row_count"] == 2

    def test_two_column_markdown(self):
        tables = restore_tables_from_source(
            "| 进程 | 时间 |\n|------|------|\n| P1 | 0 |", source_format="auto"
        )
        assert len(tables) == 1
        assert tables[0]["column_count"] == 2

    def test_html_rowspan_colspan(self):
        tables = restore_tables_from_source(
            '<table><tr><td colspan="2" rowspan="2">M</td></tr></table>',
            source_format="html",
        )
        assert len(tables) == 1
        cell = tables[0]["rows"][0]["cells"][0]
        assert cell["row_span"] == 2
        assert cell["col_span"] == 2


class TestMergeContinuedTableSegments:
    def test_coordinate_only_adjacent_pages_do_not_merge(self):
        """P2 regression: position alone must not splice unrelated tables."""
        first = _segment(
            2,
            1,
            [_row("甲", "乙")],
            bbox=[0, 100, 100, 900],
            coordinate_space="normalized_1000",
        )
        second = _segment(
            2,
            2,
            [_row("丙", "丁")],
            bbox=[0, 50, 100, 800],
            coordinate_space="normalized_1000",
        )
        merged = merge_continued_table_segments([first, second])
        assert len(merged) == 2

    def test_explicit_continuation_merges(self):
        """Continued-table markers still merge across pages."""
        first = _segment(
            2,
            1,
            [_row("甲", "乙")],
            continuation={"continues_to_next": True},
        )
        second = _segment(2, 2, [_row("丙", "丁")])
        merged = merge_continued_table_segments([first, second])
        assert len(merged) == 1
        assert merged[0]["row_count"] == 2

    def test_same_header_merges(self):
        first = _segment(2, 1, [_row("头", "列"), _row("甲", "乙")])
        second = _segment(2, 2, [_row("头", "列"), _row("丙", "丁")])
        merged = merge_continued_table_segments([first, second])
        assert len(merged) == 1
        # Repeated header on the continuation page is dropped.
        assert merged[0]["row_count"] == 3
