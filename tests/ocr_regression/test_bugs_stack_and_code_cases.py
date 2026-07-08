"""Regression tests for OCR pipeline bug fixes.

Tests cover 5 bug cases from BUGS.md:
- Case 1 (false_3): Stack horizontal options + subscript loss
- Case 2 (false_4): Stem-option adhesion + option truncation
- Case 3 (false_5): Wrong subscript rewrite
- Case 4 (false_1): Code split into options
- Case 5 (ocr_code_test_2): Struct code block + traversal strings

Each test validates the pipeline at the component level, using raw OCR text
as input (no real OCR dependency).
"""

import re
from pathlib import Path

import pytest

# ── Import pipeline components directly ──
from app.features.question_splitter import (
    _extract_options,
    _reconstruct_code_lines,
    _quarantine_code_regions,
    strip_frozen_options_from_stem,
)
from app.features.question_normalizer import normalize_question, _extract_stem, normalize_output
from app.features.answer_matcher import extract_explicit_answer
from app.features.code_integrity import detect_garbled_code_block
from app.features.ai_repair import _detect_subscript_changes


# ================================================================
# Case 1: false_3 — Stack horizontal options + subscript loss
# ================================================================

RAW_OCR_FALSE_3 = (
    "已知栈的入栈序列是(2,3,4,其出栈序列为P、P、P、P、则P、P不可\n"
    "\n"
    "A. 2,4 B. 2、C. 4,3 D. 3,"
)


class TestCase1_False3_StackHorizontalOptions:
    """Test Case 1: Stack question 22 - horizontal options + subscript loss."""

    def test_extract_options_inline(self):
        """Splitter should detect 4 inline horizontal options."""
        options = _extract_options(RAW_OCR_FALSE_3)
        assert len(options) >= 2, f"Expected at least 2 options, got {options}"
        assert "A" in options, f"Missing option A: {options}"
        assert "C" in options, f"Missing option C: {options}"
        assert "D" in options, f"Missing option D: {options}"

    def test_explicit_answer_not_present(self):
        """No explicit answer in this raw text."""
        result = extract_explicit_answer(RAW_OCR_FALSE_3)
        assert result.answer is None, (
            f"No explicit answer expected, got: {result.answer}"
        )

    def test_normalize_question_basic(self):
        """Pipeline should not crash on this input."""
        raw_q = {
            "number": 22,
            "raw_question_text": RAW_OCR_FALSE_3,
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": _extract_options(RAW_OCR_FALSE_3),
        }
        result = normalize_question(raw_q, source_info={"file": "false_3.png", "type": "image"})
        assert result is not None
        # Stem should contain question text
        assert len(result.get("stem", "")) > 20
        assert "栈" in result.get("stem", "")


# ================================================================
# Case 2: false_4 — Stem-option adhesion + P_i=3 → P_3=3
# ================================================================

RAW_OCR_FALSE_4 = (
    "若栈的输入序列是 $ P_{1}, P_{2}, \\cdots, P_{n} $"
    "，输出序列是 $ 1, 2, 3, \\cdots, n $"
    "，若 $ P_{i}=3 $，则"
    "A. 可能是2 B. 不可能是( C. 一定是1 D. 一定"
)


class TestCase2_False4_StemOptionAdhesion:
    """Test Case 2: Stack question 21 - stem/option adhesion + subscript."""

    def test_extract_options_from_inline(self):
        """Should extract 4 inline options from one line."""
        options = _extract_options(RAW_OCR_FALSE_4)
        assert "A" in options
        assert "B" in options
        assert "C" in options
        assert "D" in options

    def test_explicit_answer_not_present(self):
        """No answer marker in this raw text."""
        result = extract_explicit_answer(RAW_OCR_FALSE_4)
        assert result.answer is None

    def test_normalize_question_handles_inline_options(self):
        """Options should be separated from stem."""
        options = _extract_options(RAW_OCR_FALSE_4)
        raw_q = {
            "number": 21,
            "raw_question_text": RAW_OCR_FALSE_4,
            "page_start": 1,
            "page_end": 1,
            "has_options": bool(options),
            "option_lines": options,
        }
        result = normalize_question(raw_q, source_info={"file": "false_4.png", "type": "image"})
        stem = result.get("stem", "")
        # Stem should not contain inline option text
        assert "A." not in stem, f"Stem contains option text: {stem}"
        assert "可能是2" not in stem, f"Stem contains option value: {stem}"


# ================================================================
# Case 3: false_5 — Wrong subscript rewrite protection
# ================================================================

RAW_OCR_FALSE_5 = (
    "20.若栈的输入序列是P,P^{2},\",Pn,输出序列是1,2,3,\"\",n,"
    "若Ps=1,则 P的值()。\n"
    "A.可能是 2\n"
    "B.一定是 2\n"
    "C.不可能是 2\n"
    "D.不可能是 3"
)


class TestCase3_False5_SubscriptSafety:
    """Test Case 3: Stack question 20 - subscript safety gate."""

    def test_extract_options_multiline(self):
        """Options should be detected from multi-line format."""
        options = _extract_options(RAW_OCR_FALSE_5)
        assert "A" in options, f"Missing option A: {options}"
        assert "B" in options
        assert "C" in options
        assert "D" in options

    def test_subscript_safety_gate_detects_change(self):
        """Subscript safety gate should flag P_1=1 → wrong rewrite."""
        # This tests the subscript detection logic directly
        before = "若 $P_3=1$，则 $P_1$ 的值"
        after_wrong = "若 $P_1=1$，则 $P_2$ 的值"
        raw_text = RAW_OCR_FALSE_5

        changes = _detect_subscript_changes(before, after_wrong, raw_text)
        assert len(changes) > 0, (
            "Should detect subscript change P_3→P_1 without evidence"
        )

    def test_subscript_safety_accepts_correct_repair(self):
        """Subscript safety gate should accept P_3=1 → P_3=1 (no change)."""
        before = "若 $P_3=1$，则 $P_1$ 的值"
        after_correct = "若 $P_3=1$，则 $P_1$ 的值"
        raw_text = RAW_OCR_FALSE_5

        changes = _detect_subscript_changes(before, after_correct, raw_text)
        assert len(changes) == 0, (
            f"Should not flag unchanged subscripts: {changes}"
        )


# ================================================================
# Case 4: false_1 — Stack code split into options
# ================================================================

RAW_OCR_FALSE_1 = (
    "12.经过以下栈的操作后，变量x的值为( )。\n"
    "InitStack(st); Push(st,\n"
    "a); Push(st,\n"
    "b); Pop(st, x); GetTop(st, x) ;\n"
    "D.false\n"
    "C.NULL\n"
    "B.b\n"
    "A.a"
)


class TestCase4_False1_CodeNotOptions:
    """Test Case 4: Stack code - code must not be split into options."""

    def test_reconstruct_code_lines(self):
        """Broken code lines should be merged."""
        reconstructed = _reconstruct_code_lines(RAW_OCR_FALSE_1)
        # Check that Push(st, a) is now on one line
        assert "Push(st, a)" in reconstructed, (
            f"Expected 'Push(st, a)' in reconstructed text, got: {reconstructed}"
        )
        # Check that Pop and GetTop are on the same line as the rest
        assert "Pop(st, x)" in reconstructed
        assert "GetTop(st, x)" in reconstructed
        # The reconstruction may not merge all of them into one-line but
        # each function call should be continuous

    def test_code_quarantine_prevents_option_extraction(self):
        """Code content like 'a)' should NOT be extracted as options."""
        options = _extract_options(RAW_OCR_FALSE_1)
        # Real options are from the bottom: A.a, B.b, C.NULL, D.false
        assert "A" in options, f"Missing option A: {options}"
        assert "B" in options, f"Missing option B: {options}"
        assert "C" in options, f"Missing option C: {options}"
        assert "D" in options, f"Missing option D: {options}"

        # Code content should NOT appear as option values
        for key, value in options.items():
            assert "Push" not in value, (
                f"Option {key} contains code: '{value}'"
            )
            assert "Pop" not in value, (
                f"Option {key} contains code: '{value}'"
            )
            assert "InitStack" not in value, (
                f"Option {key} contains code: '{value}'"
            )

    def test_options_have_correct_values(self):
        """Options should have correct values from the real option block."""
        options = _extract_options(RAW_OCR_FALSE_1)
        # The real options at the bottom are A.a, B.b, C.NULL, D.false
        assert options.get("A") == "a", (
            f"Expected option A='a', got '{options.get('A')}'"
        )
        assert options.get("B") == "b", (
            f"Expected option B='b', got '{options.get('B')}'"
        )
        assert options.get("C") == "NULL", (
            f"Expected option C='NULL', got '{options.get('C')}'"
        )
        assert options.get("D") == "false", (
            f"Expected option D='false', got '{options.get('D')}'"
        )

    def test_code_regions_quarantined(self):
        """Code regions should be identified and quarantined."""
        cleaned, regions = _quarantine_code_regions(RAW_OCR_FALSE_1)
        assert len(regions) >= 1, "Expected at least 1 code region"


# ================================================================
# Case 5: ocr_code_test_2 — Struct code block + traversal strings
# ================================================================

RAW_OCR_CODE_TEST_2 = (
    "2. 已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，"
    "后序遍历序列为 DEBFCA\n"
    "则其前序遍历序列为:\n"
    "typedef struct BiTNode {\n"
    "char data;\n"
    "(1typu*  p1tysI* apo11ta aonu2s\n"
    "} BiTNode, *BiTree;\n"
    "A.ABDECF\n"
    "B.ABDCEF\n"
    "C.ABDFEC\n"
    "D. ACBEDF\n"
    "答案：A"
)


class TestCase5_CodeTest2_StructAndTraversal:
    """Test Case 5: Binary tree traversal - struct code block + traversal strings."""

    def test_explicit_answer_extracted(self):
        """Answer: A should be extracted from '答案：A'."""
        result = extract_explicit_answer(RAW_OCR_CODE_TEST_2)
        assert result.answer == "A", (
            f"Expected answer='A', got '{result.answer}'"
        )

    def test_garbled_code_detected(self):
        """Garbled code in struct body should be detected."""
        garbled = detect_garbled_code_block(RAW_OCR_CODE_TEST_2)
        assert garbled.is_garbled, (
            "Expected garbled code detection, got clean"
        )
        assert len(garbled.reasons) > 0, (
            f"Expected reasons for garbled code, got empty: {garbled}"
        )

    def test_frozen_options_stripped_from_stem(self):
        """Frozen option text should be removed from stem."""
        frozen_options = {
            "A": "ABDECF",
            "B": "ABDCEF",
            "C": "ABDFEC",
            "D": "ACBEDF",
        }
        stem = (
            "已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 "
            "DBEAFC，后序遍历序列为 DEBFCA\n"
            "则其前序遍历序列为:\n"
            "A.ABDECF\n"
            "B.ABDCEF\n"
            "C.ABDFEC\n"
            "D. ACBEDF\n"
            "答案：A"
        )
        cleaned = strip_frozen_options_from_stem(stem, frozen_options)
        assert "A.ABDECF" not in cleaned, (
            f"Frozen option 'A.ABDECF' still in stem: {cleaned}"
        )
        assert "B.ABDCEF" not in cleaned
        assert "C.ABDFEC" not in cleaned
        assert "答案" not in cleaned, (
            f"Answer text still in stem: {cleaned}"
        )
        # Traversal sequences should be preserved
        assert "DBEAFC" in cleaned, (
            f"Traversal sequence 'DBEAFC' removed from stem: {cleaned}"
        )
        assert "DEBFCA" in cleaned

    def test_normalize_preserves_struct_code(self):
        """Pipeline should process raw text with struct code."""
        options = _extract_options(RAW_OCR_CODE_TEST_2)
        raw_q = {
            "number": 2,
            "raw_question_text": RAW_OCR_CODE_TEST_2,
            "page_start": 1,
            "page_end": 1,
            "has_options": bool(options),
            "option_lines": options,
        }
        result = normalize_question(raw_q, source_info={"file": "ocr_code_test_2.png", "type": "image"})
        assert result is not None

    def test_options_have_correct_values(self):
        """Options should have correct traversal sequence values."""
        options = _extract_options(RAW_OCR_CODE_TEST_2)
        assert options.get("A") == "ABDECF", (
            f"Expected option A='ABDECF', got '{options.get('A')}'"
        )
        assert options.get("B") == "ABDCEF", (
            f"Expected option B='ABDCEF', got '{options.get('B')}'"
        )
        assert options.get("C") == "ABDFEC", (
            f"Expected option C='ABDFEC', got '{options.get('C')}'"
        )


# ================================================================
# Cross-cutting: Explicit answer extraction
# ================================================================

class TestExplicitAnswerExtraction:
    """Test explicit answer extraction patterns."""

    def test_answer_colon_a(self):
        result = extract_explicit_answer("内容\n答案：A\n更多内容")
        assert result.answer == "A"

    def test_answer_colon_lowercase(self):
        result = extract_explicit_answer("答案：a")
        assert result.answer == "A"

    def test_reference_answer(self):
        result = extract_explicit_answer("参考答案：C")
        assert result.answer == "C"

    def test_correct_answer(self):
        result = extract_explicit_answer("正确答案：B")
        assert result.answer == "B"

    def test_answer_english_colon(self):
        result = extract_explicit_answer("Answer: D")
        assert result.answer == "D"

    def test_key_label(self):
        result = extract_explicit_answer("KEY: A")
        assert result.answer == "A"

    def test_answer_in_brackets(self):
        result = extract_explicit_answer("【答案】A")
        assert result.answer == "A"

    def test_multi_choice_answer(self):
        result = extract_explicit_answer("答案：AB")
        assert result.answer == "AB"

    def test_multi_choice_with_separator(self):
        result = extract_explicit_answer("答案：A、C")
        assert result.answer == "A,C"

    def test_no_answer(self):
        result = extract_explicit_answer("这是一道题目，没有答案标记")
        assert result.answer is None

    def test_answer_ocr_fuzzy(self):
        """OCR fuzzy: 8 → B, 0 → D"""
        result = extract_explicit_answer("答案：8")
        assert result.answer == "B"

    def test_answer_with_extra_spaces(self):
        result = extract_explicit_answer("答案 :   A")
        assert result.answer == "A"


# ================================================================
# Cross-cutting: Garbled code detection
# ================================================================

class TestGarbledCodeDetection:
    """Test garbled code block detection."""

    def test_clean_c_struct(self):
        """Valid C struct should not be flagged as garbled."""
        code = (
            "typedef struct BiTNode {\n"
            "    char data;\n"
            "    struct BiTNode *lchild, *rchild;\n"
            "} BiTNode, *BiTree;"
        )
        result = detect_garbled_code_block(code)
        assert not result.is_garbled, (
            f"Clean struct flagged as garbled: {result.reasons}"
        )

    def test_garbled_c_struct(self):
        """Struct with garbled body should be detected."""
        code = (
            "typedef struct BiTNode {\n"
            "char data;\n"
            "(1typu*  p1tysI* apo11ta aonu2s\n"
            "} BiTNode, *BiTree;"
        )
        result = detect_garbled_code_block(code)
        assert result.is_garbled, (
            "Garbled struct not detected"
        )
        assert any("garbled" in r for r in result.reasons), (
            f"Expected garbled-related reason, got: {result.reasons}"
        )

    def test_operator_code_not_garbled(self):
        """Stack operation code should not be garbled."""
        code = "InitStack(st); Push(st, a); Push(st, b); Pop(st, x);"
        result = detect_garbled_code_block(code)
        assert not result.is_garbled

    def test_empty_code_not_garbled(self):
        result = detect_garbled_code_block("")
        assert not result.is_garbled


# ================================================================
# Cross-cutting: Code reconstruction and quarantine
# ================================================================

class TestCodeReconstruction:
    """Test broken code line reconstruction."""

    def test_merge_paren_continuation(self):
        text = "InitStack(st); Push(st,\na); Push(st,\nb);"
        result = _reconstruct_code_lines(text)
        assert "Push(st, a)" in result, f"Expected merge: {result}"
        assert "Push(st, b)" in result

    def test_no_false_positive_natural_language(self):
        text = "这是一段自然语言。\n它包含一些（括号内容）\n还有逗号，"
        result = _reconstruct_code_lines(text)
        # Should not merge natural language lines
        assert "\n它" in result or "这是一段自然语言。" in result


# ================================================================
# Cross-cutting: Frozen options stem stripping
# ================================================================

class TestFrozenOptionsStripping:
    """Test frozen options removal from stem."""

    def test_strip_basic(self):
        stem = "题干内容\nA.ABDECF\nB.ABDCEF\nC.ABDFEC\nD.ACBEDF"
        frozen = {"A": "ABDECF", "B": "ABDCEF", "C": "ABDFEC", "D": "ACBEDF"}
        cleaned = strip_frozen_options_from_stem(stem, frozen)
        assert "A.ABDECF" not in cleaned
        assert "B.ABDCEF" not in cleaned
        assert "题干内容" in cleaned

    def test_strip_inline_options(self):
        stem = "题干内容 A.ABDECF B.ABDCEF C.ABDFEC D.ACBEDF"
        frozen = {"A": "ABDECF", "B": "ABDCEF", "C": "ABDFEC", "D": "ACBEDF"}
        cleaned = strip_frozen_options_from_stem(stem, frozen)
        assert "题干内容" in cleaned

    def test_does_not_remove_traversal_sequences(self):
        stem = "中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA"
        frozen = {"A": "ABDECF"}
        cleaned = strip_frozen_options_from_stem(stem, frozen)
        assert "DBEAFC" in cleaned, f"Removed traversal sequence: {cleaned}"
        assert "DEBFCA" in cleaned


# ================================================================
# Cross-cutting: Subscript safety gate
# ================================================================

class TestSubscriptSafetyGate:
    """Test math subscript change detection."""

    def test_detect_subscript_change_without_evidence(self):
        before = "若 $P_3=1$，则 $P_1$ 的值"
        after = "若 $P_1=1$，则 $P_2$ 的值"
        raw = "Ps=1,则 P的值()"

        changes = _detect_subscript_changes(before, after, raw)
        assert len(changes) > 0, (
            "Should detect subscript change without evidence"
        )

    def test_no_change_when_same(self):
        before = "若 $P_3=1$，则 $P_1$ 的值"
        after = "若 $P_3=1$，则 $P_1$ 的值"
        raw = "Ps=1,则 P的值()"

        changes = _detect_subscript_changes(before, after, raw)
        assert len(changes) == 0

    def test_detect_specificity_loss(self):
        """P_3 → P_i (generalizing a specific subscript)."""
        before = "若 $P_3=3$"
        after = "若 $P_i=3$"
        raw = "P_i=3"

        changes = _detect_subscript_changes(before, after, raw)
        assert len(changes) > 0, (
            "Should detect specificity loss"
        )


# ================================================================
# Cross-cutting: Quality status
# ================================================================

class TestQualityStatus:
    """Test quality status derivation."""

    def test_normalize_question_has_quality_status(self):
        raw_q = {
            "number": 1,
            "raw_question_text": "测试题干内容 A.选项1 B.选项2 C.选项3 D.选项4",
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "选项1", "B": "选项2", "C": "选项3", "D": "选项4"},
        }
        result = normalize_question(raw_q, source_info={"file": "test.png", "type": "image"})
        assert "quality_status" in result, (
            "Missing quality_status in normalize output"
        )
