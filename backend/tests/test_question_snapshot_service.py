"""Tests for question_snapshot_service — bbox computation and coordinate-aware padding.

Covers:
- OCR line builder with header filtering
- Question anchor detection
- Single question bbox (no next question on page)
- Multi-question page bbox separation
- Option coverage and extension
- Visual reference area protection
- Coordinate-space-aware expand_bbox
- Fallback behavior
"""
from __future__ import annotations

import pytest

from app.services.question_snapshot_service import (
    _find_anchor_line,
    _find_next_question_line,
    _match_question_number,
    _has_visual_reference,
    _extract_expected_option_keys,
    _find_option_lines_in_ocr,
    _union_bbox,
    _collect_question_lines,
    build_ocr_lines,
    compute_question_bbox,
    expand_bbox,
    CS_IMAGE_PIXELS,
    CS_PDF_POINTS,
    CS_NORMALIZED_1000,
    CS_NORMALIZED_1,
)


# ---------------------------------------------------------------------------
# _match_question_number
# ---------------------------------------------------------------------------


class TestMatchQuestionNumber:
    def test_simple_number(self):
        assert _match_question_number("15. 题干文本", 15) is True

    def test_chinese_period(self):
        assert _match_question_number("15．题干文本", 15) is True

    def test_paren(self):
        assert _match_question_number("(15) 题干文本", 15) is True

    def test_chinese_paren(self):
        assert _match_question_number("（15）题干文本", 15) is True

    def test_bracket(self):
        assert _match_question_number("【15】题干文本", 15) is True

    def test_ocr_tolerant(self):
        assert _match_question_number("l. 题干文本", 1) is True
        assert _match_question_number("I. 题干文本", 1) is True

    def test_wrong_number(self):
        assert _match_question_number("15. 文本", 16) is False

    def test_no_expected_number(self):
        assert _match_question_number("15. 文本", None) is True
        assert _match_question_number("普通文本", None) is False

    def test_label_match(self):
        assert _match_question_number("15.【2013 统考真题】", 15) is True


# ---------------------------------------------------------------------------
# _has_visual_reference
# ---------------------------------------------------------------------------


class TestHasVisualReference:
    def test_ru_tu(self):
        assert _has_visual_reference("如图") is True

    def test_ru_xia_tu(self):
        assert _has_visual_reference("如下图") is True

    def test_ru_xia_biao(self):
        assert _has_visual_reference("如下表") is True

    def test_no_reference(self):
        assert _has_visual_reference("普通文本") is False

    def test_empty(self):
        assert _has_visual_reference("") is False


# ---------------------------------------------------------------------------
# expand_bbox coordinate-aware padding
# ---------------------------------------------------------------------------


class TestExpandBbox:
    def test_image_pixels_default_dpi(self):
        """With default fallback DPI (150), 8pt padding = 8*150/72 ≈ 16.67px"""
        result = expand_bbox(
            (100, 200, 500, 400), CS_IMAGE_PIXELS, 8.0,
            800, 600, None, None,
        )
        x0, y0, x1, y1 = result
        assert x0 < 100  # padding added left
        assert y0 < 200  # padding added top
        assert x1 > 500  # padding added right
        assert y1 > 400  # padding added bottom
        assert x0 >= 0  # clamped
        assert y0 >= 0

    def test_image_pixels_with_pdf_dims(self):
        """With known PDF dims, 8pt at 800px/612pt = ~94dpi"""
        result = expand_bbox(
            (100, 200, 500, 400), CS_IMAGE_PIXELS, 8.0,
            800, 600, 612.0, 792.0,
        )
        x0, y0, x1, y1 = result
        # 8pt * (800/612*72) / 72 = 8 * (800/612) ≈ 10.46px
        assert abs(x0 - (100 - 8.0 * 800 / 612)) < 0.1
        assert x1 > 500

    def test_pdf_points(self):
        result = expand_bbox(
            (72, 144, 432, 360), CS_PDF_POINTS, 8.0,
            800, 600, 612.0, 792.0,
        )
        x0, y0, x1, y1 = result
        assert x0 == 64.0  # 72 - 8
        assert y0 == 136.0  # 144 - 8
        assert x1 == 440.0  # 432 + 8
        assert y1 == 368.0  # 360 + 8

    def test_normalized_1000(self):
        result = expand_bbox(
            (200, 300, 600, 500), CS_NORMALIZED_1000, 8.0,
            800, 600, 612.0, 792.0,
        )
        x0, y0, x1, y1 = result
        # pad_x = 8/612*1000 ≈ 13.07
        assert abs(x0 - (200 - 8.0 / 612 * 1000)) < 0.1
        assert x0 >= 0
        assert x1 <= 1000

    def test_normalized_1(self):
        result = expand_bbox(
            (0.2, 0.3, 0.6, 0.5), CS_NORMALIZED_1, 8.0,
            800, 600, 612.0, 792.0,
        )
        x0, y0, x1, y1 = result
        # pad_x = 8/612 ≈ 0.01307
        assert abs(x0 - (0.2 - 8.0 / 612)) < 0.001
        assert x0 >= 0
        assert x1 <= 1.0

    def test_clamp_to_boundary(self):
        """Padding that goes negative should clamp to 0."""
        result = expand_bbox(
            (2, 2, 500, 400), CS_PDF_POINTS, 8.0,
            800, 600, 612.0, 792.0,
        )
        assert result[0] >= 0
        assert result[1] >= 0

    def test_unknown_space_fallback(self):
        """Unknown space falls back to image_pixels with 150 DPI."""
        result = expand_bbox(
            (100, 200, 500, 400), "unknown", 8.0,
            800, 600, None, None,
        )
        x0, y0, x1, y1 = result
        assert x0 < 100
        assert y0 < 200

    def test_empty_bbox_padding(self):
        """Tiny bbox with padding should not crash."""
        result = expand_bbox(
            (10, 10, 20, 20), CS_PDF_POINTS, 8.0,
            800, 600, 612.0, 792.0,
        )
        assert result[0] < result[2]
        assert result[1] < result[3]


# ---------------------------------------------------------------------------
# _union_bbox
# ---------------------------------------------------------------------------


class TestUnionBbox:
    def test_single_line(self):
        lines = [{"bbox": (100, 200, 500, 400)}]
        assert _union_bbox(lines) == (100, 200, 500, 400)

    def test_multiple_lines(self):
        lines = [
            {"bbox": (100, 200, 500, 400)},
            {"bbox": (150, 350, 600, 500)},
        ]
        assert _union_bbox(lines) == (100, 200, 600, 500)

    def test_empty(self):
        assert _union_bbox([]) == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# _find_anchor_line
# ---------------------------------------------------------------------------


class TestFindAnchorLine:
    def test_exact_number_match(self):
        page_lines = [
            {"text": "普通文本", "bbox": (50, 50, 200, 70)},
            {"text": "15. 题干文本", "bbox": (50, 100, 500, 120)},
            {"text": "A. 选项", "bbox": (50, 150, 200, 170)},
        ]
        result = _find_anchor_line(page_lines, "", 15, "")
        assert result is not None
        assert "15." in result.get("text", "")

    def test_no_match_returns_none(self):
        page_lines = [
            {"text": "普通文本", "bbox": (50, 50, 200, 70)},
            {"text": "A. 选项", "bbox": (50, 100, 200, 120)},
        ]
        result = _find_anchor_line(page_lines, "", 99, "")
        assert result is None

    def test_stem_prefix_match(self):
        page_lines = [
            {"text": "15. 若对如下无向图进行遍历", "bbox": (50, 100, 500, 120)},
        ]
        raw_text = "15. 若对如下无向图进行遍历，则下列"
        result = _find_anchor_line(page_lines, raw_text, None, "")
        assert result is not None


# ---------------------------------------------------------------------------
# _find_next_question_line
# ---------------------------------------------------------------------------


class TestFindNextQuestionLine:
    def test_finds_next_question(self):
        page_lines = [
            {"text": "15. 第一题", "bbox": (50, 100, 500, 120)},
            {"text": "A. 选项", "bbox": (50, 150, 200, 170)},
            {"text": "16. 第二题", "bbox": (50, 300, 500, 320)},
            {"text": "A. 选项", "bbox": (50, 350, 200, 370)},
        ]
        result = _find_next_question_line(page_lines, 1)
        assert result is not None
        assert "16." in result.get("text", "")

    def test_no_next_question(self):
        page_lines = [
            {"text": "15. 第一题", "bbox": (50, 100, 500, 120)},
            {"text": "普通文本", "bbox": (50, 200, 500, 220)},
        ]
        result = _find_next_question_line(page_lines, 1)
        assert result is None


# ---------------------------------------------------------------------------
# _extract_expected_option_keys / _find_option_lines_in_ocr
# ---------------------------------------------------------------------------


class TestOptionKeyExtraction:
    def test_from_option_lines_dict(self):
        raw = {"option_lines": {"A": "内容A", "B": "内容B", "C": "内容C", "D": "内容D"}}
        assert _extract_expected_option_keys(raw) == ["A", "B", "C", "D"]

    def test_from_options_list(self):
        raw = {"options": [{"key": "A", "text": "aa"}, {"key": "B", "text": "bb"}]}
        assert _extract_expected_option_keys(raw) == ["A", "B"]

    def test_empty(self):
        assert _extract_expected_option_keys({}) == []


class TestFindOptionLinesInOcr:
    def test_finds_options(self):
        ocr_lines = [
            {"text": "A. 内容A", "bbox": (50, 100, 200, 120)},
            {"text": "B. 内容B", "bbox": (250, 100, 400, 120)},
            {"text": "普通文本", "bbox": (50, 200, 500, 220)},
        ]
        result = _find_option_lines_in_ocr(ocr_lines, ["A", "B"])
        assert len(result) == 2

    def test_horizontal_options(self):
        """Separate OCR lines for each horizontally arranged option."""
        ocr_lines = [
            {"text": "A. 内容A", "bbox": (50, 100, 150, 120)},
            {"text": "B. 内容B", "bbox": (200, 100, 300, 120)},
            {"text": "C. 内容C", "bbox": (350, 100, 450, 120)},
            {"text": "D. 内容D", "bbox": (500, 100, 600, 120)},
        ]
        result = _find_option_lines_in_ocr(ocr_lines, ["A", "B", "C", "D"])
        assert len(result) == 4

    def test_no_matches(self):
        ocr_lines = [
            {"text": "普通文本", "bbox": (50, 100, 500, 120)},
        ]
        result = _find_option_lines_in_ocr(ocr_lines, ["A"])
        assert len(result) == 0


# ---------------------------------------------------------------------------
# build_ocr_lines — header filtering + bbox alignment
# ---------------------------------------------------------------------------


class TestBuildOcrLines:
    def test_keeps_body_lines(self):
        blocks = [
            {
                "page": 1,
                "text": "15. 题干\nA. 选项A\nB. 选项B",
                "boxes": [
                    {"bbox": [50, 100, 500, 120], "confidence": 0.9},
                    {"bbox": [50, 150, 200, 170], "confidence": 0.9},
                    {"bbox": [250, 150, 400, 170], "confidence": 0.9},
                ],
                "page_width": 800,
                "page_height": 1000,
            },
        ]
        lines = build_ocr_lines(blocks)
        assert len(lines) == 3  # all non-empty lines kept
        assert all(l.get("zone") == "body" for l in lines)

    def test_filters_header_lines(self):
        """Header lines at page top should be filtered out."""
        blocks = [
            {
                "page": 1,
                "text": "品牌页眉\n15. 题干",
                "boxes": [
                    {"bbox": [50, 5, 750, 25], "confidence": 0.9},  # top 5/1000 → header
                    {"bbox": [50, 100, 500, 120], "confidence": 0.9},
                ],
                "page_width": 800,
                "page_height": 1000,
            },
        ]
        lines = build_ocr_lines(blocks)
        assert len(lines) == 1
        assert "15." in lines[0]["text"]

    def test_empty_lines_skipped(self):
        blocks = [
            {
                "page": 1,
                "text": "\n15. 题干",
                "boxes": [
                    {"bbox": [50, 100, 500, 120], "confidence": 0.9},
                ],
                "page_width": 800,
                "page_height": 1000,
            },
        ]
        lines = build_ocr_lines(blocks)
        assert len(lines) == 1

    def test_boxes_and_text_aligned(self):
        """After filtering, each line should still have its correct bbox."""
        blocks = [
            {
                "page": 1,
                "text": "15. 题干\nA. 选项A\nB. 选项B",
                "boxes": [
                    {"bbox": [50, 100, 500, 120], "confidence": 0.9},
                    {"bbox": [50, 150, 200, 170], "confidence": 0.9},
                    {"bbox": [250, 150, 400, 170], "confidence": 0.9},
                ],
                "page_width": 800,
                "page_height": 1000,
            },
        ]
        lines = build_ocr_lines(blocks)
        assert len(lines) == 3
        # Line indices should match their original block positions
        assert lines[1]["bbox"][0] == 50
        assert lines[2]["bbox"][0] == 250


# ---------------------------------------------------------------------------
# compute_question_bbox — main bbox computation
# ---------------------------------------------------------------------------


class TestComputeQuestionBbox:
    def _make_ocr_lines(self, lines_data: list[dict]) -> list[dict]:
        return [
            {
                "page": d.get("page", 1),
                "text": d["text"],
                "bbox": d["bbox"],
                "confidence": d.get("conf", 0.9),
                "zone": d.get("zone", "body"),
                "line_index": idx,
                "page_width": d.get("pw", 800),
                "page_height": d.get("ph", 1000),
            }
            for idx, d in enumerate(lines_data)
        ]

    # ── Test: single question on page ──
    def test_single_question_includes_all_options(self):
        """Bbox should cover from question number through all options."""
        ocr_lines = self._make_ocr_lines([
            {"text": "15. 题干文本", "bbox": (50, 100, 500, 120), "ph": 1000},
            {"text": "图中所示", "bbox": (50, 130, 500, 150), "ph": 1000},
            {"text": "A. 选项A", "bbox": (50, 200, 200, 220), "ph": 1000},
            {"text": "B. 选项B", "bbox": (250, 200, 400, 220), "ph": 1000},
            {"text": "C. 选项C", "bbox": (50, 230, 200, 250), "ph": 1000},
            {"text": "D. 选项D", "bbox": (250, 230, 400, 250), "ph": 1000},
        ])
        raw_q = {
            "page_start": 1,
            "source_question_no": 15,
            "raw_question_text": "15. 题干文本",
            "option_lines": {"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"},
        }
        result = compute_question_bbox(raw_q, ocr_lines, 1)
        bbox = result["question_bbox"]
        assert bbox is not None
        assert bbox[0] <= 50  # left covers leftmost content
        assert bbox[1] <= 100  # top covers question start
        assert bbox[3] >= 250  # bottom covers D option
        assert result["question_bbox_diagnostics"]["coverage"] >= 0.99

    # ── Test: no header in bbox ──
    def test_no_header_in_bbox(self):
        """Bbox top should start from question number, not include header above."""
        ocr_lines = self._make_ocr_lines([
            {"text": "品牌页眉文字", "bbox": (50, 5, 750, 25), "zone": "header", "ph": 1000},
            {"text": "15. 题干", "bbox": (50, 100, 500, 120), "ph": 1000},
            {"text": "A. 选项A", "bbox": (50, 200, 200, 220), "ph": 1000},
            {"text": "D. 选项D", "bbox": (50, 230, 200, 250), "ph": 1000},
        ])
        raw_q = {
            "page_start": 1,
            "source_question_no": 15,
            "raw_question_text": "15. 题干",
            "option_lines": {"A": "选项A", "D": "选项D"},
        }
        result = compute_question_bbox(raw_q, ocr_lines, 1)
        bbox = result["question_bbox"]
        # Header was already filtered by build_ocr_lines, but bbox should match
        # the anchor line top, not the header
        assert bbox[1] >= 50  # shouldn't extend up to header area

    # ── Test: multi-question page ──
    def test_multi_question_page(self):
        """First question bbox should stop before second question's number."""
        ocr_lines = self._make_ocr_lines([
            {"text": "15. 第一题", "bbox": (50, 100, 500, 120), "ph": 1000},
            {"text": "A. 选项A", "bbox": (50, 150, 200, 170), "ph": 1000},
            {"text": "D. 选项D", "bbox": (50, 180, 200, 200), "ph": 1000},
            {"text": "16. 第二题", "bbox": (50, 300, 500, 320), "ph": 1000},
            {"text": "A. 选项A", "bbox": (50, 350, 200, 370), "ph": 1000},
        ])
        raw_q = {
            "page_start": 1,
            "source_question_no": 15,
            "raw_question_text": "15. 第一题",
            "option_lines": {"A": "选项A", "D": "选项D"},
        }
        result = compute_question_bbox(raw_q, ocr_lines, 1)
        bbox = result["question_bbox"]
        assert bbox[1] <= 100  # starts at question
        assert bbox[3] < 300  # should not reach next question
        assert bbox[3] >= 200  # should cover D option

    # ── Test: visual reference protection ──
    def test_visual_reference_protection(self):
        """Graphics area between stem and options should be preserved."""
        ocr_lines = self._make_ocr_lines([
            {"text": "15. 如图无向图", "bbox": (50, 100, 500, 120), "ph": 1000},
            {"text": "A. 选项A", "bbox": (50, 400, 200, 420), "ph": 1000},
            {"text": "D. 选项D", "bbox": (50, 430, 200, 450), "ph": 1000},
        ])
        raw_q = {
            "page_start": 1,
            "source_question_no": 15,
            "raw_question_text": "15. 如图无向图，进行遍历",
            "option_lines": {"A": "选项A", "D": "选项D"},
        }
        result = compute_question_bbox(raw_q, ocr_lines, 1)
        bbox = result["question_bbox"]
        # There's a big gap between stem (y=120) and options (y=400)
        # The bbox bottom should be at least at D option's bottom
        assert bbox[3] >= 450  # covers D option bottom

    # ── Test: horizontal options ──
    def test_horizontal_option_coverage(self):
        """Bbox left/right must cover A through D for horizontal options."""
        ocr_lines = self._make_ocr_lines([
            {"text": "15. 题干", "bbox": (50, 100, 500, 120), "ph": 1000},
            {"text": "A. opt A", "bbox": (50, 200, 150, 220), "ph": 1000},
            {"text": "B. opt B", "bbox": (200, 200, 300, 220), "ph": 1000},
            {"text": "C. opt C", "bbox": (350, 200, 450, 220), "ph": 1000},
            {"text": "D. opt D", "bbox": (500, 200, 600, 220), "ph": 1000},
        ])
        raw_q = {
            "page_start": 1,
            "source_question_no": 15,
            "raw_question_text": "15. 题干",
            "option_lines": {"A": "A", "B": "B", "C": "C", "D": "D"},
        }
        result = compute_question_bbox(raw_q, ocr_lines, 1)
        bbox = result["question_bbox"]
        assert bbox[0] <= 50  # left covers A
        assert bbox[2] >= 600  # right covers D

    # ── Test: fallback when anchor not found ──
    def test_anchor_not_found_fallback(self):
        """When anchor isn't found, should return confidence 0."""
        ocr_lines = self._make_ocr_lines([
            {"text": "普通文本", "bbox": (50, 100, 500, 120), "ph": 1000},
        ])
        raw_q = {
            "page_start": 1,
            "source_question_no": 99,
            "raw_question_text": "",
        }
        result = compute_question_bbox(raw_q, ocr_lines, 1)
        assert result["question_bbox_confidence"] == 0.0
        assert result["question_bbox_strategy"].startswith("fallback")

    # ── Test: no options case ──
    def test_no_options_still_gets_bbox(self):
        """Fill-in-the-blank/subjective questions should still get a bbox."""
        ocr_lines = self._make_ocr_lines([
            {"text": "10. 填空题____", "bbox": (50, 100, 500, 120), "ph": 1000},
            {"text": "答案是三", "bbox": (50, 130, 200, 150), "ph": 1000},
        ])
        raw_q = {
            "page_start": 1,
            "source_question_no": 10,
            "raw_question_text": "10. 填空题____",
        }
        result = compute_question_bbox(raw_q, ocr_lines, 1)
        bbox = result["question_bbox"]
        assert bbox is not None
        assert bbox[3] >= 150  # covers all lines

    # ── Test: question_bbox fields survive full computation ──
    def test_bbox_fields_present(self):
        ocr_lines = self._make_ocr_lines([
            {"text": "1. 测试", "bbox": (50, 100, 500, 120), "ph": 1000},
        ])
        raw_q = {"page_start": 1, "source_question_no": 1, "raw_question_text": "1. 测试"}
        result = compute_question_bbox(raw_q, ocr_lines, 1)
        assert "question_bbox" in result
        assert "question_bbox_coordinate_space" in result
        assert "question_bbox_page_width" in result
        assert "question_bbox_page_height" in result
        assert "question_bbox_confidence" in result
        assert "question_bbox_strategy" in result
        assert "question_bbox_diagnostics" in result


# ---------------------------------------------------------------------------
# collect_question_lines
# ---------------------------------------------------------------------------


class TestCollectQuestionLines:
    def test_stops_at_next_question(self):
        page_lines = [
            {"text": "15. 第一题", "bbox": (50, 100, 500, 120)},
            {"text": "A. 选项A", "bbox": (50, 150, 200, 170)},
            {"text": "16. 第二题", "bbox": (50, 300, 500, 320)},
        ]
        result = _collect_question_lines(page_lines, 0, 1, {}, {"A": "A"})
        assert len(result) == 2  # only "15." and "A." — not "16."

    def test_collects_all_lines_no_next(self):
        page_lines = [
            {"text": "15. 第一题", "bbox": (50, 100, 500, 120)},
            {"text": "A. 选项A", "bbox": (50, 150, 200, 170)},
        ]
        result = _collect_question_lines(page_lines, 0, 1, {}, {"A": "A"})
        assert len(result) == 2


# ---------------------------------------------------------------------------
# compute_question_bboxes batch API
# ---------------------------------------------------------------------------


class TestComputeQuestionBboxes:
    def test_batch_processes_all_questions(self):
        from app.services.question_snapshot_service import compute_question_bboxes

        raw_questions = [
            {"page_start": 1, "source_question_no": 1, "raw_question_text": "1. 第一题"},
            {"page_start": 1, "source_question_no": 2, "raw_question_text": "2. 第二题"},
        ]
        normalized_blocks = [
            {
                "page": 1,
                "text": "1. 第一题\nA. opt A\n2. 第二题\nA. opt B",
                "boxes": [
                    {"bbox": [50, 100, 500, 120], "confidence": 0.9},
                    {"bbox": [50, 150, 200, 170], "confidence": 0.9},
                    {"bbox": [50, 300, 500, 320], "confidence": 0.9},
                    {"bbox": [50, 350, 200, 370], "confidence": 0.9},
                ],
                "page_width": 800,
                "page_height": 1000,
            },
        ]
        result = compute_question_bboxes(raw_questions, normalized_blocks)
        assert len(result) == 2
        for q in result:
            assert "question_bbox" in q
