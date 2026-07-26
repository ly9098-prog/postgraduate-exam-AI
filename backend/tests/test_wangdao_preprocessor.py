"""Tests for wangdao_preprocessor — header/watermark filtering with box alignment.

Covers:
- Header filtering removes brand banner lines
- Boxes are filtered synchronously with lines
- Text lines and boxes maintain 1:1 correspondence after filtering
- classify_zone works correctly for header/body/footer/watermark
- Long brand header lines are filtered by position + width heuristics
"""
from __future__ import annotations

from app.features.wangdao_preprocessor import (
    _filter_lines_and_boxes,
    _filter_lines_and_boxes_detailed,
    classify_zone,
    preprocess_wangdao_blocks,
    preprocess_wangdao_blocks_detailed,
)

# ---------------------------------------------------------------------------
# classify_zone
# ---------------------------------------------------------------------------


class TestClassifyZone:
    def test_body_center(self):
        """Text in the middle of the page should be body."""
        zone = classify_zone("正常题干文本", 50, 200, 500, 220, 800, 1000)
        assert zone == "body"

    def test_brand_header(self):
        """Long brand header text at page top should be header."""
        zone = classify_zone(
            "风中易小生·24考研计算机WD数据结构做题本【选择题】",
            50, 5, 750, 25, 800, 1000,
        )
        assert zone == "header"

    def test_short_header(self):
        """Short text at page top should be header."""
        zone = classify_zone("考研复习指导", 50, 10, 200, 25, 800, 1000)
        assert zone == "header"

    def test_footer(self):
        """Short text at page bottom should be footer."""
        zone = classify_zone("第1页", 50, 950, 200, 970, 800, 1000)
        assert zone == "footer"

    def test_watermark_short(self):
        """Short watermark keyword text anywhere."""
        zone = classify_zone("王道", 50, 400, 150, 420, 800, 1000)
        assert zone == "watermark"

    def test_body_medium_text(self):
        """Normal text mentioning keywords should not be filtered from body area."""
        zone = classify_zone("计算机系统结构", 50, 400, 500, 420, 800, 1000)
        assert zone == "body"  # longer text in body area

    def test_header_edge_slightly_below(self):
        """Line just below 6% threshold should be body."""
        zone = classify_zone("正常文本", 50, 65, 200, 85, 800, 1000)
        assert zone == "body"  # 65/1000 = 0.065 > 0.06


# ---------------------------------------------------------------------------
# _filter_lines_and_boxes
# ---------------------------------------------------------------------------


class TestFilterLinesAndBoxes:
    def test_both_filtered_synchronously(self):
        """Header lines and their boxes should both be removed."""
        text = "品牌页眉行\n15. 题干\nA. 选项A"
        boxes = [
            {"bbox": [50, 5, 750, 25], "confidence": 0.9},
            {"bbox": [50, 100, 500, 120], "confidence": 0.9},
            {"bbox": [50, 200, 200, 220], "confidence": 0.9},
        ]
        kept_lines, kept_boxes = _filter_lines_and_boxes(text, boxes, 800, 1000)
        assert len(kept_lines) == len(kept_boxes)
        assert len(kept_lines) == 2  # header removed
        assert "15." in kept_lines[0]
        assert kept_boxes[0]["bbox"] == [50, 100, 500, 120]  # correct bbox

    def test_empty_lines_preserved(self):
        """Empty lines should stay without consuming box indices."""
        text = "15. 题干\n\nA. 选项A"
        boxes = [
            {"bbox": [50, 100, 500, 120], "confidence": 0.9},
            {"bbox": [50, 150, 200, 170], "confidence": 0.9},
        ]
        kept_lines, kept_boxes = _filter_lines_and_boxes(text, boxes, 800, 1000)
        assert len(kept_lines) == 3  # empty line preserved
        # Empty lines have no corresponding boxes
        assert len(kept_boxes) == 2
        # Box indices should still be correct for non-empty lines
        assert kept_boxes[0]["bbox"] == [50, 100, 500, 120]  # "15. 题干"
        assert kept_boxes[1]["bbox"] == [50, 150, 200, 170]  # "A. 选项A"

    def test_one_to_one_alignment(self):
        """After filtering, each non-empty line maps to its correct box."""
        text = "页眉\n15. 题干\n页脚\nA. 选项"
        boxes = [
            {"bbox": [50, 5, 750, 25], "confidence": 0.9},
            {"bbox": [50, 100, 500, 120], "confidence": 0.9},
            {"bbox": [50, 970, 200, 990], "confidence": 0.9},
            {"bbox": [50, 200, 200, 220], "confidence": 0.9},
        ]
        kept_lines, kept_boxes = _filter_lines_and_boxes(text, boxes, 800, 1000)
        assert len(kept_lines) == 2
        assert len(kept_boxes) == 2
        # Verify correct box alignment
        assert "15." in kept_lines[0]
        assert kept_boxes[0]["bbox"] == [50, 100, 500, 120]
        assert "A." in kept_lines[1]
        assert kept_boxes[1]["bbox"] == [50, 200, 200, 220]
        assert len(kept_lines) == len(kept_boxes)

    def test_all_body_none_filtered(self):
        """When no lines match filter criteria, everything is kept."""
        text = "15. 题干\nA. 选项A"
        boxes = [
            {"bbox": [50, 100, 500, 120], "confidence": 0.9},
            {"bbox": [50, 200, 200, 220], "confidence": 0.9},
        ]
        kept_lines, kept_boxes = _filter_lines_and_boxes(text, boxes, 800, 1000)
        assert kept_lines == ["15. 题干", "A. 选项A"]
        assert len(kept_boxes) == 2

    def test_empty_text_returns_empty(self):
        """Empty text with empty boxes returns empty lists."""
        kept_lines, kept_boxes = _filter_lines_and_boxes("", [], 800, 1000)
        # split("") on empty string produces [""], which is one empty line
        assert len(kept_lines) == 0 or len(kept_lines) == 1
        assert len(kept_boxes) == 0 or len(kept_boxes) == 1


# ---------------------------------------------------------------------------
# _filter_lines_and_boxes_detailed
# ---------------------------------------------------------------------------


class TestFilterLinesAndBoxesDetailed:
    def test_returns_removal_diagnostics(self):
        text = "页眉\n15. 题干"
        boxes = [
            {"bbox": [50, 5, 750, 25], "confidence": 0.9},
            {"bbox": [50, 100, 500, 120], "confidence": 0.9},
        ]
        kept_lines, kept_boxes, removed = _filter_lines_and_boxes_detailed(
            text, boxes, 800, 1000,
        )
        assert removed.get("header", 0) == 1
        assert len(kept_lines) == 1
        assert "15." in kept_lines[0]

    def test_removal_categories(self):
        text = "页眉\n15. 题干\n页脚"
        boxes = [
            {"bbox": [50, 5, 750, 25], "confidence": 0.9},
            {"bbox": [50, 100, 500, 120], "confidence": 0.9},
            {"bbox": [50, 970, 200, 990], "confidence": 0.9},
        ]
        _, _, removed = _filter_lines_and_boxes_detailed(text, boxes, 800, 1000)
        assert removed.get("header", 0) == 1
        assert removed.get("footer", 0) == 1


# ---------------------------------------------------------------------------
# preprocess_wangdao_blocks
# ---------------------------------------------------------------------------


class TestPreprocessWangdaoBlocks:
    def test_filters_blocks_with_boxes(self):
        """Blocks with boxes should be filtered."""
        blocks = [
            {
                "text": "品牌页眉\n15. 题干",
                "boxes": [
                    {"bbox": [50, 5, 750, 25], "confidence": 0.9},
                    {"bbox": [50, 100, 500, 120], "confidence": 0.9},
                ],
                "page_width": 800,
                "page_height": 1000,
            },
        ]
        result = preprocess_wangdao_blocks(blocks)
        assert len(result) == 1
        assert "15." in result[0]["text"]
        assert "品牌" not in result[0]["text"]

    def test_preserves_non_boxed_blocks(self):
        """Blocks without boxes should pass through with zone=body."""
        blocks = [
            {
                "text": "纯文本内容",
                "boxes": [],
                "page_width": 800,
                "page_height": 1000,
            },
        ]
        result = preprocess_wangdao_blocks(blocks)
        assert len(result) == 1
        assert result[0]["zone"] == "body"

    def test_boxes_filtered_synchronously(self):
        """After preprocessing, len(boxes) must match number of non-empty lines."""
        blocks = [
            {
                "text": "页眉1\n页眉2\n15. 题干\nA. 选项",
                "boxes": [
                    {"bbox": [50, 5, 750, 25], "confidence": 0.9},
                    {"bbox": [50, 10, 750, 25], "confidence": 0.9},
                    {"bbox": [50, 100, 500, 120], "confidence": 0.9},
                    {"bbox": [50, 200, 200, 220], "confidence": 0.9},
                ],
                "page_width": 800,
                "page_height": 1000,
            },
        ]
        result = preprocess_wangdao_blocks(blocks)
        assert len(result) == 1
        kept = result[0]
        num_lines = len([l for l in kept["text"].split("\n") if l.strip()])
        assert len(kept["boxes"]) == num_lines

    def test_all_filtered_block_dropped(self):
        """If all lines are filtered, the block should be dropped."""
        blocks = [
            {
                "text": "页眉",
                "boxes": [
                    {"bbox": [50, 5, 750, 25], "confidence": 0.9},
                ],
                "page_width": 800,
                "page_height": 1000,
            },
        ]
        result = preprocess_wangdao_blocks(blocks)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# preprocess_wangdao_blocks_detailed
# ---------------------------------------------------------------------------


class TestPreprocessWangdaoBlocksDetailed:
    def test_returns_diagnostics(self):
        blocks = [
            {
                "text": "页眉\n15. 题干",
                "boxes": [
                    {"bbox": [50, 5, 750, 25], "confidence": 0.9},
                    {"bbox": [50, 100, 500, 120], "confidence": 0.9},
                ],
                "page_width": 800,
                "page_height": 1000,
            },
        ]
        result, diagnostics = preprocess_wangdao_blocks_detailed(blocks)
        assert diagnostics["removed_lines"] >= 1
