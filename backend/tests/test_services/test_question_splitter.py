"""QuestionSplitter 单元测试。"""
import os
import pytest
from app.features.question_splitter import (
    split_questions,
    _detect_question_number,
    _detect_option_line,
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def _read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def _make_blocks(text: str, page: int = 1, block_index: int = 0) -> list[dict]:
    return [{"page": page, "block_index": block_index, "normalized_text": text}]


# ---------------------------------------------------------------
# 1. 标准 INLINE 文档
# ---------------------------------------------------------------

class TestInlineDocument:
    def test_split_five_questions(self):
        text = _read_fixture("splitter_inline.txt")
        result = split_questions(_make_blocks(text))
        assert len(result) == 5
        assert result[0]["number"] == 1
        assert result[4]["number"] == 5

    def test_questions_have_options(self):
        text = _read_fixture("splitter_inline.txt")
        result = split_questions(_make_blocks(text))
        for q in result:
            assert q["has_options"] is True
            assert len(q["option_lines"]) >= 3

    def test_option_keys_uppercase(self):
        text = _read_fixture("splitter_inline.txt")
        result = split_questions(_make_blocks(text))
        for q in result:
            for key in q["option_lines"]:
                assert key in ("A", "B", "C", "D")
                assert key == key.upper()


# ---------------------------------------------------------------
# 2. 单一题号格式
# ---------------------------------------------------------------

class TestSingleFormat:
    def test_dot_format(self):
        blocks = _make_blocks("1. 题目一\n2. 题目二\n3. 题目三")
        result = split_questions(blocks)
        assert len(result) == 3
        assert [q["number"] for q in result] == [1, 2, 3]

    def test_chinese_number(self):
        blocks = _make_blocks("第一题 题目一\n第二题 题目二\n第三题 题目三")
        result = split_questions(blocks)
        assert len(result) == 3
        assert [q["number"] for q in result] == [1, 2, 3]


# ---------------------------------------------------------------
# 3. 题号格式检测（单元函数）
# ---------------------------------------------------------------

class TestQuestionNumberDetection:
    def test_dot(self):
        r = _detect_question_number("1. 题目")
        assert r == (1, 2)

    def test_comma(self):
        r = _detect_question_number("1、题目")
        assert r == (1, 2)

    def test_paren(self):
        r = _detect_question_number("(1) 题目")
        assert r == (1, 3)

    def test_bracket(self):
        r = _detect_question_number("【1】题目")
        assert r == (1, 3)

    def test_di_prefix(self):
        r = _detect_question_number("第1题 题目")
        assert r == (1, 3)

    def test_chinese_prefix(self):
        r = _detect_question_number("第一题 题目")
        assert r == (1, 3)

    def test_ocr_l_to_1(self):
        r = _detect_question_number("l. 题目")
        assert r == (1, 2)

    def test_ocr_I_to_1(self):
        r = _detect_question_number("I. 题目")
        assert r == (1, 2)

    def test_no_question_number(self):
        assert _detect_question_number("普通文本") is None
        assert _detect_question_number("A. 选项") is None


# ---------------------------------------------------------------
# 4. 选项检测（单元函数）
# ---------------------------------------------------------------

class TestOptionLineDetection:
    def test_dot_option(self):
        r = _detect_option_line("A. 选项内容")
        assert r == ("A", "选项内容")

    def test_colon_option(self):
        r = _detect_option_line("B: 选项内容")
        assert r == ("B", "选项内容")

    def test_paren_option(self):
        r = _detect_option_line("C）选项内容")
        assert r == ("C", "选项内容")

    def test_lowercase_option(self):
        r = _detect_option_line("d. 选项内容")
        assert r == ("D", "选项内容")

    def test_ocr_8_to_B(self):
        r = _detect_option_line("8. 选项内容")
        assert r == ("B", "选项内容")

    def test_ocr_0_to_D(self):
        r = _detect_option_line("0. 选项内容")
        assert r == ("D", "选项内容")

    def test_not_option(self):
        assert _detect_option_line("普通文本") is None
        assert _detect_option_line("1. 题号不是选项") is None


# ---------------------------------------------------------------
# 5. 多题号格式混用
# ---------------------------------------------------------------

class TestMixedFormats:
    def test_mixed_in_document(self):
        blocks = _make_blocks(
            "1. 题目一\n"
            "2、题目二\n"
            "(3) 题目三\n"
            "【4】题目四\n"
            "第五题 题目五"
        )
        result = split_questions(blocks)
        assert len(result) == 5
        assert [q["number"] for q in result] == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------
# 6. 跨页/跨块题目
# ---------------------------------------------------------------

class TestCrossPage:
    def test_cross_page_text(self):
        text = _read_fixture("splitter_cross_page.txt")
        # 模拟跨页：每个 block 来自不同页面
        lines = text.strip().split("\n\n")
        blocks = [
            {"page": 1, "block_index": 0, "normalized_text": lines[0]},
            {"page": 2, "block_index": 1, "normalized_text": lines[1]},
            {"page": 3, "block_index": 2, "normalized_text": lines[2]},
        ]
        result = split_questions(blocks)
        assert len(result) == 3

    def test_cross_block_continuation(self):
        """跨 block 的连续题目（续文不应成为新题目）。"""
        blocks = [
            {"page": 1, "block_index": 0, "normalized_text": "1. 设函数 f(x) 在区间"},
            {"page": 1, "block_index": 1, "normalized_text": "[0, 1] 上连续，证明：存在 ξ ∈ (0, 1)"},
            {"page": 1, "block_index": 2, "normalized_text": "2. 下一题"},
        ]
        result = split_questions(blocks)
        assert len(result) == 2
        assert "f(x)" in result[0]["raw_question_text"]
        assert "[0, 1]" in result[0]["raw_question_text"]

    def test_page_end_tracking(self):
        """跨页题目应标记最大页码。"""
        blocks = [
            {"page": 1, "block_index": 0, "normalized_text": "1. 题目开始"},
            {"page": 2, "block_index": 1, "normalized_text": "题目继续"},
        ]
        result = split_questions(blocks)
        assert result[0]["page_start"] == 1
        assert result[0]["page_end"] == 2


# ---------------------------------------------------------------
# 7. OCR 错误容错
# ---------------------------------------------------------------

class TestOcrTolerance:
    def test_ocr_question_number(self):
        text = _read_fixture("splitter_ocr_noise.txt")
        result = split_questions(_make_blocks(text))
        # 应能切分出 3 道题（"l.", "2.O", "3.I" 都是题号）
        assert len(result) == 3

    def test_ocr_options_detected(self):
        text = _read_fixture("splitter_ocr_noise.txt")
        result = split_questions(_make_blocks(text))
        for q in result:
            assert q["has_options"]
            assert len(q["option_lines"]) >= 2


    def test_inline_next_question_after_option(self):
        blocks = _make_blocks(
            "29. 以下关于管程的叙述中，错误的是（ ）。\n"
            "A. 同步工具\n"
            "B. 每次只允许一个进程进入\n"
            "C. signal 操作作用相同\n"
            "D. 无法创建和撤销 30. 对信号量 S 执行 P 操作后，使该进程进入资源等待队列的条件是（ ）。\n"
            "A. S.value < 0\n"
            "B. S.value <= 0\n"
            "C. S.value > 0\n"
            "D. S.value >= 0"
        )
        result = split_questions(blocks)
        assert len(result) == 2
        assert [q["number"] for q in result] == [29, 30]
        assert "30." not in result[0]["option_lines"]["D"]

    def test_inline_options_are_extracted(self):
        blocks = _make_blocks("1. 题干\nA. 1 B. 2 C. 3 D. 4")
        result = split_questions(blocks)
        assert result[0]["option_lines"] == {"A": "1", "B": "2", "C": "3", "D": "4"}

    def test_sub_questions_are_not_split_as_questions(self):
        blocks = _make_blocks(
            "1. 有一个计数信号量 S：\n"
            "1）假如若干进程对 S 进行 28 次 P 操作和 18 次 V 操作后，信号量 S 的值为 0。\n"
            "2）假如若干进程对信号量 S 进行了 15 次 P 操作和 2 次 V 操作。请问此时有多少个进程等待？\n"
            "A. 2\nB. 3\nC. 5\nD. 7"
        )
        result = split_questions(blocks)
        assert len(result) == 1

    def test_sub_questions_after_semicolon_are_not_split(self):
        blocks = _make_blocks(
            "1. 有一个计数信号量 S，若干进程对 S 执行 P、V 操作；\n"
            "1）假如若干进程对 S 进行 28 次 P 操作和 18 次 V 操作后，信号量 S 的值为 0。\n"
            "2）假如若干进程对信号量 S 进行了 15 次 P 操作和 2 次 V 操作。请问此时有多少个进程等待？\n"
            "A. 2\nB. 3\nC. 5\nD. 7"
        )
        result = split_questions(blocks)
        assert len(result) == 1
        assert "1）假如" in result[0]["raw_question_text"]
        assert "2）假如" in result[0]["raw_question_text"]
        assert result[0]["has_options"] is True

    def test_option_continuation_line_appended(self):
        blocks = _make_blocks(
            "1. 下列说法正确的是（ ）。\n"
            "A. 第一项很长\n"
            "需要换行继续说明\n"
            "B. 第二项\n"
            "C. 第三项\n"
            "D. 第四项"
        )
        result = split_questions(blocks)
        assert result[0]["option_lines"]["A"] == "第一项很长 需要换行继续说明"

    def test_inline_option_truncates_answer_and_explanation_tail(self):
        blocks = _make_blocks("1. 题干\nA. 1 B. 2 C. 3 D. 4 答案：A 解析：因为如此")
        result = split_questions(blocks)
        assert result[0]["option_lines"]["D"] == "4"

    def test_single_option_truncates_answer_tail(self):
        blocks = _make_blocks("1. 题干\nD. 4 正确答案：A")
        result = split_questions(blocks)
        assert result[0]["option_lines"]["D"] == "4"


# ---------------------------------------------------------------
# 8. 空输入 / 边界情况
# ---------------------------------------------------------------

class TestEdgeCases:
    def test_empty_list(self):
        assert split_questions([]) == []

    def test_empty_text(self):
        blocks = _make_blocks("")
        assert split_questions(blocks) == []

    def test_no_question_numbers(self):
        blocks = _make_blocks("这是普通文本\n没有题号\n只有段落")
        assert split_questions(blocks) == []


# ---------------------------------------------------------------
# 9. 单题文档
# ---------------------------------------------------------------

class TestSingleQuestion:
    def test_single_question_fixture(self):
        text = _read_fixture("splitter_single.txt")
        result = split_questions(_make_blocks(text))
        assert len(result) == 1
        assert result[0]["number"] == 1
        assert result[0]["has_options"]
        assert "A" in result[0]["option_lines"]
        assert "D" in result[0]["option_lines"]


# ---------------------------------------------------------------
# 10. structure 参数可选
# ---------------------------------------------------------------

class TestStructureParam:
    def test_structure_optional(self):
        blocks = _make_blocks("1. 题目A\n2. 题目B")
        r1 = split_questions(blocks)
        r2 = split_questions(blocks, {"mode": "INLINE"})
        assert len(r1) == len(r2)

    def test_confidence_range(self):
        blocks = _make_blocks("1. 题目\nA. 选A\nB. 选B")
        result = split_questions(blocks)
        for q in result:
            assert 0.0 <= q["confidence"] <= 1.0


# ---------------------------------------------------------------
# 11. 无选项题目（填空/简答）
# ---------------------------------------------------------------

class TestNoOptions:
    def test_fill_blank_no_options(self):
        blocks = _make_blocks("1. 计算极限：lim(x→0) sin(x)/x = ______")
        result = split_questions(blocks)
        assert len(result) == 1
        assert result[0]["has_options"] is False
        assert result[0]["option_lines"] == {}

    def test_multiple_no_option_questions(self):
        blocks = _make_blocks(
            "1. 求导数 f'(x)。\n"
            "2. 计算积分值。\n"
            "3. 证明不等式。"
        )
        result = split_questions(blocks)
        assert len(result) == 3
        for q in result:
            assert q["has_options"] is False
