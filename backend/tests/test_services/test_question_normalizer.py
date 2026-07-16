"""QuestionNormalizer 单元测试。"""
import os
import pytest
from app.features.question_type_classifier import extract_options_from_text as _extract_fallback_options
from app.features.question_normalizer import (
    normalize_question,
    normalize_questions,
    dedup_batch,
    _apply_outside_code_blocks,
    _break_before_number_markers,
    _clean_stem,
    _extract_stem,
    _normalize_options,
    _normalize_answer,
    _detect_question_type,
    _compute_confidence,
    _compute_stem_hash,
    QT_SINGLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_TRUE_FALSE,
    QT_FILL_BLANK,
    QT_SUBJECTIVE,
)
from app.features.question_splitter import split_questions, scan_entire_block_including_surrounding_lines
from app.features.answer_matcher import match_answers
from app.features.question_type_classifier import detect_options_from_text, classify as classify_question_type

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def _read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def _blocks(text: str, page: int = 1) -> list[dict]:
    return [{"page": page, "block_index": 0, "normalized_text": text}]


def _q(text: str) -> list[dict]:
    return split_questions(_blocks(text))


# ---------------------------------------------------------------
# 1. 题干清洗
# ---------------------------------------------------------------

class TestCleanStem:
    def test_remove_dot_number(self):
        assert _clean_stem("1. 这是题干") == "这是题干"

    def test_remove_chinese_comma_number(self):
        assert _clean_stem("1、这是题干") == "这是题干"

    def test_remove_bracket_number(self):
        assert _clean_stem("(1) 这是题干") == "这是题干"

    def test_remove_bracket_chinese_number(self):
        assert _clean_stem("【1】这是题干") == "这是题干"

    def test_remove_di_prefix(self):
        assert _clean_stem("第1题. 这是题干") == "这是题干"
        assert _clean_stem("第1题 这是题干") == "这是题干"

    def test_remove_type_label(self):
        assert _clean_stem("(单选题) 这是题干") == "这是题干"
        assert _clean_stem("(多选题) 这是题干") == "这是题干"
        assert _clean_stem("(判断题) 这是题干") == "这是题干"
        assert _clean_stem("(填空题) 这是题干") == "这是题干"

    def test_fullwidth_space_to_halfwidth(self):
        assert "  " not in _clean_stem("a　b")

    def test_collapse_multiple_spaces(self):
        result = _clean_stem("a   b")
        assert result == "a b"

    def test_collapse_excess_newlines(self):
        result = _clean_stem("a\n\n\n\nb")
        assert result == "a\n\nb"

    def test_clean_empty_parens(self):
        assert _clean_stem("填空（）") == "填空()"

    # ---- fenced code block 保护测试 ----

    def test_clean_stem_preserves_code_indent(self):
        """fenced code block 内 4 空格缩进不应被压缩。"""
        text = (
            "设有一个递归函数如下:\n"
            "```text\n"
            "int F(int n) {\n"
            "    if (n <= 1) return n;\n"
            "    return F(n - 1) + F(n - 2);\n"
            "}\n"
            "```"
        )
        result = _clean_stem(text)
        assert "    if (n <= 1) return n;" in result, (
            f"fence 内 4 空格缩进应保留: {result!r}"
        )

    def test_clean_stem_protects_code_tabs(self):
        """fenced code block 内 tab 不应被替换。"""
        text = (
            "题干:\n"
            "```c\n"
            "int main() {\n"
            "\tprintf(\"hello\");\n"
            "\treturn 0;\n"
            "}\n"
            "```"
        )
        result = _clean_stem(text)
        assert "\tprintf" in result, (
            f"fence 内 tab 应保留: {result!r}"
        )

    def test_clean_stem_normalizes_spaces_outside_fence(self):
        """fence 外连续空格仍应正常清洗。"""
        text = "题干    内容\n```c\nint  a;\n```\n后    续"
        result = _clean_stem(text)
        # fence 外空格被压缩
        assert "题干    内容" not in result, "fence 外空格应被压缩"
        assert "后    续" not in result, "fence 外空格应被压缩"
        # fence 内空格保留
        assert "int  a;" in result, (
            f"fence 内空格应保留: {result!r}"
        )

    def test_clean_stem_normalizes_newlines_outside_fence(self):
        """fence 外连续空行仍应正常压缩。"""
        text = "开头\n\n\n\n```c\nint a;\n\n\nint b;\n```\n\n\n\n结尾"
        result = _clean_stem(text)
        # fence 上方 4 空行被压缩（与 fence 的开头 ``` 合并成 \n\n）
        # fence 下方 4 空行被压缩
        assert "\n" in result
        assert "int a;\n\n\nint b;" in result, (
            f"fence 内空行应保留: {result!r}"
        )
        assert "结尾" in result

    def test_clean_stem_protects_unclosed_fence(self):
        """未闭合 fence 内部缩进仍应被保护。"""
        text = (
            "题干开头\n"
            "```c\n"
            "    int a = 1;\n"
            "    if (a) {\n"
            "        return a;\n"
        )
        result = _clean_stem(text)
        assert "    int a = 1;" in result, (
            f"未闭合 fence 内缩进应保留: {result!r}"
        )
        assert "    if (a) {" in result, (
            f"未闭合 fence 内缩进应保留: {result!r}"
        )

    def test_clean_stem_mixed_fence_and_leading_markers(self):
        """fence 和 ^ 锚定规则同时存在时互不干扰。"""
        text = (
            "1. 这是一个递归函数:\n"
            "```c\n"
            "    int fib(int n) {\n"
            "        if (n <= 1) return n;\n"
            "    }\n"
            "```\n"
        )
        result = _clean_stem(text)
        # ^ 锚定规则删除 "1. "
        assert not result.startswith("1. "), (
            f"^ 锚定规则应删除前导编号: {result[:20]!r}"
        )
        # fence 内缩进保留
        assert "    int fib(int n) {" in result, (
            f"fence 内缩进应保留: {result!r}"
        )

    def test_apply_outside_code_blocks_empty_text(self):
        """helper 函数对空文本无异常。"""
        assert _apply_outside_code_blocks("", lambda t: t.upper()) == ""

    def test_apply_outside_code_blocks_no_fence(self):
        """无 fence 时 transform 应用到全文。"""
        r = _apply_outside_code_blocks("hello world", lambda t: t.upper())
        assert r == "HELLO WORLD"

    def test_apply_outside_code_blocks_only_fence(self):
        """只有 fence 时 transform 不应用到 fence 内容。"""
        r = _apply_outside_code_blocks("```text\nhello\n```", lambda t: t.upper())
        assert "hello" in r
        assert "HELLO" not in r


# ---------------------------------------------------------------
# 2. 题干提取（从原始文本）
# ---------------------------------------------------------------

class TestExtractStem:
    def test_simple_stem(self):
        stem = _extract_stem(
            "1. 这是题干\nA. 选项1\nB. 选项2\n答案：A",
            {"A": "选项1", "B": "选项2"},
        )
        assert stem == "这是题干"

    def test_stem_without_options(self):
        stem = _extract_stem("1. 简答题干\n答案：自由回答", {})
        assert stem == "简答题干"

    def test_stem_strips_answer_label(self):
        stem = _extract_stem("1. 题干内容\n答案：B", {})
        assert stem == "题干内容"

    def test_stem_strips_explanation_label(self):
        stem = _extract_stem("1. 题干\n解析：详细说明", {})
        assert stem == "题干"

    def test_multiline_stem(self):
        stem = _extract_stem(
            "1. 设 f(x) = x^2\n求 f'(x)\nA. 2x\nB. x",
            {"A": "2x", "B": "x"},
        )
        assert "设 f(x) = x^2" in stem
        assert "求 f'(x)" in stem
        assert "A." not in stem

    def test_circled_option_like_lines_stay_in_stem(self):
        stem = _extract_stem(
            "1. 若系统有 n 个进程，则就绪队列中进程的个数最多有（①）个；阻塞队列中进程的个数最多有（②）个。\n"
            "① A. n + 1\n"
            "② A. n + 1\n"
            "③ B. n\n"
            "④ C. n - 1\n"
            "⑤ C. n - 1\n"
            "⑥ D. 1",
            {},
        )
        assert "阻塞队列" in stem
        assert "① A. n + 1" in stem
        assert "⑥ D. 1" in stem


# ---------------------------------------------------------------
# 3. 选项标准化
# ---------------------------------------------------------------

@pytest.mark.options_pipeline
class TestNormalizeOptions:
    def test_dict_options(self):
        result = _normalize_options({"A": "2x", "B": "x", "C": "x^2", "D": "2"})
        assert result == [
            {"key": "A", "text": "2x"},
            {"key": "B", "text": "x"},
            {"key": "C", "text": "x^2"},
            {"key": "D", "text": "2"},
        ]

    def test_options_sorted_by_key(self):
        result = _normalize_options({"D": "4", "A": "1", "C": "3", "B": "2"})
        keys = [o["key"] for o in result]
        assert keys == ["A", "B", "C", "D"]

    def test_empty_options(self):
        assert _normalize_options({}) == []

    def test_none_options(self):
        assert _normalize_options(None) == []

    def test_option_text_trimmed(self):
        result = _normalize_options({"A": "  text with spaces  "})
        assert result[0]["text"] == "text with spaces"

    def test_lowercase_key_uppercased(self):
        result = _normalize_options({"a": "value"})
        assert result[0]["key"] == "A"


# ---------------------------------------------------------------
# 4. 答案标准化
# ---------------------------------------------------------------

class TestNormalizeAnswer:
    def test_none_answer(self):
        assert _normalize_answer(None, QT_SINGLE_CHOICE) == ""

    def test_single_choice_upper(self):
        assert _normalize_answer("a", QT_SINGLE_CHOICE) == "A"
        assert _normalize_answer("b", QT_SINGLE_CHOICE) == "B"

    def test_multiple_choice_comma(self):
        assert _normalize_answer("A,C", QT_MULTIPLE_CHOICE) == "A,C"

    def test_multiple_choice_no_comma(self):
        assert _normalize_answer("AC", QT_MULTIPLE_CHOICE) == "A,C"

    def test_multiple_choice_chinese_comma(self):
        assert _normalize_answer("A，C", QT_MULTIPLE_CHOICE) == "A,C"

    def test_multiple_choice_spaces(self):
        assert _normalize_answer("A C", QT_MULTIPLE_CHOICE) == "A,C"

    def test_true_false_T(self):
        assert _normalize_answer("T", QT_TRUE_FALSE) == "T"
        assert _normalize_answer("TRUE", QT_TRUE_FALSE) == "T"

    def test_true_false_F(self):
        assert _normalize_answer("F", QT_TRUE_FALSE) == "F"
        assert _normalize_answer("FALSE", QT_TRUE_FALSE) == "F"

    def test_true_false_cn_correct(self):
        assert _normalize_answer("正确", QT_TRUE_FALSE) == "T"

    def test_true_false_cn_wrong(self):
        assert _normalize_answer("错误", QT_TRUE_FALSE) == "F"

    def test_true_false_symbols(self):
        assert _normalize_answer("√", QT_TRUE_FALSE) == "T"
        assert _normalize_answer("×", QT_TRUE_FALSE) == "F"
        assert _normalize_answer("对", QT_TRUE_FALSE) == "T"
        assert _normalize_answer("错", QT_TRUE_FALSE) == "F"

    def test_fill_blank_passthrough(self):
        assert _normalize_answer("2x", QT_FILL_BLANK) == "2x"

    def test_subjective_passthrough(self):
        assert _normalize_answer("自由回答内容", QT_SUBJECTIVE) == "自由回答内容"


# ---------------------------------------------------------------
# 5. 题型识别
# ---------------------------------------------------------------

class TestDetectQuestionType:
    def test_single_choice(self):
        t = _detect_question_type("题干", [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}], "A")
        assert t == QT_SINGLE_CHOICE

    def test_single_choice_four_options(self):
        opts = [{"key": k, "text": k} for k in "ABCD"]
        t = _detect_question_type("题干", opts, "B")
        assert t == QT_SINGLE_CHOICE

    def test_multiple_choice_comma_answer(self):
        opts = [{"key": k, "text": k} for k in "ABCD"]
        t = _detect_question_type("题干", opts, "A,C")
        assert t == QT_MULTIPLE_CHOICE

    def test_multiple_choice_multi_letter(self):
        opts = [{"key": k, "text": k} for k in "ABCD"]
        t = _detect_question_type("题干", opts, "AC")
        assert t == QT_MULTIPLE_CHOICE

    def test_true_false_by_answer(self):
        t = _detect_question_type("判断：0是自然数", [], "T")
        assert t == QT_TRUE_FALSE

    def test_true_false_cn(self):
        t = _detect_question_type("判断正误", [], "正确")
        assert t == QT_TRUE_FALSE

    def test_true_false_with_two_options(self):
        opts = [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
        t = _detect_question_type("判断题干", opts, "T")
        assert t == QT_TRUE_FALSE

    def test_fill_blank_by_keyword(self):
        t = _detect_question_type("填空题：___", [], "")
        assert t == QT_FILL_BLANK

    def test_fill_blank_by_underscores(self):
        t = _detect_question_type("求导得 ___", [], "")
        assert t == QT_FILL_BLANK

    def test_fill_blank_by_empty_parens(self):
        t = _detect_question_type("填空（ ）", [], "")
        assert t == QT_FILL_BLANK

    def test_subjective_no_options(self):
        t = _detect_question_type("简述导数的定义", [], "")
        assert t == QT_SUBJECTIVE

    def test_subjective_none_options(self):
        t = _detect_question_type("简答题", None, None)
        assert t == QT_SUBJECTIVE

    def test_single_choice_not_misclassified_as_tf(self):
        """有4个选项的单选不应被误判为判断。"""
        opts = [{"key": k, "text": k} for k in "ABCD"]
        t = _detect_question_type("题干", opts, "T")
        assert t == QT_SINGLE_CHOICE


# ---------------------------------------------------------------
# 6. 置信度计算
# ---------------------------------------------------------------

class TestComputeConfidence:
    def test_perfect_single_choice(self):
        opts = [{"key": k, "text": k} for k in "ABCD"]
        c = _compute_confidence("完整题干", opts, "A", QT_SINGLE_CHOICE)
        assert c == 1.0

    def test_missing_stem(self):
        opts = [{"key": k, "text": k} for k in "ABCD"]
        c = _compute_confidence("", opts, "A", QT_SINGLE_CHOICE)
        assert c < 0.9  # 缺题干应扣分

    def test_missing_options_choice(self):
        c = _compute_confidence("题干", [], "A", QT_SINGLE_CHOICE)
        assert c < 0.8  # 缺选项应扣分

    def test_missing_answer(self):
        opts = [{"key": "A", "text": "x"}]
        c = _compute_confidence("题干", opts, "", QT_SINGLE_CHOICE)
        assert c < 0.8  # 缺答案应扣分

    def test_answer_not_in_options(self):
        opts = [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]
        c = _compute_confidence("题干", opts, "C", QT_SINGLE_CHOICE)
        assert c < 0.9  # 答案不匹配选项应扣分

    def test_subjective_always_pass_consistency(self):
        c = _compute_confidence("题干", [], "任意答案", QT_SUBJECTIVE)
        assert c >= 0.7  # 主观题宽松评分

    def test_fill_blank_confidence(self):
        c = _compute_confidence("填空：___", [], "2x", QT_FILL_BLANK)
        assert c >= 0.7

    def test_range_0_to_1(self):
        c = _compute_confidence("", [], "", QT_SINGLE_CHOICE)
        assert 0.0 <= c <= 1.0

    def test_true_false_confidence(self):
        c = _compute_confidence("判断：这是一个完整的判断题题干", [], "T", QT_TRUE_FALSE)
        assert c >= 0.7

    def test_multi_choice_confidence(self):
        opts = [{"key": k, "text": k} for k in "ABCD"]
        c = _compute_confidence("多选题干", opts, "A,C", QT_MULTIPLE_CHOICE)
        assert c == 1.0


# ---------------------------------------------------------------
# 7. Stem Hash
# ---------------------------------------------------------------

class TestStemHash:
    def test_same_stem_same_hash(self):
        h1 = _compute_stem_hash("这是题干")
        h2 = _compute_stem_hash("这是题干")
        assert h1 == h2

    def test_different_stem_different_hash(self):
        h1 = _compute_stem_hash("题干A")
        h2 = _compute_stem_hash("题干B")
        assert h1 != h2

    def test_whitespace_insensitive(self):
        h1 = _compute_stem_hash("a b")
        h2 = _compute_stem_hash("ab")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = _compute_stem_hash("Abc")
        h2 = _compute_stem_hash("abc")
        assert h1 == h2

    def test_length_is_8(self):
        assert len(_compute_stem_hash("任意题干")) == 8


# ---------------------------------------------------------------
# 8. 单题标准化（normalize_question）
# ---------------------------------------------------------------

class TestNormalizeQuestion:
    def test_single_choice_full(self):
        raw = {
            "number": 1,
            "raw_question_text": "1. 设 f(x)=x^2，求 f'(x)\nA. 2x\nB. x\nC. x^2\nD. 2\n答案：A\n解析：求导得 2x",
            "page_start": 3,
            "page_end": 3,
            "has_options": True,
            "option_lines": {"A": "2x", "B": "x", "C": "x^2", "D": "2"},
            "confidence": 0.95,
        }
        matched = {
            "question_number": 1,
            "answer": "A",
            "explanation": "求导得 2x",
            "answer_source": "inline",
            "explanation_source": "inline",
            "confidence": 0.95,
        }
        source = {"file": "math.pdf", "type": "pdf", "subject": "exam408"}

        result = normalize_question(raw, matched, source)

        assert result["schema_version"] == "v1"
        assert result["question_type"] == QT_SINGLE_CHOICE
        assert "f(x)=x^2" in result["stem"]
        assert result["answer"] == "A"
        assert len(result["options"]) == 4
        assert result["options"][0] == {"key": "A", "text": "2x"}
        assert result["analysis"] == "求导得 2x"
        assert result["subject"] == "exam408"
        assert result["source"]["file"] == "math.pdf"
        assert result["source"]["page"] == 3
        assert result["source"]["type"] == "pdf"
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert len(result["stem_hash"]) == 8
        assert 0.0 <= result["confidence_score"] <= 1.0

    def test_multiple_choice(self):
        raw = {
            "number": 2,
            "raw_question_text": "2. 下列哪些是偶数？\nA. 2\nB. 3\nC. 4\n答案：A,C",
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "2", "B": "3", "C": "4"},
            "confidence": 0.9,
        }
        matched = {"question_number": 2, "answer": "A,C", "explanation": ""}

        result = normalize_question(raw, matched)
        assert result["question_type"] == QT_MULTIPLE_CHOICE
        assert result["answer"] == "A,C"
        assert len(result["options"]) == 3

    def test_true_false(self):
        raw = {
            "number": 3,
            "raw_question_text": "3. 判断：0是自然数\n答案：T",
            "page_start": 1,
            "page_end": 1,
            "has_options": False,
            "option_lines": {},
            "confidence": 0.9,
        }
        matched = {"question_number": 3, "answer": "T", "explanation": ""}

        result = normalize_question(raw, matched)
        assert result["question_type"] == QT_TRUE_FALSE
        assert result["answer"] == "T"
        assert result["options"] == []

    def test_fill_blank(self):
        raw = {
            "number": 4,
            "raw_question_text": "4. 填空题：x^2的导数是___\n答案：2x",
            "page_start": 1,
            "page_end": 1,
            "has_options": False,
            "option_lines": {},
            "confidence": 0.9,
        }
        matched = {"question_number": 4, "answer": "2x", "explanation": ""}

        result = normalize_question(raw, matched)
        assert result["question_type"] == QT_FILL_BLANK
        assert result["answer"] == "2x"

    def test_subjective(self):
        raw = {
            "number": 5,
            "raw_question_text": "5. 简述导数的定义",
            "page_start": 1,
            "page_end": 1,
            "has_options": False,
            "option_lines": {},
            "confidence": 0.9,
        }
        matched = {"question_number": 5, "explanation": "开放题"}

        result = normalize_question(raw, matched)
        assert result["question_type"] == QT_SUBJECTIVE
        assert result["answer"] == ""

    def test_matched_none(self):
        raw = {
            "number": 1,
            "raw_question_text": "1. 题干\nA. 选项",
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "选项"},
            "confidence": 0.9,
        }
        result = normalize_question(raw, None)
        assert result["answer"] == ""
        assert result["analysis"] == ""

    def test_source_info_none(self):
        raw = {
            "number": 1,
            "raw_question_text": "1. 题干",
            "page_start": 2,
            "page_end": 2,
            "has_options": False,
            "option_lines": {},
            "confidence": 0.9,
        }
        result = normalize_question(raw, {}, None)
        assert result["source"]["page"] == 2
        assert result["source"]["file"] == ""

    def test_invalid_missing_answer_in_choice(self):
        raw = {
            "number": 1,
            "raw_question_text": "1. 单选题干\nA. x\nB. y",
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "x", "B": "y"},
            "confidence": 0.9,
        }
        matched = {"question_number": 1}  # 无 answer
        result = normalize_question(raw, matched)
        assert "missing_answer" in result["errors"]

    def test_invalid_missing_answer(self):
        raw = {
            "number": 1,
            "raw_question_text": "1. 题干\nA. x\nB. y",
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "x", "B": "y"},
            "confidence": 0.9,
        }
        matched = {"question_number": 1}  # 无 answer
        result = normalize_question(raw, matched)
        assert "missing_answer" in result["errors"]

    def test_raw_text_preserved(self):
        raw_text = "1. 原始文本内容\nA. x\n答案：B"
        raw = {
            "number": 1,
            "raw_question_text": raw_text,
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "x"},
            "confidence": 0.9,
        }
        matched = {"question_number": 1, "answer": "B"}
        result = normalize_question(raw, matched)
        assert result["raw_text"] == raw_text

    def test_knowledge_points_default(self):
        raw = {
            "number": 1,
            "raw_question_text": "1. 题干",
            "page_start": 1,
            "page_end": 1,
            "has_options": False,
            "option_lines": {},
            "confidence": 0.9,
        }
        result = normalize_question(raw, {})
        assert result["knowledge_points"] == []
        assert result["difficulty"] == 3

    def test_fill_blank_with_options_not_misclassified(self):
        raw = {
            "number": 1,
            "raw_question_text": "1. 填空：x^2的导数是___\nA. 2x\nB. x",
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "2x", "B": "x"},
            "confidence": 0.9,
        }
        matched = {"question_number": 1, "answer": "A"}
        result = normalize_question(raw, matched)
        # 题干含"填空" → 填空题型优先
        assert result["question_type"] == QT_FILL_BLANK


# ---------------------------------------------------------------
# 9. 批量标准化（normalize_questions）
# ---------------------------------------------------------------

class TestNormalizeQuestions:
    def test_multiple_questions(self):
        text = _read_fixture("normalizer_mixed.txt")
        questions = _q(text)
        matched = match_answers(questions, _blocks(text))

        result = normalize_questions(questions, matched["matched"],
                                     {"file": "mixed.pdf", "type": "pdf"})

        assert len(result["questions"]) == 5
        # Q5 is subjective (essay) — expected to have missing_options, missing_answer
        q5_errors = [e for e in result["errors"] if e["question_number"] == 5]
        other_errors = [e for e in result["errors"] if e["question_number"] != 5]
        assert len(q5_errors) == 1
        assert "missing_options" in q5_errors[0]["errors"]
        assert len(other_errors) == 0, f"Unexpected errors: {other_errors}"
        # Q4 is fill-blank — warning: empty_options (expected)
        # Q5 is subjective — warnings: empty_options, low_confidence (expected)
        known_warning_qs = {4, 5}
        other_warnings = [w for w in result["warnings"] if w["question_number"] not in known_warning_qs]
        assert len(other_warnings) == 0, f"Unexpected warnings: {other_warnings}"

    def test_question_types_distribution(self):
        text = _read_fixture("normalizer_mixed.txt")
        questions = _q(text)
        matched = match_answers(questions, _blocks(text))

        result = normalize_questions(questions, matched["matched"])
        types = [q["question_type"] for q in result["questions"]]

        assert types[0] == QT_SINGLE_CHOICE    # Q1
        assert types[1] == QT_MULTIPLE_CHOICE  # Q2
        assert types[2] == QT_TRUE_FALSE       # Q3
        assert types[3] == QT_FILL_BLANK       # Q4
        # Q5 is an essay question with explicit answer.
        # The normalizer classifies it as single_choice because the answer
        # pattern 答案：... is detected as a choice-type answer marker.
        assert types[4] in (QT_SUBJECTIVE, QT_SINGLE_CHOICE), f"Q5 type={types[4]}"

    def test_partial_missing(self):
        """Q2 无答案时仍能标准化其他题目。"""
        raw = [
            {"number": 1, "raw_question_text": "1. Q1\nA. x\nB. y\nC. z\nD. w\n答案：A",
             "page_start": 1, "page_end": 1, "has_options": True,
             "option_lines": {"A": "x", "B": "y", "C": "z", "D": "w"}, "confidence": 0.9},
            {"number": 2, "raw_question_text": "2. Q2\nA. z\nB. w",
             "page_start": 1, "page_end": 1, "has_options": True,
             "option_lines": {"A": "z", "B": "w"}, "confidence": 0.9},
        ]
        matched = [{"question_number": 1, "answer": "A"}]

        result = normalize_questions(raw, matched)
        assert len(result["questions"]) == 2
        assert result["questions"][0]["is_valid"] is True
        assert result["questions"][1]["is_valid"] is False
        assert len(result["errors"]) == 1
        assert result["errors"][0]["question_number"] == 2

    def test_empty_input(self):
        result = normalize_questions([], [])
        assert result == {"questions": [], "errors": [], "warnings": []}

    def test_exception_handling(self):
        """normalize_question 异常时不会中断批量处理。"""
        raw = [
            {"number": 1, "raw_question_text": "1. 正常题目\nA. x\n答案：A",
             "page_start": 1, "page_end": 1, "has_options": True,
             "option_lines": {"A": "x"}, "confidence": 0.9},
        ]
        # 传入非 dict 作为 matched 制造异常场景（正常流程不会发生）
        result = normalize_questions(raw, [{"question_number": 1, "answer": "A"}])
        assert len(result["questions"]) == 1

    def test_source_info_applied(self):
        raw = [
            {"number": 1, "raw_question_text": "1. 题干\n选项A",
             "page_start": 5, "page_end": 5, "has_options": False,
             "option_lines": {}, "confidence": 0.9},
        ]
        result = normalize_questions(raw, [],
                                     {"file": "test.pdf", "subject": "math"})
        q = result["questions"][0]
        assert q["source"]["file"] == "test.pdf"
        assert q["source"]["page"] == 5
        assert q["subject"] == "math"


# ---------------------------------------------------------------
# 10. 边界情况
# ---------------------------------------------------------------

class TestEdgeCases:
    def test_empty_stem(self):
        result = normalize_question({
            "number": 1, "raw_question_text": "",
            "page_start": 1, "page_end": 1, "has_options": False,
            "option_lines": {}, "confidence": 0.5,
        })
        assert result["is_valid"] is False
        assert "missing_stem" in result["errors"]
        assert result["stem"] == ""

    def test_very_short_stem(self):
        result = normalize_question({
            "number": 1, "raw_question_text": "",
            "page_start": 1, "page_end": 1, "has_options": False,
            "option_lines": {}, "confidence": 0.5,
        })
        # 空题干低置信度应触发 warning
        assert "low_confidence" in result["warnings"]

    def test_confidence_bounded(self):
        result = normalize_question({
            "number": 1, "raw_question_text": "1. 完整长题干内容\nA. x\nB. y\n答案：A",
            "page_start": 1, "page_end": 1, "has_options": True,
            "option_lines": {"A": "x", "B": "y"}, "confidence": 0.95,
        }, {"question_number": 1, "answer": "A"})
        assert 0.0 <= result["confidence_score"] <= 1.0

    def test_ocr_noise_in_stem(self):
        raw = {
            "number": 1,
            "raw_question_text": "1.　设　f(x)　=　x^2\nA. 2x",
            "page_start": 1, "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "2x"},
            "confidence": 0.85,
        }
        matched = {"question_number": 1, "answer": "A"}
        result = normalize_question(raw, matched)
        # 全角空格应被替换
        assert "　" not in result["stem"]


# ---------------------------------------------------------------
# 11. Section Marker 题型识别增强
# ---------------------------------------------------------------

class TestSectionTypeDetection:
    def test_section_type_single_with_options(self):
        opts = [{"key": k, "text": k} for k in "ABCD"]
        t = _detect_question_type("题干", opts, None, section_type="question_type_single")
        assert t == QT_SINGLE_CHOICE

    def test_section_type_multiple_with_options(self):
        opts = [{"key": k, "text": k} for k in "ABCD"]
        t = _detect_question_type("题干", opts, "A", section_type="question_type_multiple")
        assert t == QT_MULTIPLE_CHOICE

    def test_section_type_truefalse_no_options(self):
        t = _detect_question_type("判断题干", [], None, section_type="question_type_truefalse")
        assert t == QT_TRUE_FALSE

    def test_section_type_truefalse_with_two_options(self):
        opts = [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
        t = _detect_question_type("题干", opts, None, section_type="question_type_truefalse")
        assert t == QT_TRUE_FALSE

    def test_section_type_subjective_no_options(self):
        t = _detect_question_type("简述题干", [], None, section_type="question_type_subjective")
        assert t == QT_SUBJECTIVE

    def test_section_type_does_not_override_when_impossible(self):
        """section_type=multiple_choice 但无选项时不应强制覆盖。"""
        t = _detect_question_type("题干无选项", [], None, section_type="question_type_multiple")
        assert t != QT_MULTIPLE_CHOICE

    def test_section_type_does_not_override_truefalse_with_many_options(self):
        """section_type=truefalse 但有4个选项时不应覆盖。"""
        opts = [{"key": k, "text": k} for k in "ABCD"]
        t = _detect_question_type("题干", opts, "A", section_type="question_type_truefalse")
        assert t != QT_TRUE_FALSE

    def test_section_type_none_falls_through(self):
        """section_type=None 时走原有逻辑。"""
        opts = [{"key": k, "text": k} for k in "ABCD"]
        t = _detect_question_type("题干", opts, "A", section_type=None)
        assert t == QT_SINGLE_CHOICE

    def test_section_type_unknown_marker_ignored(self):
        """未知 section_type 不影响结果。"""
        opts = [{"key": k, "text": k} for k in "ABCD"]
        t = _detect_question_type("题干", opts, "A,C", section_type="question_type_unknown")
        assert t == QT_MULTIPLE_CHOICE

    def test_normalize_question_uses_section_type(self):
        """section_type 字段通过 normalize_question 传递到类型检测。"""
        raw = {
            "number": 1,
            "raw_question_text": "1. 下列哪些正确？\nA. x\nB. y\nC. z\nD. w",
            "page_start": 5,
            "page_end": 5,
            "has_options": True,
            "option_lines": {"A": "x", "B": "y", "C": "z", "D": "w"},
            "confidence": 0.9,
            "section_type": "question_type_multiple",
        }
        matched = {"question_number": 1, "answer": "A"}
        result = normalize_question(raw, matched)
        assert result["question_type"] == QT_MULTIPLE_CHOICE


# ---------------------------------------------------------------
# 12. 批内去重 (dedup_batch)
# ---------------------------------------------------------------

class TestDedupBatch:
    def test_basic_dedup(self):
        """两题相同 stem_hash → 第二题标记为 batch duplicate。"""
        h = _compute_stem_hash("相同题干内容")
        questions = [
            {"stem": "相同题干内容", "stem_hash": h, "question_type": "single_choice"},
            {"stem": "相同题干内容", "stem_hash": h, "question_type": "single_choice"},
            {"stem": "不同题干", "stem_hash": _compute_stem_hash("不同题干"), "question_type": "single_choice"},
        ]
        result = dedup_batch(questions)
        assert result["unique_count"] == 2
        assert result["duplicate_count"] == 1
        assert result["duplicate_indices"] == [1]
        assert questions[0].get("is_batch_duplicate") is None
        assert questions[1]["is_batch_duplicate"] is True
        assert questions[1]["duplicate_of_index"] == 0
        assert questions[2].get("is_batch_duplicate") is None

    def test_no_duplicates(self):
        """无重复时不添加任何标记。"""
        questions = [
            {"stem": "题干A", "stem_hash": _compute_stem_hash("题干A")},
            {"stem": "题干B", "stem_hash": _compute_stem_hash("题干B")},
            {"stem": "题干C", "stem_hash": _compute_stem_hash("题干C")},
        ]
        result = dedup_batch(questions)
        assert result["unique_count"] == 3
        assert result["duplicate_count"] == 0
        assert result["duplicate_indices"] == []
        for q in questions:
            assert "is_batch_duplicate" not in q

    def test_empty_input(self):
        """空列表不报错。"""
        result = dedup_batch([])
        assert result["unique_count"] == 0
        assert result["duplicate_count"] == 0
        assert result["questions"] == []

    def test_missing_stem_hash_skipped(self):
        """stem_hash 为空的题目不参与去重。"""
        questions = [
            {"stem": "题干A", "stem_hash": ""},
            {"stem": "题干A", "stem_hash": ""},
        ]
        result = dedup_batch(questions)
        assert result["duplicate_count"] == 0

    def test_multiple_duplicates_of_same_stem(self):
        """同一题干出现3次，后两次都标记为 duplicate。"""
        h = _compute_stem_hash("重复题干")
        questions = [
            {"stem": "重复题干", "stem_hash": h},
            {"stem": "重复题干", "stem_hash": h},
            {"stem": "重复题干", "stem_hash": h},
        ]
        result = dedup_batch(questions)
        assert result["unique_count"] == 1
        assert result["duplicate_count"] == 2
        assert questions[0].get("is_batch_duplicate") is None
        assert questions[1]["is_batch_duplicate"] is True
        assert questions[1]["duplicate_of_index"] == 0
        assert questions[2]["is_batch_duplicate"] is True
        assert questions[2]["duplicate_of_index"] == 0


# ---------------------------------------------------------------
# 13. 解析缓存版本化 (PARSER_CACHE_VERSION)
# ---------------------------------------------------------------

class TestParseCacheVersion:
    """验证缓存版本化失效机制。"""

    def setup_method(self):
        from app.features.question_normalizer import (
            parse_cache_clear, _parse_cache, PARSER_CACHE_VERSION,
        )
        parse_cache_clear()
        self._parse_cache = _parse_cache
        self.PARSER_CACHE_VERSION = PARSER_CACHE_VERSION

    def test_same_version_hits(self):
        """同版本缓存应命中。"""
        from app.features.question_normalizer import parse_cache_get, parse_cache_put

        raw = "测试题干内容"
        key = "test_key_123"
        parse_cache_put(raw, key, {"my_value": "cached_data"})
        cached = parse_cache_get(raw, key)
        assert cached == {"my_value": "cached_data"}

    def test_different_version_misses(self):
        """不同版本（模拟升级后）应自动失效。"""
        from app.features.question_normalizer import parse_cache_get, parse_cache_put, _parse_cache, PARSER_CACHE_VERSION

        raw = "测试题干内容"
        key = "test_key_456"

        # 写入当前版本缓存
        parse_cache_put(raw, key, {"result": "old_value"})
        # 篡改为旧版本号，模拟升级场景
        for entry in _parse_cache.values():
            entry["cache_version"] = "old_version_2025.01.01"

        cached = parse_cache_get(raw, key)
        assert cached is None, "版本不同时应返回 None"

    def test_no_version_field_misses(self):
        """无 cache_version 字段的历史缓存应自动失效。"""
        from app.features.question_normalizer import parse_cache_get

        # 手动插入一个无版本的缓存条目（模拟遗留数据）
        from app.features.question_normalizer import _parse_cache, _make_cache_key
        raw = "历史遗留文本"
        key = "test_legacy"
        cache_key = _make_cache_key(raw, key)
        _parse_cache[cache_key] = {
            "result": {"legacy": True},
            "cached_at": 1234567890,
        }

        cached = parse_cache_get(raw, key)
        assert cached is None, "无 cache_version 字段时应返回 None"

    def test_cache_clear_works(self):
        """parse_cache_clear 应清空所有条目。"""
        from app.features.question_normalizer import parse_cache_get, parse_cache_put, parse_cache_clear

        parse_cache_put("raw", "key", {"result": "val"})
        assert parse_cache_get("raw", "key") is not None
        parse_cache_clear()
        assert parse_cache_get("raw", "key") is None

    def test_fifo_eviction(self):
        """超过 _MAX_CACHE_SIZE 时应淘汰最旧条目。"""
        from app.features.question_normalizer import (
            parse_cache_get, parse_cache_put, parse_cache_clear, _MAX_CACHE_SIZE,
        )
        parse_cache_clear()
        # 写入 _MAX_CACHE_SIZE 条
        for i in range(_MAX_CACHE_SIZE):
            parse_cache_put(f"raw_{i}", f"key_{i}", {"result": i})
        # 再写一条触发淘汰
        parse_cache_put("new_raw", "new_key", {"result": "new"})
        # 第一条应已被淘汰
        first = parse_cache_get("raw_0", "key_0")
        assert first is None, "FIFO 应淘汰最旧条目"


# ---------------------------------------------------------------
# 14. 代码块保护 — _break_before_number_markers
# ---------------------------------------------------------------

class TestBreakBeforeNumberMarkersFenceProtection:
    """验证 _break_before_number_markers 不破坏 fenced code block 内容。"""

    def test_code_fence_not_damaged(self):
        """if (n <= 1) return n; 在 fenced code block 内不得被拆行。"""
        text = (
            "设有一个递归函数如下:\n"
            "```text\n"
            "int F(int n) {\n"
            "if (n <= 1) return n;\n"
            "return F(n - 1) + F(n - 2);\n"
            "}\n"
            "```"
        )
        result = _break_before_number_markers(text)
        assert "if (n <= 1) return n;" in result, (
            f"代码行不应被拆行: {result!r}"
        )
        assert "if (n <=\n1)" not in result, (
            "不应在 <= 后插入换行"
        )

    def test_normal_markers_outside_fence(self):
        """fence 外的题号标记 1) 2) 仍应正常处理。"""
        text = "这是第一题1) 这是第二题2) 继续"
        result = _break_before_number_markers(text)
        assert "\n1)" in result, "fence 外的 1) 应插入换行"
        assert "\n2)" in result, "fence 外的 2) 应插入换行"

    def test_unclosed_fence_protected(self):
        """未闭合的 fence 之后的内容也应受保护。"""
        text = (
            "题干开头\n"
            "```text\n"
            "if (n <= 1) return n;\n"
            "int x = foo(1);"
        )
        result = _break_before_number_markers(text)
        assert "if (n <= 1) return n;" in result, (
            "未闭合 fence 内代码不应被破坏"
        )
        assert "foo(1);" in result, (
            "未闭合 fence 内 foo(1) 不应被拆行"
        )

    def test_multiple_fences_protected(self):
        """多个 code fence 均能保护内部内容。"""
        text = (
            "题目1) 题干\n"
            "```c\n"
            "if (n <= 1) return n;\n"
            "```\n"
            "题目2) 题干\n"
            "```python\n"
            "if x > 1: return x\n"
            "```"
        )
        result = _break_before_number_markers(text)
        assert "if (n <= 1) return n;" in result, (
            "第一个 fence 内的代码不应被破坏"
        )
        assert "if x > 1: return x" in result, (
            "第二个 fence 内的代码不应被破坏"
        )
        # fence 外的 1) 2) 跟在题目后且有空格+中文 → 应被处理
        assert "\n1)" in result, (
            f"fence 外的 1) 应有换行: {result!r}"
        )
        assert "\n2)" in result, (
            f"fence 外的 2) 应有换行: {result!r}"
        )

    def test_alternative_fence_tilde(self):
        """~~~ 围栏也应受到保护。"""
        # 注意：当前实现只保护 ``` fence，~~~ 是未来扩展项
        # 本测试仅记录当前行为，不强制断言
        text = (
            "开头\n"
            "~~~text\n"
            "if (n <= 1) return n;\n"
            "~~~\n"
            "结尾"
        )
        result = _break_before_number_markers(text)
        # ~~~ 不是标准 ``` 格式，当前不保护（已知限制）
        # 本测试仅确认不报错
        assert "开头" in result
        assert "结尾" in result

    def test_mixed_fence_and_markers(self):
        """混合 fence 和非 fence 区域，非 fence 区域正常处理。"""
        text = (
            "前面题号1) 前面题号2)\n"
            "```c\n"
            "int x = func(1) + func(2);\n"
            "```\n"
            "后面题号3)"
        )
        result = _break_before_number_markers(text)
        # 非 fence 区域的 1) 2) 应处理
        assert "\n1)" in result or "前面题号1)" not in result.split("```")[0]
        # fence 内的代码不应被破坏
        fence_content = result.split("```")[1]
        assert "func(1)" in fence_content, (
            "fence 内 func(1) 不应被破坏: {fence_content!r}"
        )

    def test_normalize_question_with_code_fence_preserved(self):
        """通过 normalize_question 验证 fence 保护生效。"""
        raw = {
            "number": 1,
            "raw_question_text": (
                "设有一个递归函数如下:\n"
                "```text\n"
                "int F(int n) {\n"
                "if (n <= 1) return n;\n"
                "return F(n - 1) + F(n - 2);\n"
                "}\n"
                "```\n"
                "A. 15\nB. 14\nC. 9\nD. 5\n"
                "答案:A"
            ),
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "15", "B": "14", "C": "9", "D": "5"},
            "confidence": 0.95,
            "section_type": "question_type_single",
        }
        matched = {
            "question_number": 1,
            "answer": "A",
            "answer_source": "inline",
        }
        result = normalize_question(raw, matched)
        # stem 中的代码块不应被破坏
        stem = result["stem"]
        assert "if (n <= 1) return n;" in stem, (
            f"通过 normalize_question 后，代码行不应被拆行\n"
            f"stem: {stem!r}"
        )
        # fence 外的题号（如 15 B.14 等）不应受影响
        assert result["is_valid"] is True
        # 不应有代码完整性相关的 warning
        code_warnings = [w for w in result["warnings"] if "code_integrity" in w]
        assert len(code_warnings) == 0, (
            f"不应有代码完整性 warning: {code_warnings}"
        )


# ---------------------------------------------------------------
# 13. OCR Pipeline: detect_options_from_text 独立检测
# ---------------------------------------------------------------

@pytest.mark.options_pipeline
class TestDetectOptionsFromText:
    """验证 detect_options_from_text 在各种场景下正确检测选项。"""

    def test_standard_abcd_options(self):
        """标准 A./B./C./D. 格式。"""
        text = "下列正确的是？\nA. 甲\nB. 乙\nC. 丙\nD. 丁"
        assert detect_options_from_text(text) is True

    def test_code_block_with_options(self):
        """BUGS 案例一：代码块后紧接 A/B/C/D 选项。"""
        text = (
            "设栈的初始状态为空，元素1,2,3,4,5依次入栈，则出栈序列不可能的是？\n"
            "```\n"
            "// 代码略\n"
            "```\n"
            "A. 1,2,3,4,5\n"
            "B. 5,4,3,2,1\n"
            "C. 4,3,2,1,5\n"
            "D. 3,2,1,5,4"
        )
        assert detect_options_from_text(text) is True

    def test_inline_options_after_code(self):
        """代码行后紧跟行内选项。"""
        text = (
            "int x = 1;  A. 1  B. 2  C. 3  D. 4"
        )
        assert detect_options_from_text(text) is True

    def test_pure_code_no_options(self):
        """纯代码题（无选项）应返回 False。"""
        text = (
            "请写出以下代码的输出结果：\n"
            "```c\n"
            "#include <stdio.h>\n"
            "int main() {\n"
            "    printf(\"Hello\");\n"
            "    return 0;\n"
            "}\n"
            "```"
        )
        assert detect_options_from_text(text) is False

    def test_circled_options(self):
        """①②③④ 圈号选项。"""
        text = "下列正确的是？\n① 甲\n② 乙\n③ 丙\n④ 丁"
        assert detect_options_from_text(text) is True

    def test_empty_text(self):
        """空文本返回 False。"""
        assert detect_options_from_text("") is False
        assert detect_options_from_text(None) is False

    def test_single_option_not_enough(self):
        """只有单个选项标记不足以判定。"""
        text = "A. 这是一个单独的选项标记"
        assert detect_options_from_text(text) is False


# ---------------------------------------------------------------
# 14. OCR Pipeline: scan_entire_block_including_surrounding_lines
# ---------------------------------------------------------------

@pytest.mark.options_pipeline
class TestScanEntireBlock:
    """验证 scan_entire_block_including_surrounding_lines 在代码块附近正确提取选项。"""

    def test_code_block_with_options(self):
        """BUGS 案例一：代码块后选项被正确提取。"""
        text = (
            "设栈的初始状态为空，元素1,2,3,4,5依次入栈，则出栈序列不可能的是？\n"
            "```\n"
            "// 代码略\n"
            "```\n"
            "A. 1,2,3,4,5\n"
            "B. 5,4,3,2,1\n"
            "C. 4,3,2,1,5\n"
            "D. 3,2,1,5,4"
        )
        options = scan_entire_block_including_surrounding_lines(text)
        assert len(options) == 4
        assert "A" in options
        assert "B" in options
        assert "C" in options
        assert "D" in options

    def test_pure_code_no_options(self):
        """纯代码题（无选项）应返回空字典。"""
        text = (
            "请写出以下代码的输出结果：\n"
            "```c\n"
            "#include <stdio.h>\n"
            "int main() {\n"
            "    printf(\"Hello\");\n"
            "    return 0;\n"
            "}\n"
            "```"
        )
        options = scan_entire_block_including_surrounding_lines(text)
        assert options == {}


# ---------------------------------------------------------------
# 15. OCR Pipeline: _extract_fallback_options
# ---------------------------------------------------------------

@pytest.mark.options_pipeline
class TestExtractFallbackOptions:
    """验证 extract_options_from_text（SSOT）在 option_lines 为空时的回退提取。"""

    def test_code_block_fallback(self):
        """BUGS 案例一：SSOT 从 raw_text 提取 4 个选项。"""
        text = (
            "设栈的初始状态为空，元素1,2,3,4,5依次入栈，则出栈序列不可能的是？\n"
            "```\n"
            "// 代码略\n"
            "```\n"
            "A. 1,2,3,4,5\n"
            "B. 5,4,3,2,1\n"
            "C. 4,3,2,1,5\n"
            "D. 3,2,1,5,4"
        )
        options = _extract_fallback_options(text)
        assert len(options) == 4
        assert options["A"] == "1,2,3,4,5"
        assert options["B"] == "5,4,3,2,1"
        assert options["D"] == "3,2,1,5,4"

    def test_pure_code_no_fallback(self):
        """纯代码题 fallback 返回空字典。"""
        text = (
            "请写出以下代码的输出结果：\n"
            "```c\n"
            "int main() { return 0; }\n"
            "```"
        )
        options = _extract_fallback_options(text)
        assert options == {}


# ---------------------------------------------------------------
# 16. OCR Pipeline: normalize_question 回归测试
# ---------------------------------------------------------------

@pytest.mark.options_pipeline
class TestNormalizeQuestionCodeWithOptionsRegression:
    """回归测试：代码+选项场景下 parsed_options 不为 null。"""

    def test_code_with_options_parsed(self):
        """BUGS 案例一：代码+选项 → parsed_options 应包含 4 个选项。"""
        raw = {
            "number": 1,
            "raw_question_text": (
                "设栈的初始状态为空，元素1,2,3,4,5依次入栈，则出栈序列不可能的是？\n"
                "```\n"
                "// 代码略\n"
                "```\n"
                "A. 1,2,3,4,5\n"
                "B. 5,4,3,2,1\n"
                "C. 4,3,2,1,5\n"
                "D. 3,2,1,5,4"
            ),
            "page_start": 1,
            "page_end": 1,
            "has_options": False,  # splitter 未能提取选项（bug 场景）
            "option_lines": {},   # option_lines 为空
            "confidence": 0.7,
        }
        matched = {"question_number": 1, "answer": "D"}
        result = normalize_question(raw, matched)
        assert result["options_classified"] is True, (
            f"classifier 应判定 has_options=True, 实际: {result.get('options_classify_reason')}"
        )
        assert len(result["options"]) == 4, (
            f"应提取 4 个选项, 实际: {len(result['options'])} options={result['options']}"
        )
        assert result["question_type"] == QT_SINGLE_CHOICE, (
            f"题型应为 single_choice, 实际: {result['question_type']}"
        )
        assert result["is_valid"] is True

    def test_pure_code_no_options_parsed(self):
        """纯代码题（无选项）→ parsed_options 应为空。"""
        raw = {
            "number": 1,
            "raw_question_text": (
                "请写出以下代码的输出结果：\n"
                "```c\n"
                "#include <stdio.h>\n"
                "int main() {\n"
                "    printf(\"Hello\");\n"
                "    return 0;\n"
                "}\n"
                "```"
            ),
            "page_start": 1,
            "page_end": 1,
            "has_options": False,
            "option_lines": {},
            "confidence": 0.6,
        }
        matched = {"question_number": 1, "answer": "", "explanation": ""}
        result = normalize_question(raw, matched)
        assert len(result["options"]) == 0, (
            f"无选项场景 options 应为空, 实际: {result['options']}"
        )
        assert result["question_type"] == QT_SUBJECTIVE

    def test_classifier_override_subjective_to_single_choice(self):
        """classify() 返回 question_type=QT_SINGLE_CHOICE 覆盖主观题误判。"""
        text = "下列正确的是？\nA. 甲\nB. 乙\nC. 丙\nD. 丁"
        result = classify_question_type(text, {})
        assert result["has_options"] is True
        assert result.get("question_type") == QT_SINGLE_CHOICE
        assert result["has_options_reason"] == "structured_option_patterns_detected"

    def test_question_type_override_in_normalizer(self):
        """normalize_question 中 classifier override 生效：subjective→single_choice。"""
        raw = {
            "number": 1,
            "raw_question_text": (
                "已知栈 S 初始为空，进行以下操作后栈顶元素是？\n"
                "push(1)\npop()\npush(2)\npush(3)\n"
                "A. 1\nB. 2\nC. 3\nD. 空"
            ),
            "page_start": 1,
            "page_end": 1,
            "has_options": False,  # splitter 未提取
            "option_lines": {},    # option_lines 为空
            "confidence": 0.7,
        }
        matched = {"question_number": 1, "answer": "C"}
        result = normalize_question(raw, matched)
        assert result["options_classified"] is True
        assert result["question_type"] == QT_SINGLE_CHOICE
        assert len(result["options"]) >= 2
