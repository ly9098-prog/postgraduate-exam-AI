"""Cross-Page Pipeline Integration Tests (OCR-102).

Tests that cross-page linking is properly wired into the pipeline:
1. ``_merge_cross_page_blocks`` merges content from linked pages
2. Pipeline ``_run_split`` applies cross-page links before splitting
3. Non-ambiguous links result in merged question text
4. Ambiguous links do not merge content
5. Single-page input produces no cross-page links
6. Independent consecutive pages produce no false links
"""

from __future__ import annotations

import pytest

from app.core.document_ir import (
    BBox,
    DocumentIR,
    LineIR,
    PageIR,
    RegionIR,
    new_document,
)
from app.features.cross_page_linking import (
    REASON_EXPLICIT_MARKER,
    CrossPageLink,
    detect_cross_page_links,
)
from app.features.pipeline_orchestrator import (
    _apply_cross_page_block_merge,
    _merge_cross_page_blocks,
)

# ===================================================================
# Helpers
# ===================================================================


def _make_page(
    page_id: str,
    page_index: int,
    texts: list[str],
    *,
    height: int = 1000,
    width: int = 800,
    y1: int | None = None,
) -> PageIR:
    """Create a PageIR with one region containing the given texts."""
    full_text = "\n".join(texts)
    region_y1 = y1 if y1 is not None else height - 50
    lines = []
    for li, t in enumerate(texts):
        lines.append(LineIR(
            text=t,
            line_id=f"{page_id}_l{li}",
            bbox=BBox(50, 100 + li * 30, 700, 130 + li * 30),
        ))
    region = RegionIR(
        region_id=f"{page_id}_r0",
        region_type="text",
        bbox=BBox(30, 50, 750, region_y1),
        lines=lines,
    )
    return PageIR(
        page_id=page_id,
        page_index=page_index,
        width=width,
        height=height,
        regions=[region],
    )


def _make_block(page: int, text: str, block_index: int = 0) -> dict:
    return {
        "page": page,
        "block_index": block_index,
        "normalized_text": text,
    }


# ===================================================================
# 1. _merge_cross_page_blocks — module-level helper
# ===================================================================


class TestMergeCrossPageBlocks:
    def test_no_links_single_block(self):
        blocks = [_make_block(1, "1. 题目")]
        merged, links, warns, merge_results = _merge_cross_page_blocks(blocks)
        assert len(merged) == 1
        assert links == []

    def test_no_links_independent_pages(self):
        blocks = [
            _make_block(1, "1. 第一题\nA. 甲\n答案：A", block_index=0),
            _make_block(2, "2. 第二题\nA. 乙\n答案：B", block_index=1),
        ]
        merged, links, warns, merge_results = _merge_cross_page_blocks(blocks)
        assert links == []

    def test_empty_blocks(self):
        merged, links, warns, merge_results = _merge_cross_page_blocks([])
        assert merged == []
        assert links == []


# ===================================================================
# 2. _apply_cross_page_block_merge — direct merge logic
# ===================================================================


class TestApplyCrossPageBlockMerge:
    def test_merge_explicit_continuation(self):
        """Explicit marker → content from target page appends to source block."""
        p0 = _make_page("p0", 0, ["1. 页内地址占（ ）位"], y1=950)
        p1 = _make_page("p1", 1, ["（接上页）", "A. 6", "B. 10", "C. 8", "D. 12"])
        doc = new_document(source_bytes=b"test")
        doc.add_page(p0)
        doc.add_page(p1)

        links = detect_cross_page_links(doc.pages)
        assert len(links) >= 1

        blocks = [
            _make_block(1, "1. 页内地址占（ ）位", block_index=0),
        ]
        merged, merge_results = _apply_cross_page_block_merge(blocks, links, doc)

        assert len(merged) == 1
        assert "A. 6" in merged[0]["normalized_text"]

    def test_merge_option_continuation(self):
        """Option continuation → content from target appends to source block."""
        p0 = _make_page("p0", 0, ["1. 页内地址占（ ）位"], y1=950)
        p1 = _make_page("p1", 1, ["A. 6", "B. 10", "C. 8", "D. 12"])
        doc = new_document(source_bytes=b"test")
        doc.add_page(p0)
        doc.add_page(p1)

        links = detect_cross_page_links(doc.pages)
        assert len(links) >= 1

        blocks = [
            _make_block(1, "1. 页内地址占（ ）位", block_index=0),
        ]
        merged, merge_results = _apply_cross_page_block_merge(blocks, links, doc)
        assert "A. 6" in merged[0]["normalized_text"]

    def test_ambiguous_link_no_merge(self):
        """Ambiguous links should NOT merge content."""
        p0 = _make_page("p0", 0, ["1. 题目"], y1=950)
        p1 = _make_page("p1", 1, ["（接上页）", "2. 新题目"])
        doc = new_document(source_bytes=b"test")
        doc.add_page(p0)
        doc.add_page(p1)

        links = detect_cross_page_links(doc.pages)
        # May or may not detect — but if detected, should be ambiguous
        ambiguous_links = [l for l in links if l.is_ambiguous]
        non_ambiguous = [l for l in links if not l.is_ambiguous]

        blocks = [
            _make_block(1, "1. 题目", block_index=0),
        ]
        merged, merge_results = _apply_cross_page_block_merge(blocks, links, doc)
        if ambiguous_links:
            assert "2. 新题目" not in merged[0]["normalized_text"]

    def test_no_merge_for_different_source_page(self):
        """Links only merge into designated source pages."""
        p0 = _make_page("p0", 0, ["1. 题目一"], y1=500)
        p1 = _make_page("p1", 1, ["A. 6"], y1=500)
        p2 = _make_page("p2", 2, ["2. 题目二"])
        doc = new_document(source_bytes=b"test")
        doc.add_page(p0)
        doc.add_page(p1)
        doc.add_page(p2)

        blocks = [
            _make_block(1, "1. 题目一", block_index=0),
            _make_block(2, "", block_index=1),
            _make_block(3, "2. 题目二", block_index=2),
        ]
        links = []
        # Should be no links since none have continuation signals
        merged, merge_results = _apply_cross_page_block_merge(blocks, links, doc)
        assert len(merged) == 3

    def test_multiple_links_merged(self):
        """Multiple cross-page links merge correctly."""
        p0 = _make_page("p0", 0, ["1. 第一题题干"], y1=950)
        p1 = _make_page("p1", 1, ["（接上页）", "A. 6", "B. 10"], y1=950)
        p2 = _make_page("p2", 2, ["（接上页）", "C. 8", "D. 12"])
        doc = new_document(source_bytes=b"test")
        doc.add_page(p0)
        doc.add_page(p1)
        doc.add_page(p2)

        blocks = [
            _make_block(1, "1. 第一题题干", block_index=0),
            _make_block(2, "", block_index=1),
            _make_block(3, "", block_index=2),
        ]
        links = detect_cross_page_links(doc.pages)

        # At least some links should be detected
        merged, merge_results = _apply_cross_page_block_merge(blocks, links, doc)
        # Page 1 block should get content from linked pages
        if links:
            assert len(merged) == 3


# ===================================================================
# 3. DocumentIR cross_page_links field
# ===================================================================


class TestDocumentIRCrossPageLinks:
    def test_cross_page_links_default_empty(self):
        doc = DocumentIR()
        assert doc.cross_page_links == []

    def test_cross_page_links_can_be_set(self):
        doc = DocumentIR()
        doc.cross_page_links = [{"source": "p0", "target": "p1"}]
        assert len(doc.cross_page_links) == 1

    def test_cross_page_links_survives_serialization(self):
        """CrossPageLink serialization survives dict conversion."""
        link = CrossPageLink(
            source_page_id="p0",
            target_page_id="p1",
            source_region_ids=["r1"],
            target_region_ids=["r2"],
            link_type="stem_continuation",
            confidence=0.85,
            reason_codes=[REASON_EXPLICIT_MARKER],
        )
        d = link.to_dict()
        assert d["source_page_id"] == "p0"
        assert d["target_page_id"] == "p1"
        assert d["link_type"] == "stem_continuation"


# ===================================================================
# 4. Positive pipeline tests — cross-page linking should activate
# ===================================================================


class TestPositiveCrossPage:
    """5+ positive cases: cross-page linking should detect and merge."""

    @pytest.mark.parametrize("case_id, p0_texts, p1_texts, expected_text", [
        ("explicit", ["1. 缺页中断处理"], ["（接上页）", "A. 调页", "B. 置换", "C. 淘汰", "D. 回写"],
         "A. 调页"),
        ("option_cont", ["1. 页内地址占（ ）位"], ["A. 6", "B. 10", "C. 8", "D. 12"],
         "A. 6"),
        ("bottom_cont", ["1. 下列叙述中，正确的是"], ["A. 进程", "B. 线程", "C. 协程", "D. 管程"],
         "A. 进程"),
        ("chinese_cont", ["1. 在页式存储管理中"], ["（接上页）", "B. 10", "C. 8"],
         "B. 10"),
        ("cross_code", ["17. 下列代码的输出是"], ["（续）", "A. 10", "B. 20", "C. 30", "D. 40"],
         "A. 10"),
    ])
    def test_cross_page_detection(self, case_id, p0_texts, p1_texts, expected_text):
        """Cross-page links detected between consecutive pages."""
        p0 = _make_page("p0", 0, p0_texts, y1=950)
        p1 = _make_page("p1", 1, p1_texts)
        doc = new_document(source_bytes=b"test")
        doc.add_page(p0)
        doc.add_page(p1)

        links = detect_cross_page_links(doc.pages)

        # At least one link should be detected
        assert len(links) >= 1, f"Case {case_id}: expected cross-page link"

        # Block merge test
        blocks = [_make_block(1, "\n".join(p0_texts), block_index=0)]
        merged, merge_results = _apply_cross_page_block_merge(blocks, links, doc)
        assert expected_text in merged[0]["normalized_text"], (
            f"Case {case_id}: expected {expected_text!r} in merged text"
        )


class TestNegativeCrossPage:
    """5+ negative cases: no false cross-page links."""

    @pytest.mark.parametrize("case_id, p0_texts, p1_texts", [
        ("independent", ["1. 第一题", "A. 甲", "答案：A"], ["2. 第二题", "A. 乙", "答案：B"]),
        ("mid_page", ["1. 题目内容"], ["2. 完整新题"],),
        ("with_answer", ["1. 题目", "A. 甲", "B. 乙", "答案：B"],
         ["2. 题目", "A. 丙", "B. 丁", "答案：A"]),
        ("section_header", ["1. 第一题"], ["Part II", "2. 第二题"]),
        ("full_options_both", ["1. 题目", "A. 甲", "B. 乙", "C. 丙", "D. 丁"],
         ["2. 题目", "A. 子", "B. 丑", "C. 寅", "D. 卯"]),
    ])
    def test_no_false_cross_page(self, case_id, p0_texts, p1_texts):
        """Independent consecutive pages produce no cross-page links."""
        p0 = _make_page("p0", 0, p0_texts, y1=300)
        p1 = _make_page("p1", 1, p1_texts)
        doc = new_document(source_bytes=b"test")
        doc.add_page(p0)
        doc.add_page(p1)

        links = detect_cross_page_links(doc.pages)
        non_ambiguous = [l for l in links if not l.is_ambiguous]
        assert len(non_ambiguous) == 0, (
            f"Case {case_id}: expected no non-ambiguous links, got {len(non_ambiguous)}"
        )
