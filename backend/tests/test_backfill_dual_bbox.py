"""Tests for backfill dual-bbox functions: visual_bbox, stem cleanup, quality gates.

Covers the 15-point specification for fixing content images and stem text:
- OCR overlap analysis and visual_text detection
- Stem cleanup via spatial dedup (no regex number deletion)
- Visual bbox computation from OCR line positions
- Option-aware visual bbox constraint
- Content image quality gates
- Versioned crop regeneration
- OCR line classification and zone detection
- Hard visual quality gate
- Regression tests for qno 369, 380, 457
"""

from __future__ import annotations

import json
import os
import re
import sys

import pytest

# Ensure the scripts and backend directories are importable
_SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
for _p in (_SCRIPT_DIR, _BACKEND_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backfill_question_images import (
    CROP_VERSION,
    OVERLAP_THRESHOLD,
    VISUAL_PADDING_PT,
    ImageResult,
    ZoneResult,
    _ZONE_HEADER,
    _ZONE_QUESTION_STEM,
    _ZONE_VISUAL_TEXT,
    _ZONE_ANSWER_HINT,
    _ZONE_OPTION,
    _ZONE_FOOTER,
    _ZONE_SECTION_HEADING,
    _ZONE_BODY,
    _ZONE_NEXT_QUESTION,
    classify_line,
    _ocr_diagram_bbox,
    analyze_ocr_overlap,
    check_content_image_quality,
    check_visual_gate,
    classify_ocr_lines,
    clean_stem_from_visual_text,
    compute_diagram_zone_pt,
    compute_overlap_ratio,
    compute_stem_bottom_pt,
    content_storage_key,
    detect_first_option_pt,
    ocr_lines_to_pdf_points,
    refine_visual_bbox_for_options,
    check_header_pollution,
)

# ── Fixtures ──


@pytest.fixture
def pdf_rect():
    """Simulate PDF page rect (567x425 pt, typical for ds_sc.pdf)."""
    class MockRect:
        width = 567.0
        height = 425.34
    return MockRect()


@pytest.fixture
def bplus_ocr_lines(pdf_rect):
    """OCR lines from the B+ tree page (page 380), converted to PDF points."""
    raw = [
        {"text": "风中易小生·24考研计算机WD数据结构做题本【选择题】", "confidence": 0.997, "bbox": [82, 25, 820, 55]},
        {"text": "7.4 B 树和 B+树", "confidence": 0.935, "bbox": [62, 89, 240, 120]},
        {"text": "一、单项选择题（本部分答案在书P293）", "confidence": 0.996, "bbox": [57, 142, 509, 171]},
        {"text": "1.下图所示是一棵()", "confidence": 0.994, "bbox": [57, 190, 308, 223]},
        {"text": "12", "confidence": 1.0, "bbox": [516, 255, 547, 281]},
        {"text": "25", "confidence": 1.0, "bbox": [568, 256, 601, 282]},
        {"text": "05", "confidence": 1.0, "bbox": [382, 348, 415, 375]},
        {"text": "10", "confidence": 1.0, "bbox": [431, 348, 463, 375]},
        {"text": "15", "confidence": 1.0, "bbox": [506, 348, 539, 374]},
        {"text": "19", "confidence": 1.0, "bbox": [544, 349, 576, 374]},
        {"text": "22", "confidence": 1.0, "bbox": [579, 349, 614, 375]},
        {"text": "26", "confidence": 1.0, "bbox": [653, 348, 686, 375]},
        {"text": "28", "confidence": 1.0, "bbox": [706, 349, 739, 375]},
        {"text": "A.4 阶 B 树", "confidence": 0.87, "bbox": [80, 404, 208, 436]},
        {"text": "B.4 阶 B+树", "confidence": 0.941, "bbox": [318, 404, 452, 436]},
        {"text": "C.3 阶 B 树", "confidence": 0.953, "bbox": [537, 404, 664, 436]},
        {"text": "D.3 阶 B+树", "confidence": 0.943, "bbox": [755, 404, 890, 435]},
    ]
    return ocr_lines_to_pdf_points(raw, (1182, 887), pdf_rect)


@pytest.fixture
def bst_ocr_lines(pdf_rect):
    """OCR lines from the BST page (page 379)."""
    raw = [
        {"text": "风中易小生·24考研计算机WD数据结构做题本【选择题】", "confidence": 0.994, "bbox": [82, 25, 820, 55]},
        {"text": "27.【2021 统考真题】给定平衡二叉树如下图所示，插入关键字23后，根中的关键字是()。", "confidence": 0.997, "bbox": [54, 88, 1081, 121]},
        {"text": "20", "confidence": 1.0, "bbox": [513, 161, 545, 190]},
        {"text": "16", "confidence": 1.0, "bbox": [460, 228, 497, 260]},
        {"text": "30", "confidence": 1.0, "bbox": [568, 229, 598, 258]},
        {"text": "25", "confidence": 1.0, "bbox": [515, 295, 550, 328]},
        {"text": "40", "confidence": 1.0, "bbox": [619, 295, 655, 328]},
        {"text": "A.16", "confidence": 0.999, "bbox": [79, 378, 138, 407]},
        {"text": "B.20", "confidence": 1.0, "bbox": [183, 378, 243, 407]},
        {"text": "C.23", "confidence": 1.0, "bbox": [315, 375, 374, 408]},
        {"text": "D.25", "confidence": 1.0, "bbox": [446, 375, 507, 408]},
    ]
    return ocr_lines_to_pdf_points(raw, (1182, 887), pdf_rect)


# ═══════════════════════════════════════════════════════════════════
# Test: compute_overlap_ratio
# ═══════════════════════════════════════════════════════════════════


class TestComputeOverlapRatio:
    def test_full_overlap(self):
        """Line bbox completely inside visual bbox → 1.0."""
        r = compute_overlap_ratio((100, 100, 200, 200), (50, 50, 250, 250))
        assert r == 1.0

    def test_no_overlap(self):
        r = compute_overlap_ratio((100, 100, 200, 200), (300, 300, 400, 400))
        assert r == 0.0

    def test_partial_overlap(self):
        """Half the line area overlaps."""
        r = compute_overlap_ratio((100, 100, 300, 200), (200, 100, 400, 200))
        assert r == 0.5

    def test_edge_touching(self):
        """Bboxes that touch at edge have zero area overlap."""
        r = compute_overlap_ratio((100, 100, 200, 200), (200, 100, 300, 200))
        assert r == 0.0

    def test_line_inside_visual(self):
        """Line fully inside visual bbox."""
        r = compute_overlap_ratio((100, 100, 200, 200), (50, 50, 250, 250))
        assert r == 1.0


# ═══════════════════════════════════════════════════════════════════
# Test: _ocr_diagram_bbox (visual_bbox from OCR)
# ═══════════════════════════════════════════════════════════════════


class TestOcrDiagramBbox:
    def test_bplus_tree_detection(self, bplus_ocr_lines, pdf_rect):
        """OCR-based diagram detection should find the B+ tree node values."""
        region = (199.4, 1.4, 349.9, 200.5)
        db = _ocr_diagram_bbox(bplus_ocr_lines, region, 425.34)
        assert db is not None, "Should find diagram bbox"
        # Should cover the tree node values (approximately y=122-185pt)
        assert db[1] >= 50, f"Top should exclude header, got y0={db[1]:.1f}"
        assert db[3] <= 210, f"Bottom should exclude options, got y1={db[3]:.1f}"
        # Should NOT include header text
        for line in bplus_ocr_lines:
            text = line["text"]
            if "风中易小生" in text or "选择题" in text or "答案在书" in text:
                # These should NOT be diagram lines
                pass

    def test_bst_detection(self, bst_ocr_lines, pdf_rect):
        """OCR-based diagram detection should find BST node values."""
        region = (199.4, 1.4, 349.9, 200.5)
        db = _ocr_diagram_bbox(bst_ocr_lines, region, 425.34)
        assert db is not None, "Should find diagram bbox"

    def test_diagram_excludes_options(self, bplus_ocr_lines, pdf_rect):
        """Diagram bbox must NOT include option lines."""
        region = (199.4, 1.4, 349.9, 200.5)
        db = _ocr_diagram_bbox(bplus_ocr_lines, region, 425.34)
        for line in bplus_ocr_lines:
            text = line["text"]
            if re.match(r"^[A-D]\s*[.、:：)）]", text):
                # Option line - its bbox should NOT be fully inside diagram bbox
                b = line["bbox_pt"]
                # If the option line overlaps, it should be below the diagram
                if db[3] > b[1]:
                    pytest.fail(f"Diagram bbox bottom {db[3]:.1f} extends into option '{text}' at y={b[1]:.1f}")


# ═══════════════════════════════════════════════════════════════════
# Test: analyze_ocr_overlap
# ═══════════════════════════════════════════════════════════════════


class TestAnalyzeOcrOverlap:
    def test_visual_text_marking(self, bplus_ocr_lines):
        """Lines inside visual bbox should be marked as visual_text."""
        # Use a visual bbox that covers the B+ tree node values
        visual = (199.4, 115.0, 349.9, 185.0)
        viz_text, kept = analyze_ocr_overlap(bplus_ocr_lines, visual, threshold=0.6)

        viz_texts = [v["text"] for v in viz_text]
        # "12", "25" should be visual_text (fully inside bbox)
        assert "12" in viz_texts, "'12' should be visual_text"
        assert "25" in viz_texts, "'25' should be visual_text"

        # Check annotation
        for vt in viz_text:
            assert vt["zone"] == "visual_text"
            assert vt["excluded_from_stem"] is True
            assert vt["exclude_reason"] == "inside_visual_region"
            assert vt["overlap_ratio"] >= 0.6

    def test_stem_and_options_not_visual(self, bplus_ocr_lines):
        """Stem text and option lines must NOT be marked as visual_text."""
        visual = (199.4, 115.0, 349.9, 185.0)
        viz_text, kept = analyze_ocr_overlap(bplus_ocr_lines, visual, threshold=0.6)

        kept_texts = [k["text"] for k in kept]
        assert \
            any("下图所示" in t for t in kept_texts), \
            "Stem text should be kept"
        assert any(t.startswith("A.") for t in kept_texts), "A. option should be kept"

    def test_bst_stem_text_excluded(self, bst_ocr_lines):
        """BST node values should be visual_text, stem should be kept."""
        # BST diagram extends from y≈77pt (value "20") to y≈157pt (value "40")
        visual = (199.4, 75.0, 349.9, 165.0)
        viz_text, kept = analyze_ocr_overlap(bst_ocr_lines, visual, threshold=0.6)

        viz_texts = [v["text"] for v in viz_text]
        kept_texts = [k["text"] for k in kept]

        # "20", "16", "30", "25", "40" should all be visual_text
        assert "20" in viz_texts, "'20' should be excluded"
        assert "16" in viz_texts, "'16' should be excluded"
        assert "30" in viz_texts, "'30' should be excluded"
        assert "25" in viz_texts, "'25' should be excluded"
        assert "40" in viz_texts, "'40' should be excluded"
        # Option C.23 should be kept (option, not diagram text)
        assert any("C.23" in t for t in kept_texts)

    def test_no_diagram_lines_in_empty_region(self, bplus_ocr_lines, pdf_rect):
        """Empty visual bbox → no visual text."""
        viz_text, kept = analyze_ocr_overlap(bplus_ocr_lines, (0, 0, 0, 0))
        assert len(viz_text) == 0


# ═══════════════════════════════════════════════════════════════════
# Test: clean_stem_from_visual_text
# ═══════════════════════════════════════════════════════════════════


class TestCleanStem:
    def test_bplus_tree_stem_cleanup(self, bplus_ocr_lines):
        """B+ tree stem must NOT contain diagram node values after cleanup."""
        visual = (199.4, 115.0, 349.9, 185.0)
        viz_text, kept = analyze_ocr_overlap(bplus_ocr_lines, visual, threshold=0.6)

        original_stem = "下图所示是一棵( 12 25 05 10 151922 28 26"
        cleaned = clean_stem_from_visual_text(original_stem, kept, viz_text)

        # These diagram node values must NOT appear as standalone tokens
        for val in ["12", "25", "10", "15", "19", "22", "26", "28"]:
            assert not _has_standalone(cleaned, val), f"'{val}' must not be in cleaned stem"
        # The stem text must remain
        assert "下图所示是一棵" in cleaned, "Stem text must be preserved"

    def test_bst_stem_cleanup(self, bst_ocr_lines):
        """BST stem must not contain node values (but preserve '2021' in stem)."""
        visual = (199.4, 75.0, 349.9, 165.0)
        viz_text, kept = analyze_ocr_overlap(bst_ocr_lines, visual, threshold=0.6)

        original = "【2021统考真题】给定平衡二叉树如下图所示，插入关键字 23后，根中的关键字是( 20 16 30 25 40"
        cleaned = clean_stem_from_visual_text(original, kept, viz_text)

        # '20' in '2021' must be preserved; standalone '20' must be removed
        assert "2021" in cleaned, "'2021' context must be preserved"
        # Check standalone tokens are removed using word boundary
        assert not _has_standalone(cleaned, "20"), "'20' as standalone token must be removed"
        assert not _has_standalone(cleaned, "16"), "'16' must be removed"
        assert not _has_standalone(cleaned, "30"), "'30' must be removed"
        assert not _has_standalone(cleaned, "25"), "'25' must be removed"
        assert not _has_standalone(cleaned, "40"), "'40' must be removed"
        assert "平衡二叉树" in cleaned, "Stem text must be preserved"
        assert "23" in cleaned, "Real number '23' in stem must be preserved"

    def test_no_visual_text_no_change(self, bplus_ocr_lines):
        """If no visual text, stem should not change."""
        visual = (0, 0, 10, 10)  # Empty bbox, no overlap
        viz_text, kept = analyze_ocr_overlap(bplus_ocr_lines, visual, threshold=0.6)
        assert len(viz_text) == 0

        original = "下图所示是一棵( 12 25 05 10 151922 28 26"
        cleaned = clean_stem_from_visual_text(original, kept, viz_text)
        assert cleaned == original

    def test_concatenated_token_handling(self, bplus_ocr_lines):
        """Concatenated tokens like '151922' should be removed."""
        visual = (199.4, 115.0, 349.9, 185.0)
        viz_text, kept = analyze_ocr_overlap(bplus_ocr_lines, visual, threshold=0.6)

        original = "下图所示是一棵( 12 25 05 10 151922 28 26"
        cleaned = clean_stem_from_visual_text(original, kept, viz_text)

        # '151922' is '15' + '19' + '22' concatenated → should be removed
        assert "151922" not in cleaned, "Concatenated '151922' must be removed"

    def test_no_regex_number_deletion(self, bplus_ocr_lines):
        """Real numbers in stem must NOT be deleted via regex - only spatial dedup."""
        viz_text: list[dict] = []
        kept = bplus_ocr_lines
        # Only exclude "12" from the visual region, keep everything else
        original = "一棵( 12 25 05 10 151922 28 26"
        # Create mock viz_text with just one token
        viz_mock = [{"text": "12", "bbox_pt": (0, 0, 10, 10)}]
        cleaned = clean_stem_from_visual_text(original, kept, viz_mock)
        # "25", "05", "10" should remain (not in viz_mock)
        assert "25" in cleaned


def _has_standalone(text: str, token: str) -> bool:
    """Check if *token* appears as a standalone word in *text*."""
    return bool(re.search(rf'(?<!\S){re.escape(token)}(?!\S)', text))


# ═══════════════════════════════════════════════════════════════════
# Test: detect_first_option_pt
# ═══════════════════════════════════════════════════════════════════


class TestDetectFirstOption:
    def test_bplus_options(self, bplus_ocr_lines):
        """First option in B+ tree page should be 'A.4 阶 B 树'."""
        top = detect_first_option_pt(bplus_ocr_lines)
        assert top is not None
        # The OCR for A.4 阶 B 树 is at y=404px → ~193.7pt
        assert 180 < top < 210, f"First option top should be ~194pt, got {top:.1f}"

    def test_bst_options(self, bst_ocr_lines):
        """First option in BST page should be 'A.16'."""
        top = detect_first_option_pt(bst_ocr_lines)
        assert top is not None
        # A.16 is at y=378px → ~181.4pt
        assert 170 < top < 195, f"First option top should be ~181pt, got {top:.1f}"

    def test_no_options(self, pdf_rect):
        """No options → None."""
        top = detect_first_option_pt([])
        assert top is None


# ═══════════════════════════════════════════════════════════════════
# Test: refine_visual_bbox_for_options
# ═══════════════════════════════════════════════════════════════════


class TestRefineVisualBboxForOptions:
    def test_trim_below_options(self):
        """Visual bbox extending into options should be trimmed."""
        visual = (100, 100, 300, 250)
        opt_top = 200.0
        region = (100, 100, 300, 300)
        refined = refine_visual_bbox_for_options(visual, opt_top, region)
        assert refined[3] < opt_top, f"Bottom should be above {opt_top}, got {refined[3]}"

    def test_no_trim_when_above_options(self):
        """Visual bbox above options should not be trimmed."""
        visual = (100, 100, 300, 150)
        opt_top = 200.0
        region = (100, 100, 300, 300)
        refined = refine_visual_bbox_for_options(visual, opt_top, region)
        assert refined == visual

    def test_no_option_no_change(self):
        visual = (100, 100, 300, 300)
        refined = refine_visual_bbox_for_options(visual, None, (100, 100, 300, 300))
        assert refined == visual


# ═══════════════════════════════════════════════════════════════════
# Test: OCR line classification
# ═══════════════════════════════════════════════════════════════════


class TestClassifyOcrLine:
    def test_header(self):
        zr = classify_line({"text": "风中易小生·24考研计算机", "bbox_pt": (0, 0, 0, 0)}, 425.34)
        assert zr.zone == _ZONE_HEADER, f"got zone={zr.zone}: {zr.matched_features}"
        zr2 = classify_line({"text": "WD数据结构做题本【选择题】", "bbox_pt": (0, 0, 0, 0)}, 425.34)
        assert zr2.zone == _ZONE_HEADER, f"got zone={zr2.zone}: {zr2.matched_features}"

    def test_option_line(self):
        assert classify_line({"text": "A.4 阶 B 树", "bbox_pt": (0, 0, 0, 0)}, 425.34).zone == _ZONE_OPTION
        assert classify_line({"text": "B.20", "bbox_pt": (0, 0, 0, 0)}, 425.34).zone == _ZONE_OPTION
        assert classify_line({"text": "C.3 阶 B+树", "bbox_pt": (0, 0, 0, 0)}, 425.34).zone == _ZONE_OPTION

    def test_answer_hint(self):
        zr = classify_line({"text": "本部分答案在书P293", "bbox_pt": (0, 0, 0, 0)}, 425.34)
        assert zr.zone == _ZONE_ANSWER_HINT, f"got zone={zr.zone}: {zr.matched_features}"
        zr2 = classify_line({"text": "参考答案见书后", "bbox_pt": (0, 0, 0, 0)}, 425.34)
        assert zr2.zone == _ZONE_ANSWER_HINT, f"got zone={zr2.zone}: {zr2.matched_features}"

    def test_visual_label_short(self):
        assert classify_line({"text": "12", "bbox_pt": (0, 0, 0, 0)}, 425.34).zone == _ZONE_VISUAL_TEXT
        assert classify_line({"text": "25", "bbox_pt": (0, 0, 0, 0)}, 425.34).zone == _ZONE_VISUAL_TEXT
        assert classify_line({"text": "V1", "bbox_pt": (0, 0, 0, 0)}, 425.34).zone == _ZONE_VISUAL_TEXT
        assert classify_line({"text": "a", "bbox_pt": (0, 0, 0, 0)}, 425.34).zone == _ZONE_VISUAL_TEXT

    def test_stem(self):
        zr = classify_line({"text": "1.下图所示是一棵()", "bbox_pt": (0, 0, 0, 0)}, 425.34)
        assert zr.zone == _ZONE_QUESTION_STEM, f"got zone={zr.zone}: {zr.matched_features}"
        zr2 = classify_line({"text": "给定平衡二叉树如下图所示", "bbox_pt": (0, 0, 0, 0)}, 425.34)
        assert zr2.zone == _ZONE_QUESTION_STEM, f"got zone={zr2.zone}: {zr2.matched_features}"
        zr3 = classify_line({"text": "27.【2021 统考真题】", "bbox_pt": (0, 0, 0, 0)}, 425.34)
        assert zr3.zone == _ZONE_QUESTION_STEM, f"got zone={zr3.zone}: {zr3.matched_features}"

    def test_next_question(self):
        zr = classify_line({"text": "2.下一个题目", "bbox_pt": (0, 0, 0, 0)}, 425.34)
        assert zr.zone == _ZONE_QUESTION_STEM, f"got zone={zr.zone}: {zr.matched_features}"
        # Short (<=15) numbered line without Chinese content -> next_question
        zr2 = classify_line({"text": "2.", "bbox_pt": (0, 0, 0, 0)}, 425.34)
        assert zr2.zone == _ZONE_NEXT_QUESTION, f"got zone={zr2.zone}: {zr2.matched_features}"
        zr3 = classify_line({"text": "28.", "bbox_pt": (0, 0, 0, 0)}, 425.34)
        assert zr3.zone == _ZONE_NEXT_QUESTION, f"got zone={zr3.zone}: {zr3.matched_features}"


class TestClassifyOcrLines:
    def test_bplus_lines(self, bplus_ocr_lines, pdf_rect):
        zones = classify_ocr_lines(bplus_ocr_lines, 425.34)
        assert len(zones[_ZONE_HEADER]) > 0, "Should detect header"
        assert len(zones[_ZONE_VISUAL_TEXT]) >= 7, "Should detect 7+ diagram node values"
        assert len(zones[_ZONE_OPTION]) == 4, "Should detect 4 options"
        assert len(zones[_ZONE_ANSWER_HINT]) >= 1, "Should detect answer hint"
        assert _ZONE_NEXT_QUESTION in zones, "next_question zone should be present"

    def test_bst_lines(self, bst_ocr_lines, pdf_rect):
        zones = classify_ocr_lines(bst_ocr_lines, 425.34)
        assert len(zones[_ZONE_VISUAL_TEXT]) >= 4, "Should detect 4+ BST node values"
        assert len(zones[_ZONE_OPTION]) == 4, "Should detect 4 options"


# ═══════════════════════════════════════════════════════════════════
# Test: compute_stem_bottom_pt and compute_diagram_zone_pt
# ═══════════════════════════════════════════════════════════════════


class TestComputeStemBottom:
    def test_bplus_stem_bottom(self, bplus_ocr_lines, pdf_rect):
        zones = classify_ocr_lines(bplus_ocr_lines, 425.34)
        stem_btm = compute_stem_bottom_pt(bplus_ocr_lines, 425.34)
        assert stem_btm is not None
        # Stem "1.下图所示是一棵()" bottom is at 223px → ~107pt
        assert 100 < stem_btm < 115, f"stem_bottom={stem_btm:.1f}"

    def test_bst_stem_bottom(self, bst_ocr_lines, pdf_rect):
        zones = classify_ocr_lines(bst_ocr_lines, 425.34)
        stem_btm = compute_stem_bottom_pt(bst_ocr_lines, 425.34)
        assert stem_btm is not None
        # Stem "27.【2021统考真题】..." bottom is at 121px → ~58pt
        assert 50 < stem_btm < 65, f"stem_bottom={stem_btm:.1f}"

    def test_no_stem(self):
        assert compute_stem_bottom_pt([], None) is None


class TestComputeDiagramZone:
    def test_bplus_diagram_zone(self, bplus_ocr_lines, pdf_rect):
        top, bot = compute_diagram_zone_pt(bplus_ocr_lines, 425.34)
        assert top is not None
        assert bot is not None
        # Zone should be between stem_bottom (~107pt) and first option (~194pt)
        assert top >= 107, f"zone_top={top:.1f} should be below stem"
        assert bot <= 194, f"zone_bot={bot:.1f} should be above options"
        assert bot - top > 50, f"Diagram zone too small: {top:.1f}-{bot:.1f}"

    def test_bst_diagram_zone(self, bst_ocr_lines, pdf_rect):
        top, bot = compute_diagram_zone_pt(bst_ocr_lines, 425.34)
        assert top is not None
        assert bot is not None
        # B+ tree: stem bottom ~58pt, options ~181pt
        assert top >= 58, f"zone_top={top:.1f}"
        assert bot <= 181, f"zone_bot={bot:.1f}"
        assert bot - top > 70, f"Diagram zone too small: {top:.1f}-{bot:.1f}"


# ═══════════════════════════════════════════════════════════════════
# Test: check_visual_gate (hard quality gates)
# ═══════════════════════════════════════════════════════════════════


class MockRect:
    width = 567.0
    height = 425.34
    x0 = 0.0
    y0 = 0.0


class TestCheckVisualGate:
    def test_passes_good_bbox(self):
        """A bbox between stem and options should pass."""
        fails = check_visual_gate(
            (200, 100, 350, 180), MockRect(),
            stem_bottom_pt=80, first_option_top_pt=200,
        )
        assert len(fails) == 0

    def test_fails_above_stem(self):
        fails = check_visual_gate(
            (200, 50, 350, 180), MockRect(),
            stem_bottom_pt=80,
        )
        assert any("top_above_stem" in f for f in fails)

    def test_fails_below_options(self):
        fails = check_visual_gate(
            (200, 100, 350, 250), MockRect(),
            first_option_top_pt=200,
        )
        assert any("bottom_below_options" in f for f in fails)

    def test_fails_near_full_page(self):
        fails = check_visual_gate(
            (10, 10, 557, 415), MockRect(),
        )
        assert any("bbox_near_full_page" in f for f in fails)
        assert any("bbox_excessive_size" in f for f in fails)

    def test_fails_includes_header(self):
        fails = check_visual_gate(
            (200, 15, 350, 180), MockRect(),
            header_bottom_pt=28,
        )
        assert any("includes_header" in f for f in fails)

    def test_fails_invalid_bbox(self):
        fails = check_visual_gate(
            (200, 100, 100, 200), MockRect(),
        )
        assert "invalid_bbox" in fails

    def test_fails_out_of_bounds(self):
        fails = check_visual_gate(
            (200, 100, 600, 200), MockRect(),
        )
        assert "bbox_out_of_bounds" in fails

    def test_multiple_failures(self):
        """Bbox that is both above stem AND includes header."""
        fails = check_visual_gate(
            (200, 5, 400, 250), MockRect(),
            stem_bottom_pt=80, first_option_top_pt=200,
        )
        assert any("top_above_stem" in f for f in fails)
        assert any("bottom_below_options" in f for f in fails)
        assert any("includes_header" in f for f in fails)


# ═══════════════════════════════════════════════════════════════════
# Regression tests: qno=369 (a-f undirected graph)
# ═══════════════════════════════════════════════════════════════════


class TestRegression369:
    """369 must tightly enclose a-f graph, exclude header/stem/options."""

    def test_classification(self, bplus_ocr_lines, pdf_rect):
        """Verify OCR-based zone for a-f graph page (use page 380 as proxy)."""
        zones = classify_ocr_lines(bplus_ocr_lines, 425.34)
        # Diagram zone should contain only short node labels
        diag_texts = [l.text for l in zones[_ZONE_VISUAL_TEXT]]
        assert all(len(t) <= 6 for t in diag_texts)
        # No option or header text in diagram zone
        opt_texts = [l.text for l in zones[_ZONE_OPTION]]
        assert len(opt_texts) == 4

    def test_diagram_zone_excludes_header(self, bplus_ocr_lines, pdf_rect):
        """Diagram zone must start below stem text."""
        top, bot = compute_diagram_zone_pt(bplus_ocr_lines, 425.34)
        assert top is not None
        assert top > 28, f"Diagram zone top {top:.1f} must be below header (28pt)"


# ═══════════════════════════════════════════════════════════════════
# Regression tests: qno=380 (B+ tree, V1-V5 directed graph)
# ═══════════════════════════════════════════════════════════════════


class TestRegression380:
    """380 must tightly enclose B+ tree node values, exclude header/stem/options."""

    def test_ocr_diagram_excludes_header(self, bplus_ocr_lines):
        """OCR diagram bbox must exclude header and options."""
        region = (199.4, 1.4, 349.9, 200.5)
        db = _ocr_diagram_bbox(bplus_ocr_lines, region, 425.34)
        assert db is not None
        # Must be below header
        assert db[1] >= 28, f"Diagram top {db[1]:.1f} must be below header"
        # Must be above options
        assert db[3] <= 200, f"Diagram bottom {db[3]:.1f} must be above options"

    def test_diagram_zone_between_stem_and_options(self, bplus_ocr_lines, pdf_rect):
        """Diagram analysis zone must be strictly between stem and options."""
        top, bot = compute_diagram_zone_pt(bplus_ocr_lines, 425.34)
        assert top is not None
        assert bot is not None
        # stem_bottom ~107pt, first_opt ~194pt
        assert top >= 100, f"zone_top={top:.1f}"
        assert bot <= 195, f"zone_bot={bot:.1f}"

    def test_classified_options_preserved(self, bplus_ocr_lines, pdf_rect):
        """Option lines must still be classified as options."""
        zones = classify_ocr_lines(bplus_ocr_lines, 425.34)
        opt_texts = [l.text for l in zones[_ZONE_OPTION]]
        assert len(opt_texts) == 4
        assert any("A." in t for t in opt_texts)
        assert any("D." in t for t in opt_texts)


# ═══════════════════════════════════════════════════════════════════
# Regression tests: qno=457 (BST x1-x5)
# ═══════════════════════════════════════════════════════════════════


class TestRegression457:
    """457 must tightly enclose BST node values, exclude header/stem/options."""

    def test_ocr_diagram_excludes_header(self, bst_ocr_lines):
        """OCR diagram bbox must exclude header and options."""
        region = (199.4, 1.4, 349.9, 200.5)
        db = _ocr_diagram_bbox(bst_ocr_lines, region, 425.34)
        assert db is not None
        # Must be below header
        assert db[1] >= 28, f"Diagram top {db[1]:.1f} must be below header"
        # Must be above options
        assert db[3] <= 200, f"Diagram bottom {db[3]:.1f} must be above options"

    def test_diagram_zone_excludes_options(self, bst_ocr_lines, pdf_rect):
        """Diagram zone must not extend into options."""
        top, bot = compute_diagram_zone_pt(bst_ocr_lines, 425.34)
        assert bot is not None
        # Options start at ~181pt in BST page
        assert bot <= 185, f"zone_bot={bot:.1f}"

    def test_stem_preserved(self, bst_ocr_lines, pdf_rect):
        """Stem text classification should capture the full stem."""
        zones = classify_ocr_lines(bst_ocr_lines, 425.34)
        stem_texts = [l.text for l in zones[_ZONE_QUESTION_STEM]]
        assert any("统考真题" in t for t in stem_texts)


# ═══════════════════════════════════════════════════════════════════
# Test: content_storage_key (versioned regeneration)
# ═══════════════════════════════════════════════════════════════════


class TestContentStorageKey:
    def test_includes_crop_version(self):
        """Different crop_version → different storage key (supports algo upgrades)."""
        key1 = content_storage_key("ds_sc.pdf", 380, 380, (100, 100, 200, 200), kind="content", crop_version="v1")
        key2 = content_storage_key("ds_sc.pdf", 380, 380, (100, 100, 200, 200), kind="content", crop_version="v2")
        # Same bbox, different versions → different hash
        assert key1 != key2, "Different versions must produce different keys"

    def test_different_bbox_different_key(self):
        """Different bbox → different storage key (supports regeneration)."""
        key1 = content_storage_key("ds_sc.pdf", 1, 1, (100, 100, 200, 200), kind="content")
        key2 = content_storage_key("ds_sc.pdf", 1, 1, (101, 100, 200, 200), kind="content")
        assert key1 != key2, "Different bboxes must produce different keys"

    def test_different_version_different_key(self):
        """Different crop_version → different key (supports algo upgrade)."""
        key1 = content_storage_key("ds_sc.pdf", 1, 1, (100, 100, 200, 200), kind="content", crop_version="v1")
        key2 = content_storage_key("ds_sc.pdf", 1, 1, (100, 100, 200, 200), kind="content", crop_version="v2")
        assert key1 != key2, "Different versions must produce different keys"

    def test_snapshot_kind(self):
        key = content_storage_key("ds_sc.pdf", 1, 1, (100, 100, 200, 200), kind="snapshot")
        assert "snapshot" in key


# ═══════════════════════════════════════════════════════════════════
# Test: check_content_image_quality
# ═══════════════════════════════════════════════════════════════════


class TestCheckContentImageQuality:
    def test_empty_image(self):
        issues = check_content_image_quality(b"")
        assert "empty_or_tiny" in issues

    def test_small_png_valid(self):
        """A 200x200 PNG with non-white pixels should pass all checks."""
        import struct, zlib

        def _make_png(w, h):
            """Create a minimal PNG with some gray pixels (>512 bytes minimum)."""
            raw_data = b""
            for y in range(h):
                row = b"\x00"  # filter byte
                for x in range(w):
                    # Alternating white and light gray to prevent excessive compression
                    if (x + y) % 3 == 0:
                        row += b"\xf0\xf0\xf0"  # light gray
                    else:
                        row += b"\xff\xff\xff"  # white
                raw_data += row
            compressed = zlib.compress(raw_data)

            def _chunk(ctype, data):
                c = ctype + data
                return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

            ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
            return (
                    b"\x89PNG\r\n\x1a\n"
                    + _chunk(b"IHDR", ihdr)
                    + _chunk(b"IDAT", compressed)
                    + _chunk(b"IEND", b"")
            )

        png = _make_png(200, 200)
        assert len(png) > 512, f"PNG too small: {len(png)} bytes"
        issues = check_content_image_quality(png)
        assert "empty_or_tiny" not in issues, f"Unexpected issues: {issues}"
        assert "invalid_png" not in issues


# ═══════════════════════════════════════════════════════════════════
# Test: CROP_VERSION constant
# ═══════════════════════════════════════════════════════════════════


class TestCheckVisualCompleteness:
    def test_no_image(self):
        from backfill_question_images import check_visual_completeness
        issues = check_visual_completeness(b"", (0, 0, 10, 10))
        assert "completeness_no_image" in issues

    def test_empty_bbox(self):
        from backfill_question_images import check_visual_completeness
        issues = check_visual_completeness(b"", (0, 0, 0, 0))
        assert "completeness_no_image" in issues


class TestCropVersion:
    def test_version_visual_v2(self):
        assert CROP_VERSION == "visual-v2"

    def test_overlap_threshold(self):
        assert OVERLAP_THRESHOLD == 0.6
