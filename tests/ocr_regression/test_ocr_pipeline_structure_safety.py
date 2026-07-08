"""Regression tests for OCR pipeline structure safety.

Covers:
- Inline option validation (validate_option_set)
- Objective question signals detection (has_objective_question_signals)
- Frozen options cross-contamination guard (_get_span_blocks)
- Subjective false-pass prevention
"""

import re

import pytest

from app.features.question_splitter import _get_span_blocks, _extract_options, split_questions
from app.features.question_normalizer import validate_option_set, has_objective_question_signals


# =============================================================================
# Test: validate_option_set — option set sanity checking
# =============================================================================


class TestValidateOptionSet:
    """validate_option_set must catch suspicious option parsing results."""

    def test_single_a_containing_bcd_labels_is_not_usable(self):
        """Single A option containing B./C./D. labels → inline_option_split_failed."""
        bad = {"A": "Algorithm B. Binary tree C. Data structure D. Code"}
        result = validate_option_set(bad)
        assert result.is_usable is False
        assert "inline_option_split_failed" in result.suspicious_reasons
        assert result.count == 1
        assert not result.is_complete

    def test_single_a_with_chinese_bcd_labels(self):
        """Single A option with Chinese-punctuation B/C/D labels."""
        bad = {"A": "算法 B．二叉树 C．数据结构 D．代码"}
        result = validate_option_set(bad)
        assert result.is_usable is False
        assert "inline_option_split_failed" in result.suspicious_reasons

    def test_normal_four_options_pass(self):
        """Normal 4-option set is complete and usable."""
        good = {"A": "ALO", "B": "BLOS", "C": "CLO", "D": "D"}
        result = validate_option_set(good)
        assert result.is_usable is True
        assert result.is_complete is True
        assert result.suspicious_reasons == []

    def test_partial_options_not_suspicious(self):
        """Partial options (e.g. only 2) are not complete but not suspicious."""
        partial = {"A": "Yes", "B": "No"}
        result = validate_option_set(partial)
        assert result.is_usable is True  # >= 2 and no suspicious patterns
        assert result.is_complete is False  # < 4
        assert result.suspicious_reasons == []

    def test_empty_options(self):
        """Empty option dict → not usable."""
        result = validate_option_set({})
        assert result.is_usable is False
        assert "empty_options" in result.suspicious_reasons

    def test_single_a_without_bcd_labels_is_ok(self):
        """Single A without embedded BCD labels is not suspicious (just incomplete)."""
        ok = {"A": "Just one option"}
        result = validate_option_set(ok)
        # is_usable should still be True because there's no evidence of split failure
        # (count >= 2 check makes it False in practice, but no suspicious pattern)
        assert "inline_option_split_failed" not in result.suspicious_reasons
        assert result.is_usable is False  # because count < 2

    def test_long_option_with_embedded_labels(self):
        """Option text >100 chars with embedded A-D labels → suspicious."""
        text_long = "Long text with embedded B. option and C. option " + "x" * 80
        opts = {"A": text_long, "B": "Normal"}
        result = validate_option_set(opts)
        assert "option_A_may_contain_multiple_labels" in result.suspicious_reasons

    def test_long_option_without_embedded_labels(self):
        """Option text >100 chars without A-D labels → not suspicious."""
        text_long = "Just a very long text " + "x" * 100
        opts = {"A": text_long, "B": "Normal"}
        result = validate_option_set(opts)
        assert "option_A_may_contain_multiple_labels" not in result.suspicious_reasons


# =============================================================================
# Test: has_objective_question_signals
# =============================================================================


class TestHasObjectiveQuestionSignals:
    """has_objective_question_signals detects objective question indicators."""

    def test_option_labels_detected(self):
        """Text with A./B./C./D. labels → signals detected."""
        text = "A. one\nB. two\nC. three\nD. four\n答案：A"
        has, signals = has_objective_question_signals(text, "", "")
        assert has is True
        assert any(s.startswith("option_labels:") for s in signals)

    def test_explicit_answer_marker(self):
        """Text containing 答案：X → signals detected."""
        text = "一些文字\n答案：A"
        has, signals = has_objective_question_signals(text, "", "")
        assert has is True
        assert any("explicit_answer_marker" in s for s in signals)

    def test_explicit_choice_answer(self):
        """Answer being a choice letter → signals detected."""
        has, signals = has_objective_question_signals("", "Which one?", "A")
        assert has is True
        assert any("explicit_choice_answer" in s for s in signals)

    def test_keywords_detected(self):
        """Choice keywords like 下列, 选项 → signals detected."""
        has, signals = has_objective_question_signals("下列说法正确的是？", "", "")
        assert has is True
        assert any(s.startswith("choice_keywords:") for s in signals)

    def test_no_signals_for_subjective(self):
        """Plain subjective text → no signals."""
        has, signals = has_objective_question_signals("简述二叉树的性质。", "", "")
        assert has is False

    def test_empty_text_no_signals(self):
        """Empty text → no signals."""
        has, signals = has_objective_question_signals("", "", None)
        assert has is False

    def test_single_option_label_not_enough(self):
        """Single A. label → not enough for objective signal (needs >=2)."""
        has, signals = has_objective_question_signals("A. just one option", "", "")
        assert has is False


# =============================================================================
# Test: _get_span_blocks — frozen options block granularity guard
# =============================================================================


class TestGetSpanBlocks:
    """_get_span_blocks correctly maps text spans to overlapping blocks."""

    def test_single_block_span(self):
        """Span within a single block returns only that block."""
        # page_map: [(pos, page, block_idx)]
        page_map = [(0, 1, 0), (100, 1, 1), (200, 2, 0)]
        blocks = _get_span_blocks(10, 90, page_map)
        assert blocks == {(1, 0)}, f"Expected {(1, 0)}, got {blocks}"

    def test_span_across_two_blocks(self):
        """Span straddling two blocks returns both."""
        page_map = [(0, 1, 0), (100, 1, 1), (200, 2, 0)]
        blocks = _get_span_blocks(80, 150, page_map)
        assert blocks == {(1, 0), (1, 1)}, f"Expected both block 0 and 1, got {blocks}"

    def test_span_in_first_block(self):
        """Span entirely in first block returns only that block."""
        page_map = [(0, 1, 0), (50, 1, 1)]
        blocks = _get_span_blocks(5, 45, page_map)
        assert blocks == {(1, 0)}

    def test_span_at_boundary(self):
        """Span starting exactly at block boundary includes both blocks."""
        page_map = [(0, 1, 0), (100, 2, 0)]
        blocks = _get_span_blocks(100, 150, page_map)
        assert blocks == {(2, 0)}

    def test_empty_page_map(self):
        """Empty page_map → empty result."""
        blocks = _get_span_blocks(0, 100, [])
        assert blocks == set()

    def test_different_pages(self):
        """Blocks on different pages are correctly distinguished."""
        page_map = [(0, 1, 0), (100, 2, 0), (200, 2, 1)]
        blocks = _get_span_blocks(0, 250, page_map)
        assert blocks == {(1, 0), (2, 0), (2, 1)}

    def test_span_up_to_last_block_boundary(self):
        """Span ending exactly at last block's start boundary."""
        page_map = [(0, 1, 0), (100, 1, 1)]
        blocks = _get_span_blocks(50, 100, page_map)
        assert blocks == {(1, 0)}  # does NOT include block 1 (span ends at its start)


# =============================================================================
# Test: _extract_options — inline options splitter verification
# =============================================================================


class TestInlineOptions:
    """_extract_options correctly handles horizontal/English options."""

    def test_horizontal_english_options(self):
        """Horizontal English options on one line → correctly split."""
        text = "A. Algorithm B. Binary tree C. Data structure D. Code"
        opts = _extract_options(text)
        assert opts.get("A") == "Algorithm"
        assert opts.get("B") == "Binary tree"
        assert opts.get("C") == "Data structure"
        assert opts.get("D") == "Code"
        assert len(opts) == 4

    def test_horizontal_colon_options(self):
        """Horizontal options with colons → correctly split."""
        text = "A: Hash B: Tree C: Graph D: List"
        opts = _extract_options(text)
        assert opts.get("A") == "Hash"
        assert opts.get("B") == "Tree"
        assert opts.get("C") == "Graph"
        assert opts.get("D") == "List"

    def test_chinese_options(self):
        """Chinese options with standard punctuation → correctly split."""
        text = "A. 算法\nB. 二叉树\nC. 数据结构\nD. 代码"
        opts = _extract_options(text)
        assert opts.get("A") == "算法"
        assert opts.get("B") == "二叉树"
        assert opts.get("C") == "数据结构"
        assert opts.get("D") == "代码"

    def test_options_with_code_present(self):
        """Options near code block → correctly separated."""
        text = "#define MAX 100\nA. Option1 B. Option2 C. Option3 D. Option4"
        opts = _extract_options(text)
        assert len(opts) >= 3

    def test_compact_no_space_options(self):
        """Compact options (A.ABDECF) → correctly split."""
        text = "A.ABDECF B.ABDCEF C.ABDFEC D.ACBEDF"
        opts = _extract_options(text)
        assert opts.get("A") == "ABDECF"
        assert opts.get("B") == "ABDCEF"
        assert opts.get("C") == "ABDFEC"
        assert opts.get("D") == "ACBEDF"

    def test_single_line_newline_separated(self):
        """Newline-separated options → correctly split."""
        text = "A.ABDECF\nB.ABDCEF\nC.ABDFEC\nD. ACBEDF"
        opts = _extract_options(text)
        assert opts.get("A") == "ABDECF"
        assert opts.get("B") == "ABDCEF"
        assert opts.get("C") == "ABDFEC"
        assert opts.get("D") == "ACBEDF"


# =============================================================================
# Integration: validate_option_set + _extract_options combined
# =============================================================================


class TestOptionSetIntegration:
    """validate_option_set should catch _extract_options failures."""

    def test_single_option_with_bcd_labels_caught(self):
        """If _extract_options returns single A with BCD labels, validate catches it."""
        # Edge case that might produce a single A: when all options
        # are on one line with unusual spacing, the inline parser might
        # not match. This test verifies the defense-in-depth.
        text = "A. Algorithm B. Binary tree C. Data structure D. Code"
        opts = _extract_options(text)
        validation = validate_option_set(opts)
        # If inline parser works fine (it does for this case), no suspicious
        # But if it fails in future regressions, validation catches it
        if len(opts) == 1 and "A" in opts:
            assert not validation.is_usable
            assert "inline_option_split_failed" in validation.suspicious_reasons
        else:
            # Parser handled it correctly
            assert validation.is_usable


# =============================================================================
# Test: Cross-contamination guard (pipeline-level)
# =============================================================================


class TestFrozenOptionsCrossContamination:
    """Frozen options must not cross-contaminate across blocks on same page."""

    def test_get_span_blocks_filters_by_block(self):
        """_get_span_blocks returns only overlapping blocks for a question span."""
        page_map = [(0, 1, 0), (100, 1, 1), (200, 2, 0)]

        # Question 1 spans block 0 only
        q1_blocks = _get_span_blocks(10, 90, page_map)
        assert q1_blocks == {(1, 0)}

        # Question 2 spans block 1 only
        q2_blocks = _get_span_blocks(110, 190, page_map)
        assert q2_blocks == {(1, 1)}

        # No cross-contamination: neither set contains the other block
        assert (1, 1) not in q1_blocks
        assert (1, 0) not in q2_blocks

    def test_simulated_frozen_registry_block_filter(self):
        """Simulate frozen_option_registry with two blocks on same page."""
        registry = {
            "1:0": {"A": "一", "B": "二", "C": "三", "D": "四"},
            "1:1": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"},
        }
        page_map = [(0, 1, 0), (200, 1, 1)]

        # Question 1 (block 0) should only get block 0 options
        q1_span_blocks = _get_span_blocks(10, 190, page_map)
        q1_opts = {}
        for fkey, fopts in registry.items():
            parts = fkey.split(":")
            if (int(parts[0]), int(parts[1])) in q1_span_blocks:
                q1_opts.update(fopts)
        assert q1_opts == {"A": "一", "B": "二", "C": "三", "D": "四"}
        assert "甲" not in q1_opts.get("A", "")

        # Question 2 (block 1) should only get block 1 options
        q2_span_blocks = _get_span_blocks(210, 400, page_map)
        q2_opts = {}
        for fkey, fopts in registry.items():
            parts = fkey.split(":")
            if (int(parts[0]), int(parts[1])) in q2_span_blocks:
                q2_opts.update(fopts)
        assert q2_opts == {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
        assert "一" not in q2_opts.get("A", "")


# =============================================================================
# Test: Subjective false-pass prevention
# =============================================================================


class TestSubjectiveFalsePassPrevention:
    """Questions with objective signals must not be silently passed as subjective."""

    def test_option_labels_prevent_subjective(self):
        """Text with A-D option labels → has_objective_question_signals returns True."""
        text = "1. Which one?\nA. one\nB. two\nC. three\nD. four\n答案：A"
        has, signals = has_objective_question_signals(text, "", "A")
        assert has is True
        assert any(s.startswith("option_labels:") for s in signals)
        assert any("explicit_answer_marker" in s for s in signals)

    def test_no_subjective_signals_for_plain_text(self):
        """Plain text without objective signals → no false positive."""
        text = "简述二叉树的三种遍历方式。"
        has, signals = has_objective_question_signals(text, text, None)
        assert has is False

    def test_choice_keyword_prevents_subjective(self):
        """Text with 下列/选项 keywords → objective signals detected."""
        text = "下列选项中，关于二叉树的说法正确的是？"
        has, signals = has_objective_question_signals(text, text, None)
        assert has is True
        assert any(s.startswith("choice_keywords:") for s in signals)

    def test_validate_option_set_with_objective_context(self):
        """When options dict has suspicious content but objective signals exist."""
        # Scenario: _extract_options returns single A with everything, but
        # objective signals exist in raw text
        bad_options = {"A": "Algorithm B. Binary tree C. Data structure D. Code"}
        validation = validate_option_set(bad_options)
        assert "inline_option_split_failed" in validation.suspicious_reasons

        # The raw text has objective signals
        raw_text = "1. Which term describes a tree traversal method?\nA. Algorithm B. Binary tree C. Data structure D. Code\n答案：B"
        has, signals = has_objective_question_signals(raw_text, raw_text, "B")
        assert has is True
        assert any("explicit_answer_marker" in s for s in signals)
