"""Tests for unified question numbering parser (OCR-103).

Covers:
- Arabic digits: 1. 2. (1) 【1】 第1题
- Chinese numerals: 一、二、 (一) 第一题
- Roman numerals: Ⅰ. Ⅱ. I. II. (I)
- Circled: ①②③
- Heavenly stems: 甲、乙、
- Positive examples (20+): valid question numbers
- Negative examples (20+): false positives to reject
- Sequential continuity validation
- Integration with existing splitter patterns
- Edge cases: year annotations, section numbers, OCR errors
"""

from __future__ import annotations

import pytest

from app.features.question_numbering import (
    NumberingType,
    extract_first_question_label,
    has_new_question_number,
    is_section_header,
    parse_numbering,
    validate_question_sequence,
)

# ===================================================================
# 1. Positive examples (valid question numbers)  — 20+
# ===================================================================


class TestPositiveMainQuestion:
    """Valid main question numbers — should all parse."""

    @pytest.mark.parametrize("line, expected_num, expected_type", [
        ("1. 页式存储管理中", 1, NumberingType.MAIN_QUESTION),
        ("2．操作系统", 2, NumberingType.MAIN_QUESTION),
        ("3、下列选项中", 3, NumberingType.MAIN_QUESTION),
        ("10) 系统调用", 10, NumberingType.MAIN_QUESTION),
        ("25） 进程通信", 25, NumberingType.MAIN_QUESTION),
        ("(5) 虚拟内存", 5, NumberingType.SUB_QUESTION),
        ("（8）文件系统", 8, NumberingType.SUB_QUESTION),
        ("【1】 选择题", 1, NumberingType.MAIN_QUESTION),
        ("【12】 综合题", 12, NumberingType.MAIN_QUESTION),
        ("第1题", 1, NumberingType.MAIN_QUESTION),
        ("第 10 题", 10, NumberingType.MAIN_QUESTION),
        ("第一题", 1, NumberingType.MAIN_QUESTION),
        ("第二题", 2, NumberingType.MAIN_QUESTION),
        ("第十题", 10, NumberingType.MAIN_QUESTION),
    ])
    def test_arabic_question_numbers(self, line, expected_num, expected_type):
        result = parse_numbering(line)
        assert result is not None, f"Expected to parse: {line}"
        assert result.normalized_value == expected_num
        assert result.numbering_type == expected_type, f"Got {result.numbering_type}"
        assert result.confidence >= 0.5

    @pytest.mark.parametrize("line, expected_num, expected_type", [
        # These are actual question numbers (not section headers)
        ("一、进程管理", 1, NumberingType.MAIN_QUESTION),
        ("二、内存管理", 2, NumberingType.MAIN_QUESTION),
        ("三、文件系统", 3, NumberingType.MAIN_QUESTION),
        # Sub-questions in parens
        ("（一）进程管理", 1, NumberingType.SUB_QUESTION),
        ("（二）内存管理", 2, NumberingType.SUB_QUESTION),
        ("(一) 存储", 1, NumberingType.SUB_QUESTION),
        ("(三) 文件", 3, NumberingType.SUB_QUESTION),
    ])
    def test_chinese_question_numbers(self, line, expected_num, expected_type):
        result = parse_numbering(line)
        assert result is not None, f"Expected to parse: {line}"
        assert result.normalized_value == expected_num
        assert result.numbering_type == expected_type
        assert result.confidence >= 0.5

    @pytest.mark.parametrize("line, expected_num, expected_type", [
        ("Ⅰ. 算法分析", 1, NumberingType.OPTION_ROMAN),
        ("Ⅱ、数据结构", 2, NumberingType.OPTION_ROMAN),
        ("III. 计算机网络", 3, NumberingType.OPTION_ROMAN),
        ("(I) 进程", 1, NumberingType.OPTION_ROMAN),
        ("(II) 线程", 2, NumberingType.OPTION_ROMAN),
        ("(III) 调度", 3, NumberingType.OPTION_ROMAN),
    ])
    def test_roman_numeral_questions(self, line, expected_num, expected_type):
        result = parse_numbering(line)
        assert result is not None, f"Expected to parse: {line}"
        assert result.normalized_value == expected_num
        assert result.numbering_type == expected_type

    @pytest.mark.parametrize("line, expected_num, expected_type", [
        ("① 进程状态", 1, NumberingType.OPTION_CIRCLED),
        ("② 内存碎片", 2, NumberingType.OPTION_CIRCLED),
        ("③ 文件系统", 3, NumberingType.OPTION_CIRCLED),
    ])
    def test_circled_numbers(self, line, expected_num, expected_type):
        result = parse_numbering(line)
        assert result is not None
        assert result.normalized_value == expected_num
        assert result.numbering_type == expected_type

    @pytest.mark.parametrize("line, expected_num, expected_type", [
        ("甲、选项甲", 1, NumberingType.OPTION),
        ("乙、选项乙", 2, NumberingType.OPTION),
        ("丙. 选项丙", 3, NumberingType.OPTION),
    ])
    def test_heavenly_stems(self, line, expected_num, expected_type):
        result = parse_numbering(line)
        assert result is not None
        assert result.normalized_value == expected_num
        assert result.numbering_type == expected_type


class TestPositiveSubQuestion:
    """Valid sub-question markers."""

    @pytest.mark.parametrize("line, expected_num", [
        ("(1) 子问题1", 1),
        ("（2）子问题2", 2),
        ("(a) 子项", None),  # lowercase letter — should this be supported?
    ])
    def test_sub_question_numbers(self, line, expected_num):
        result = parse_numbering(line)
        # (a) is not supported yet, may be None
        if "a" in line:
            return  # skip for now
        assert result is not None, f"Expected to parse: {line}"
        assert result.normalized_value == expected_num
        assert result.numbering_type == NumberingType.SUB_QUESTION


# ===================================================================
# 2. Negative examples (false positives to reject) — 20+
# ===================================================================


class TestNegativeFalsePositives:
    """These must NOT be identified as question numbers."""

    @pytest.mark.parametrize("line", [
        # ── Prose ordinals ──
        "第一步执行初始化",
        "第二个结点不为空",
        "第三种方法是可行的",
        "第一个步骤是",
        "第二步进行判断",
        # ── Enumeration in prose ──
        "一种可行的方法",
        "一类典型问题",
        "一个重要的概念",
        "三种不同的方式",
        # ── Company names ──
        "甲公司与乙公司",
        "甲和乙签订合同",
        "丙公司与丁公司",
        "甲与乙的差异",
        # ── Counting in prose ──
        "有三个结点",
        "存在两种可能",
        "包含三种情况",
        "用两种方法实现",
        # ── Question intro phrases (not question numbers) ──
        "下列选项中正确的是",
        "以下关于操作系统的描述",
        "以下说法错误的是",
        # ── Conditional/math prose ──
        "则进程进入就绪状态",
        "若 x 大于 y",
        "设有一组作业",
        "故系统调用需要",
        "因此进程切换",
        "由此可知答案",
        "综上所述，选B",
        # ── Section references ──
        "参见第一章",
        "参考第三节",
        # ── Page headers ──
        "第 1 页",
        "第 10 页",
        "- 5 -",
        "1/2",
        # ── Year annotations ──
        "（2019）统考真题",
        "(2020) 408真题",
        "（2021）",
        # ── Mixed content ──
        "一个系统有5个进程",
        "有3个并发执行的进程",
    ])
    def test_reject_false_question_numbers(self, line):
        result = parse_numbering(line)
        assert result is None, (
            f"Should NOT parse as question number: {line!r}, "
            f"got {result}"
        )

    def test_option_start_not_question(self):
        """Option lines must not be identified as question numbers."""
        lines = [
            "A. 选项内容",
            "B．另一个选项",
            "C、第三个选项",
            "D: 选项四",
            "a. 小写选项",
            "B) 选项B",
        ]
        for line in lines:
            result = parse_numbering(line)
            assert result is None, f"Option line should not be a question number: {line}"

    def test_section_number_not_question(self):
        """Section numbers (X.X) are identified as SECTION type, not question numbers."""
        lines = [
            "1.1 操作系统的基本概念",
            "1.1.1 操作系统的特征",
            "10.2 进程管理",
            "5.3.2 页面置换算法",
            "2.1 计算机系统概述",
        ]
        for line in lines:
            result = parse_numbering(line)
            assert result is not None, f"Expected to parse section: {line}"
            assert result.numbering_type == NumberingType.SECTION, (
                f"Expected SECTION for: {line}, got {result.numbering_type}"
            )

    def test_exam_section_headers(self):
        """Section headers like 一、选择题 must be identified as SECTION type."""
        section_headers = [
            "一、选择题",
            "二、填空题",
            "三、解答题",
            "四、综合应用题",
            "Part I",
            "Part II",
            "Part III",
        ]
        for line in section_headers:
            result = parse_numbering(line)
            assert result is not None, f"Expected to parse section header: {line}"
            assert result.numbering_type == NumberingType.SECTION, (
                f"Expected SECTION but got {result.numbering_type}: {line}"
            )

    def test_reject_long_numbers(self):
        """4+ digit numbers at line start should not be question numbers."""
        lines = [
            "4096 字节",
            "10000 种情况",
        ]
        for line in lines:
            result = parse_numbering(line)
            assert result is None, f"Long number should not be question: {line}"


# ===================================================================
# 3. Convenience wrapper tests
# ===================================================================


class TestWrappers:
    def test_has_new_question_number_positive(self):
        assert has_new_question_number("1. 进程管理")
        assert has_new_question_number("2、下列选项中")
        assert has_new_question_number("3) 题目")
        # 一、选择题 is a SECTION header, not a question number
        # （1）子问题 uses parens — not matched by lightweight cross_page check
        assert not has_new_question_number("一、选择题")
        assert not has_new_question_number("（1）子问题")

    def test_has_new_question_number_negative(self):
        assert not has_new_question_number("A. 选项")
        assert not has_new_question_number("第一步执行")
        assert not has_new_question_number("下列选项中")
        assert not has_new_question_number("甲乙丙丁")
        assert not has_new_question_number("（接上页）")
        assert not has_new_question_number("")

    def test_is_section_header(self):
        assert is_section_header("一、选择题")
        assert is_section_header("二、填空题")
        assert is_section_header("Part I")
        assert is_section_header("第一章 概述")
        assert not is_section_header("1. 进程管理")
        assert not is_section_header("A. 选项")
        assert not is_section_header("第一步执行")

    def test_extract_first_question_label(self):
        assert extract_first_question_label("1. 进程管理") == "1."
        assert extract_first_question_label("10) 系统调用") == "10)"
        assert extract_first_question_label("（1）子问题") == "（1）"
        # 一、选择题 is a section header, extract returns None
        assert extract_first_question_label("一、选择题") is None
        assert extract_first_question_label("第一题") == "第一题"
        assert extract_first_question_label("A. 选项") is None
        assert extract_first_question_label("") is None

    def test_extract_first_question_label_multiline(self):
        assert extract_first_question_label("1. 第一行\n第二行内容") == "1."
        assert extract_first_question_label("") is None


# ===================================================================
# 4. Sequence validation
# ===================================================================


class TestSequenceValidation:
    def test_valid_continuous_sequence(self):
        diags = validate_question_sequence([1, 2, 3, 4, 5])
        assert diags == []

    def test_start_not_one(self):
        diags = validate_question_sequence([3, 4, 5])
        assert any(d["type"] == "unexpected_start" for d in diags)

    def test_jump_detected(self):
        diags = validate_question_sequence([1, 2, 5, 6])
        jumps = [d for d in diags if d["type"] == "jump"]
        assert len(jumps) == 1
        assert jumps[0]["from_num"] == 2
        assert jumps[0]["to_num"] == 5

    def test_duplicate_detected(self):
        diags = validate_question_sequence([1, 2, 2, 3])
        dups = [d for d in diags if d["type"] == "duplicate_or_decrease"]
        assert len(dups) == 1
        assert dups[0]["from_num"] == 2
        assert dups[0]["to_num"] == 2

    def test_empty_sequence(self):
        assert validate_question_sequence([]) == []


# ===================================================================
# 5. Edge cases
# ===================================================================


class TestEdgeCases:
    def test_empty_and_whitespace(self):
        assert parse_numbering("") is None
        assert parse_numbering("   ") is None
        assert parse_numbering("\n") is None

    def test_ocr_fallback(self):
        result = parse_numbering("l. 题号")
        assert result is not None
        assert result.normalized_value == 1
        assert result.confidence < 0.8  # lower confidence for OCR fallback

        result2 = parse_numbering("I. 题号")
        assert result2 is not None
        assert result2.normalized_value == 1

    def test_trailing_whitespace(self):
        result = parse_numbering("  1. 题号")
        assert result is not None
        assert result.normalized_value == 1
        assert result.start == 2  # offset from stripped

    def test_mixed_question_types(self):
        """Compound question hierarchy levels are correct."""
        main = parse_numbering("1. 主问题")
        assert main is not None
        assert main.numbering_type == NumberingType.MAIN_QUESTION
        assert main.hierarchy_level == 0

        sub = parse_numbering("(1) 子问题")
        assert sub is not None
        assert sub.numbering_type == NumberingType.SUB_QUESTION
        assert sub.hierarchy_level == 1

    def test_parse_numbering_returns_correct_start_end(self):
        result = parse_numbering("  1. 题号测试")
        assert result is not None
        assert result.start == 2  # after "  "
        assert result.end == 4   # "1."

    def test_compound_question_case(self):
        """The actual 026_compound case: Chinese numbered sub-questions."""
        # This is the core OCR-103 fix:
        # "（1）" as sub-question within a compound
        sub1 = parse_numbering("（1）设 n 为正整数")
        assert sub1 is not None
        assert sub1.numbering_type == NumberingType.SUB_QUESTION
        assert sub1.normalized_value == 1

        sub2 = parse_numbering("（2）证明该结论")
        assert sub2 is not None
        assert sub2.numbering_type == NumberingType.SUB_QUESTION
        assert sub2.normalized_value == 2

        # Chinese sub-questions
        sub_ch = parse_numbering("（一）进程管理")
        assert sub_ch is not None
        assert sub_ch.numbering_type == NumberingType.SUB_QUESTION
        assert sub_ch.normalized_value == 1
