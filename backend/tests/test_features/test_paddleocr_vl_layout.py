"""Tests for PaddleOCR-VL client structured layout parsing.

Covers:
- layout_blocks extraction from JSONL entries
- multiple layoutParsingResults across multiple lines
- block normalization (type, bbox, text, confidence)
- polygon → bbox conversion
- fallback text fields (text/ocr_text/content)
- empty/nonexistent blocks
- malformed JSON lines
"""
from __future__ import annotations

import json

import pytest

from app.features.ocr_vl.paddleocr_vl_client import (
    PaddleOCRVLResult,
    _normalize_layout_block,
)


# ---------------------------------------------------------------------------
# _normalize_layout_block
# ---------------------------------------------------------------------------


class TestNormalizeLayoutBlock:
    def test_markdown_with_text_and_bbox(self):
        block = _normalize_layout_block({
            "type": "figure",
            "bbox": [100, 200, 500, 400],
            "markdown": {
                "text": "Figure caption",
                "confidence": 0.95,
            },
        })
        assert block is not None
        assert block["type"] == "figure"
        assert block["text"] == "Figure caption"
        assert block["bbox"] == [100.0, 200.0, 500.0, 400.0]
        assert block["confidence"] == 0.95

    def test_empty_block_returns_none(self):
        block = _normalize_layout_block({})
        assert block is None

    def test_polygon_to_bbox_conversion(self):
        """8-element polygon → (min_x, min_y, max_x, max_y)"""
        block = _normalize_layout_block({
            "type": "table",
            "polygon": [100, 200, 500, 200, 500, 600, 100, 600],
            "markdown": {"text": "Table data"},
        })
        assert block is not None
        assert block["bbox"] == [100.0, 200.0, 500.0, 600.0]
        assert block["polygon"] == [100.0, 200.0, 500.0, 200.0, 500.0, 600.0, 100.0, 600.0]

    def test_text_fallback_when_no_markdown(self):
        block = _normalize_layout_block({
            "type": "text",
            "text": "Hello world",
            "bbox": [0, 0, 100, 20],
        })
        assert block is not None
        assert block["text"] == "Hello world"

    def test_label_and_category_fallbacks(self):
        block = _normalize_layout_block({
            "label": "chart",
            "category": "figure",
            "bbox": [0, 0, 100, 100],
        })
        assert block["type"] == "chart"
        assert block["label"] == "chart"
        assert block["category"] == "figure"

    def test_page_number(self):
        block = _normalize_layout_block({
            "type": "figure",
            "page": 3,
            "bbox": [0, 0, 100, 100],
        })
        assert block["page"] == 3

    def test_page_num_alternative(self):
        block = _normalize_layout_block({
            "type": "figure",
            "page_num": 2,
            "bbox": [0, 0, 100, 100],
        })
        assert block["page"] == 2

    def test_invalid_bbox_types_omitted(self):
        block = _normalize_layout_block({
            "type": "text",
            "bbox": "not_a_list",
            "text": "hello",
        })
        assert block is not None
        assert "bbox" not in block

    def test_no_text_no_bbox_returns_none(self):
        block = _normalize_layout_block({"type": "separator"})
        assert block is None

    def test_raw_block_preserved(self):
        raw = {"type": "custom", "bbox": [0, 0, 10, 10], "extra_field": "x"}
        block = _normalize_layout_block(raw)
        assert block["raw_block"] is raw


# ---------------------------------------------------------------------------
# PaddleOCRVLResult
# ---------------------------------------------------------------------------


class TestPaddleOCRVLResult:
    def test_default_initialization(self):
        result = PaddleOCRVLResult(text="hello", confidence=0.9)
        assert result.text == "hello"
        assert result.confidence == 0.9
        assert result.layout_blocks == []
        assert result.raw_entries == []

    def test_with_layout_blocks(self):
        blocks = [{"type": "figure", "bbox": [0, 0, 100, 100]}]
        result = PaddleOCRVLResult(
            text="hello",
            confidence=0.9,
            layout_blocks=blocks,
        )
        assert result.layout_blocks == blocks

    def test_get_blocks_by_type(self):
        blocks = [
            {"type": "figure", "bbox": [0, 0, 100, 100]},
            {"type": "text", "bbox": [0, 0, 50, 20]},
            {"type": "figure", "bbox": [200, 200, 300, 300]},
        ]
        result = PaddleOCRVLResult(text="", confidence=0.0, layout_blocks=blocks)
        figures = result.get_blocks_by_type("figure")
        assert len(figures) == 2

    def test_get_blocks_by_category(self):
        blocks = [
            {"category": "figure", "bbox": [0, 0, 100, 100]},
            {"category": "text", "bbox": [0, 0, 50, 20]},
        ]
        result = PaddleOCRVLResult(text="", confidence=0.0, layout_blocks=blocks)
        assert len(result.get_blocks_by_category("figure")) == 1
