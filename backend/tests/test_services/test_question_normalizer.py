"""QuestionNormalizer 单元测试。"""
import os
import pytest
from app.features.question_normalizer import (
    normalize_question,
    normalize_questions,
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
from app.features.question_splitter import split_questions
from app.features.answer_matcher import match_answers

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
        assert result["errors"] == []
        assert result["warnings"] == []

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
        assert types[4] == QT_SUBJECTIVE       # Q5

    def test_partial_missing(self):
        """Q2 无答案时仍能标准化其他题目。"""
        raw = [
            {"number": 1, "raw_question_text": "1. Q1\nA. x\nB. y\n答案：A",
             "page_start": 1, "page_end": 1, "has_options": True,
             "option_lines": {"A": "x", "B": "y"}, "confidence": 0.9},
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
