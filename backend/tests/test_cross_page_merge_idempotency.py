"""Cross-Page Merge Idempotency Tests.

Verifies that:
1. Multiple calls to ``_merge_cross_page_blocks`` do not duplicate text
2. ``_cross_page_revision`` tracking prevents re-merge
3. Merge results are traceable via ``CrossPageMergeResult``
"""

from __future__ import annotations

from app.features.cross_page_linking import CrossPageLink
from app.features.pipeline_orchestrator import _apply_cross_page_block_merge


class TestCrossPageMergeIdempotency:
    """Verify that cross-page merge is idempotent."""

    def _make_page_mock(self, page_id, page_index, text, region_ids=None):
        """Create a minimal page mock for test purposes."""
        class MockRegion:
            def __init__(self, region_id, text):
                self.region_id = region_id
                self.region_type = "text"
                self.text = text

        class MockPage:
            def __init__(self, page_id, page_index, text, region_ids):
                self.page_id = page_id
                self.page_index = page_index
                self.height = 1000
                self.regions = [
                    MockRegion(rid, text) for rid in (region_ids or [f"{page_id}_r0"])
                ]

        return MockPage(page_id, page_index, text, region_ids)

    def _make_doc_ir_mock(self, pages):
        """Create a minimal DocumentIR mock."""
        class MockDocIR:
            def __init__(self, pages):
                self.pages = pages
                self.pipeline_fingerprint = "test"

        return MockDocIR(pages)

    def test_idempotent_no_text_duplication(self):
        """Second call with same links does not duplicate text."""
        source_page = self._make_page_mock("p0", 0, "1. 题目", region_ids=["p0_r0"])
        target_page = self._make_page_mock("p1", 1, "A. 选项\nB. 选项二", region_ids=["p1_r0"])
        doc = self._make_doc_ir_mock([source_page, target_page])

        link = CrossPageLink(
            source_page_id="p0",
            target_page_id="p1",
            link_type="option_continuation",
            confidence=0.7,
            reason_codes=["CROSS_PAGE_EXPLICIT_MARKER"],
        )

        blocks = [{"page": 1, "block_index": 0, "normalized_text": "1. 题目"}]

        # First call
        merged1, results1 = _apply_cross_page_block_merge(blocks, [link], doc)
        assert "A. 选项" in merged1[0]["normalized_text"]
        assert len(results1) == 1
        assert results1[0]["revision"] == 1
        assert results1[0]["applied_link_ids"] == ["p0->p1"]

        # Second call — should NOT append text again
        merged2, results2 = _apply_cross_page_block_merge(merged1, [link], doc)
        text_once = merged2[0]["normalized_text"]
        # Count occurrences of "A. 选项"
        assert text_once.count("A. 选项") == 1, (
            f"Expected 1 occurrence of 'A. 选项', got {text_once.count('A. 选项')}"
        )
        assert len(results2) == 0  # no new merge results

    def test_cross_page_merge_result_traceability(self):
        """Merge results contain all traceability fields."""
        source_page = self._make_page_mock("p0", 0, "1. 题目")
        target_page = self._make_page_mock("p1", 1, "A. 续")
        doc = self._make_doc_ir_mock([source_page, target_page])

        link = CrossPageLink(
            source_page_id="p0",
            target_page_id="p1",
            link_type="stem_continuation",
            confidence=0.9,
            reason_codes=["CROSS_PAGE_EXPLICIT_MARKER"],
        )
        blocks = [{"page": 1, "block_index": 0, "normalized_text": "1. 题目"}]
        _, results = _apply_cross_page_block_merge(blocks, [link], doc)

        assert len(results) == 1
        r = results[0]
        assert "merged_block_id" in r
        assert "source_block_ids" in r
        assert "source_page_ids" in r
        assert "source_region_ids" in r
        assert "applied_link_ids" in r
        assert r["revision"] >= 1
        assert r["link_confidence"] == 0.9
        assert "CROSS_PAGE_EXPLICIT_MARKER" in r["reason_codes"]

    def test_ambiguous_links_produce_no_merge_results(self):
        """Ambiguous links are skipped and produce no merge results."""
        source_page = self._make_page_mock("p0", 0, "1. 题目")
        target_page = self._make_page_mock("p1", 1, "（接上页）\n2. 新题")
        doc = self._make_doc_ir_mock([source_page, target_page])

        link = CrossPageLink(
            source_page_id="p0",
            target_page_id="p1",
            link_type="stem_continuation",
            confidence=0.3,
            reason_codes=["CROSS_PAGE_PREV_NEAR_BOTTOM_NO_END"],
            is_ambiguous=True,
        )
        blocks = [{"page": 1, "block_index": 0, "normalized_text": "1. 题目"}]
        merged, results = _apply_cross_page_block_merge(blocks, [link], doc)

        assert len(results) == 0
        assert "2. 新题" not in merged[0].get("normalized_text", "")

    def test_idempotent_with_revision_tracking(self):
        """Blocks track _cross_page_revision to skip duplicate merges."""
        p0 = self._make_page_mock("p0", 0, "1. 题目")
        p1 = self._make_page_mock("p1", 1, "A. 续1")
        p2 = self._make_page_mock("p2", 2, "B. 续2")
        doc = self._make_doc_ir_mock([p0, p1, p2])

        link1 = CrossPageLink(
            source_page_id="p0", target_page_id="p1",
            link_type="stem_continuation", confidence=0.8,
            reason_codes=["CROSS_PAGE_EXPLICIT_MARKER"],
        )
        link2 = CrossPageLink(
            source_page_id="p0", target_page_id="p2",
            link_type="stem_continuation", confidence=0.7,
            reason_codes=["CROSS_PAGE_EXPLICIT_MARKER"],
        )

        blocks = [{"page": 1, "block_index": 0, "normalized_text": "1. 题目"}]

        # First merge — both links applied
        merged1, results1 = _apply_cross_page_block_merge(blocks, [link1, link2], doc)
        assert len(results1) == 2
        assert merged1[0].get("_cross_page_revision", 0) == 2

        # Second merge — no duplicate
        merged2, results2 = _apply_cross_page_block_merge(merged1, [link1, link2], doc)
        assert len(results2) == 0
        # Text only has one occurrence of each
        text = merged2[0]["normalized_text"]
        assert text.count("续1") == 1
        assert text.count("续2") == 1
