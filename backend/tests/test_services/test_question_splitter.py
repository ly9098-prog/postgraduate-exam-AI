"""QuestionSplitter 单元测试。"""
import os
import pytest
from app.features.question_splitter import (
    split_questions,
    _detect_question_number,
    _detect_option_line,
)
from app.features.question_normalizer import normalize_question


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

    def test_ocr_circled_prefix_option(self):
        r = _detect_option_line("① A. n + 1")
        assert r == ("A", "n + 1")

    def test_ocr_circled_prefix_option_without_space(self):
        r = _detect_option_line("②B. 2n")
        assert r == ("B", "2n")

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

    def test_orphan_options_recovery(self):
        """跨页选项恢复：题目在第1页有A、B，第2页开头有C、D。"""
        blocks = [
            {"page": 1, "block_index": 0, "normalized_text": "1. 以下关于死锁的说法正确的是\nA. 死锁是永久性阻塞\nB. 死锁只发生在两个进程间"},
            {"page": 2, "block_index": 1, "normalized_text": "C. 死锁可以被预防\nD. 死锁不可能被检测\n2. 下一题题干"},
        ]
        result = split_questions(blocks)
        assert len(result) == 2
        # Question 1 should have all 4 options merged
        assert "A" in result[0]["option_lines"]
        assert "B" in result[0]["option_lines"]
        assert "C" in result[0]["option_lines"]
        assert "D" in result[0]["option_lines"]
        # Question 2 should not contain option C/D
        assert "C" not in result[1]["option_lines"]
        assert "D" not in result[1]["option_lines"]

    def test_no_false_merge_when_complete(self):
        """完整选项不应触发合并。"""
        blocks = [
            {"page": 1, "block_index": 0, "normalized_text": "1. 题目\nA. 选项A\nB. 选项B\nC. 选项C\nD. 选项D"},
            {"page": 2, "block_index": 1, "normalized_text": "2. 下一题\nA. 选项A\nB. 选项B\nC. 选项C\nD. 选项D"},
        ]
        result = split_questions(blocks)
        assert len(result) == 2
        assert len(result[0]["option_lines"]) == 4
        assert len(result[1]["option_lines"]) == 4


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

    def test_ocr_question_prefix_options_detected(self):
        blocks = _make_blocks("1. 题目\n? A. 选项一\n？B. 选项二\n① C. 选项三\n② D. 选项四")
        result = split_questions(blocks)
        assert result[0]["option_lines"] == {
            "A": "选项一",
            "B": "选项二",
            "C": "选项三",
            "D": "选项四",
        }

    def test_ocr_question_prefix_options_removed_from_stem(self):
        blocks = _make_blocks("1. 题目\n? A. 选项一\n？B. 选项二\n① C）选项三\n② D 选项四")
        raw_question = split_questions(blocks)[0]
        normalized = normalize_question(raw_question)
        assert normalized["stem"] == "题目"


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

    def test_inline_ocr_prefix_options_are_extracted(self):
        blocks = _make_blocks("1. 题干\n? A. 1 ？B. 2 ① C. 3 ② D. 4")
        result = split_questions(blocks)
        assert result[0]["option_lines"] == {"A": "1", "B": "2", "C": "3", "D": "4"}

    def test_inline_circled_options_are_extracted(self):
        blocks = _make_blocks("31. 已知数列满足条件，求最大值 ① A. n + 1 ② B. 2n ③ C. n - 1 ④ D. 2n - 1")
        result = split_questions(blocks)
        assert result[0]["option_lines"] == {
            "A": "n + 1",
            "B": "2n",
            "C": "n - 1",
            "D": "2n - 1",
        }

    def test_collapsed_ocr_sample_splits_questions_and_options(self):
        blocks = _make_blocks(
            "31. 已知数列满足条件，求最大值 ① A. n + 1 ② B. 2n ③ C. n - 1 ④ D. 2n - 1 "
            "32. 若信号量初值为 10，问等待进程数（ ）。 A. 2 B. 3 C. 5 D. 7"
        )
        result = split_questions(blocks)
        assert [q["number"] for q in result] == [31, 32]
        assert result[0]["option_lines"] == {
            "A": "n + 1",
            "B": "2n",
            "C": "n - 1",
            "D": "2n - 1",
        }
        assert result[1]["option_lines"] == {"A": "2", "B": "3", "C": "5", "D": "7"}

    def test_inline_option_sequence_does_not_split_plain_variables(self):
        blocks = _make_blocks("1. 设集合 A 与集合 B 满足 A∩B=C，求 D 的取值。")
        result = split_questions(blocks)
        assert result[0]["option_lines"] == {}

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

    def test_question_stem_ending_with_paren_is_not_truncated(self):
        blocks = _make_blocks(
            "1. 若系统有 n 个进程，则就绪队列中进程的个数最多有（?）个；阻塞队列中进程的个数最多有（?）个。\n"
            "? A. n + 1\n"
            "? B. n\n"
            "? C. n - 1\n"
            "? D. 1"
        )
        result = split_questions(blocks)
        assert len(result) == 1
        assert "就绪队列" in result[0]["raw_question_text"]
        assert "阻塞队列" in result[0]["raw_question_text"]
        assert "? A. n + 1" in result[0]["raw_question_text"]

    def test_paren_question_number_requires_question_text_marker(self):
        assert _detect_question_number("1)假如若干进程对 S 进行 P 操作") is None
        assert _detect_question_number("2）假如若干进程对 S 进行 V 操作") is None
        assert _detect_question_number("32) 第32题内容") == (32, 3)
        assert _detect_question_number("32）下列说法正确的是") == (32, 3)

    def test_multi_digit_paren_question_number_splits(self):
        blocks = _make_blocks(
            "31. 上一道题\n"
            "A. 选项A\n"
            "32）下列说法正确的是（ ）。\n"
            "A. 选项一\nB. 选项二"
        )
        result = split_questions(blocks)
        assert len(result) == 2
        assert [q["number"] for q in result] == [31, 32]
        assert "32）" not in result[0]["raw_question_text"]

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

    def test_grouped_circled_option_rows_preserve_placeholders(self):
        blocks = _make_blocks(
            "1. 若系统有 n 个进程，则就绪队列中进程的个数最多有（①）个；阻塞队列中进程的个数最多有（②）个。\n"
            "① A. n+1  B. n  C. n−1  D. 1\n"
            "② A. n+1  B. n  C. n−1  D. 1"
        )
        result = split_questions(blocks)
        assert len(result) == 1
        raw_text = result[0]["raw_question_text"]
        assert "（①）" in raw_text
        assert "（②）" in raw_text
        assert "（）" not in raw_text
        assert "① A. n+1" in raw_text
        assert "② A. n+1" in raw_text
        assert result[0]["option_lines"] == {"A": "n+1", "B": "n", "C": "n−1", "D": "1"}

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


# ---------------------------------------------------------------
# 12. Section Type 注解
# ---------------------------------------------------------------

class TestSectionTypeAnnotation:
    def test_section_type_from_single_marker(self):
        """题目页位于 question_type_single marker 之后，应标注 section_type。"""
        blocks = _make_blocks(
            "1. 下列说法正确的是（ ）。\nA. x\nB. y\nC. z\nD. w\n"
            "2. 以下哪个不属于（ ）。\nA. a\nB. b\nC. c\nD. d",
            page=3,
        )
        structure = {
            "mode": "SEPARATED",
            "question_pages": [3],
            "answer_pages": [],
            "content_pages": [],
            "section_markers": [
                {"page": 2, "block_index": 0, "marker_type": "exercise_start", "text": "习题精选"},
                {"page": 2, "block_index": 1, "marker_type": "question_type_single", "text": "单项选择题"},
            ],
        }
        result = split_questions(blocks, structure)
        assert len(result) == 2
        for q in result:
            assert q["section_type"] == "question_type_single"

    def test_section_type_multiple_markers(self):
        """多个 type marker 按页匹配：后出现的 marker 覆盖前面的。"""
        blocks = [
            {"page": 3, "block_index": 0, "normalized_text": "1. 下列正确的是（ ）。\nA. x\nB. y\nC. z\nD. w"},
            {"page": 5, "block_index": 1, "normalized_text": "2. 以下属于（ ）。\nA. a\nB. b\nC. c\nD. d"},
        ]
        structure = {
            "mode": "SEPARATED",
            "question_pages": [3, 5],
            "answer_pages": [],
            "content_pages": [],
            "section_markers": [
                {"page": 2, "block_index": 0, "marker_type": "exercise_start", "text": "习题精选"},
                {"page": 2, "block_index": 1, "marker_type": "question_type_single", "text": "单项选择题"},
                {"page": 4, "block_index": 2, "marker_type": "question_type_multiple", "text": "多项选择题"},
            ],
        }
        result = split_questions(blocks, structure)
        assert result[0]["section_type"] == "question_type_single"
        assert result[1]["section_type"] == "question_type_multiple"

    def test_section_type_none_without_markers(self):
        """无 section markers 时 section_type 为 None。"""
        blocks = _make_blocks("1. 下列正确的是（ ）。\nA. x\nB. y\nC. z\nD. w")
        result = split_questions(blocks)
        assert result[0]["section_type"] is None

    def test_section_type_none_before_any_marker(self):
        """题目在所有 type marker 之前时 section_type 为 None。"""
        blocks = _make_blocks("1. 下列正确的是（ ）。\nA. x\nB. y\nC. z\nD. w", page=1)
        structure = {
            "mode": "SEPARATED",
            "question_pages": [1, 5],
            "answer_pages": [],
            "content_pages": [],
            "section_markers": [
                {"page": 1, "block_index": 0, "marker_type": "exercise_start", "text": "习题精选"},
                {"page": 5, "block_index": 1, "marker_type": "question_type_single", "text": "单项选择题"},
            ],
        }
        result = split_questions(blocks, structure)
        assert result[0]["section_type"] is None


# ---------------------------------------------------------------
# P1-1: book 模式下"软 prose"风险标
# ---------------------------------------------------------------

class TestBookSoftProseRiskFlag:
    """split_questions(import_mode="book") 给"疑似教材正文"打
    risk_flags=["book_pdf_prose_like"]，比 pipeline 的硬过滤宽松：
    保留进审核队列，让人工最终裁决。值域见
    prompts/tasks/ocr_book_pdf_non_question_filter_plan.md §11.3。"""

    def test_book_mode_flags_prose_like_question_without_options(self):
        # 60+ 字符 + prose marker + 无选项 + 无题问信号 → 命中 soft prose
        text = (
            "1. 定义：线性表是具有相同数据类型的 n 个数据元素的有限序列，"
            "顺序存储和链式存储是其常见实现方式，本节介绍前者和后者。"
        )
        result = split_questions(_make_blocks(text), import_mode="book")

        assert len(result) == 1
        assert "book_pdf_prose_like" in (result[0].get("risk_flags") or [])
        assert result[0]["confidence"] == 0.4

    def test_book_mode_does_not_flag_choice_question(self):
        text = "\n".join([
            "1. 下列说法中正确的是？",
            "A. 选项一",
            "B. 选项二",
            "C. 选项三",
            "D. 选项四",
        ])
        result = split_questions(_make_blocks(text), import_mode="book")

        assert len(result) == 1
        assert "book_pdf_prose_like" not in (result[0].get("risk_flags") or [])

    def test_book_mode_does_not_flag_subjective_with_question_signal(self):
        # 含"试述/为什么/简述"题问信号 → 不打 flag，即使含 prose marker
        text = (
            "1. 简述线性表顺序存储与链式存储在插入删除效率上的差异，"
            "并说明各自的适用场景。需要包含定义和性质分析。"
        )
        result = split_questions(_make_blocks(text), import_mode="book")

        assert len(result) == 1
        assert "book_pdf_prose_like" not in (result[0].get("risk_flags") or [])

    def test_short_prose_below_threshold_not_flagged(self):
        text = "1. 定义：线性表。"  # < 60 字符
        result = split_questions(_make_blocks(text), import_mode="book")

        if result:  # 可能因长度过短被切分逻辑过滤
            assert "book_pdf_prose_like" not in (result[0].get("risk_flags") or [])

    def test_exam_mode_does_not_flag_prose(self):
        """exam / image / None 模式不应触发软 prose 标，避免污染其它链路。"""
        text = (
            "1. 定义：线性表是具有相同数据类型的 n 个数据元素的有限序列，"
            "顺序存储和链式存储是其常见实现方式，本节介绍前者。"
        )
        for mode in (None, "exam", "image", "txt"):
            result = split_questions(_make_blocks(text), import_mode=mode)
            assert len(result) == 1, f"mode={mode} 没切出题目"
            assert "book_pdf_prose_like" not in (
                result[0].get("risk_flags") or []
            ), f"mode={mode} 不应触发软 prose 标"

    def test_book_mode_no_marker_no_flag(self):
        # 长但无 prose marker → 不标
        text = "1. 计算 1+1 等于多少？" + "A" * 80
        result = split_questions(_make_blocks(text), import_mode="book")

        assert len(result) == 1
        assert "book_pdf_prose_like" not in (result[0].get("risk_flags") or [])

    def test_book_mode_preserves_existing_risk_flags(self):
        """未来若 splitter 自身或外部传入已有 risk_flags，软 prose 标应合并去重。"""
        text = (
            "1. 性质：顺序存储结构可以实现随机存取。本章讨论数据结构的基本特征。"
            "知识点 1、知识点 2 分别说明逻辑结构与存储结构的关系。"
        )
        result = split_questions(_make_blocks(text), import_mode="book")

        assert len(result) == 1
        flags = result[0].get("risk_flags") or []
        # 至少 book_pdf_prose_like，且不重复
        assert flags.count("book_pdf_prose_like") == 1


# ---------------------------------------------------------------
# Wangdao 408 pages 245-280 P0: TCP prose vs. MCQ golden cases
# ---------------------------------------------------------------

class TestWangdao408TcpP0Golden:
    def test_book_content_skips_tcp_prose_heading_with_fullwidth_dot(self):
        text = "\n".join([
            "2．快重传和快恢复",
            "采用快重传算法可以让发送方尽早知道个别报文段的丢失。",
            "TCP 拥塞控制中的窗口机制会根据网络状态调整发送速率。",
            "因此可得，快恢复过程属于教材正文解释而不是待解题目。",
        ])
        structure = {"mode": "SEPARATED", "content_pages": [245], "question_pages": [], "answer_pages": []}

        result = split_questions(_make_blocks(text, page=245), structure=structure, import_mode="book")

        assert result == []

    def test_tcp_choice_questions_survive_book_content_context(self):
        text = "\n".join([
            "01. 下列关于 TCP 协议的说法，正确的是",
            "A. TCP 提供可靠传输服务",
            "B. TCP 不使用确认机制",
            "C. TCP 的拥塞窗口固定不变",
            "D. TCP 报文段不包含序号字段",
            "02. TCP 拥塞控制中，下列关于窗口的说法正确的是",
            "A. 拥塞窗口用于限制发送方注入网络的数据量",
            "B. 慢开始阶段拥塞窗口一定不变",
            "C. 快重传会关闭所有连接",
            "D. 快恢复与协议可靠性无关",
        ])
        structure = {"mode": "SEPARATED", "content_pages": [246], "question_pages": [246], "answer_pages": []}

        result = split_questions(_make_blocks(text, page=246), structure=structure, import_mode="book")

        assert [q["number"] for q in result] == [1, 2]
        assert all(q["has_options"] for q in result)
        assert all(set(q["option_lines"]) == {"A", "B", "C", "D"} for q in result)
        assert all("book_pdf_prose_like" not in (q.get("risk_flags") or []) for q in result)

    def test_postgraduate_exam_choice_questions_43_to_45_survive_domain_terms(self):
        text = "\n".join([
            "43. 【2009 统考真题】下列关于 TCP 拥塞窗口的说法，正确的是",
            "A. 拥塞窗口反映网络拥塞程度",
            "B. 报文段序号字段只在 UDP 协议中出现",
            "C. 快重传算法不需要重复确认",
            "D. 快恢复过程一定使窗口变为 0",
            "44. 【2010 统考真题】以下关于 TCP 协议机制的说法，正确的是",
            "A. TCP 可以通过确认和重传提高可靠性",
            "B. TCP 没有流量控制过程",
            "C. 窗口字段与接收能力无关",
            "D. 拥塞控制不影响发送速率",
            "45. 【2011 统考真题】下列关于快重传和快恢复的说法，错误的是",
            "A. 快重传依赖重复确认信号",
            "B. 快恢复属于 TCP 拥塞控制机制",
            "C. 协议中的窗口变化可能影响吞吐量",
            "D. 发生丢失时一定不需要重传报文段",
        ])
        structure = {"mode": "SEPARATED", "content_pages": [247], "question_pages": [247], "answer_pages": []}

        result = split_questions(_make_blocks(text, page=247), structure=structure, import_mode="book")

        assert [q["number"] for q in result] == [43, 44, 45]
        assert all(set(q["option_lines"]) == {"A", "B", "C", "D"} for q in result)

    def test_content_page_prose_filter_does_not_affect_exam_or_image_modes(self):
        text = "\n".join([
            "2．快重传和快恢复",
            "采用快重传算法可以让发送方尽早知道个别报文段的丢失。",
            "TCP 拥塞控制中的窗口机制会根据网络状态调整发送速率。",
        ])
        structure = {"mode": "SEPARATED", "content_pages": [245], "question_pages": [], "answer_pages": []}

        for mode in (None, "exam", "image", "txt"):
            result = split_questions(_make_blocks(text, page=245), structure=structure, import_mode=mode)
            assert len(result) == 1, f"mode={mode} should not apply book/content prose skip"
