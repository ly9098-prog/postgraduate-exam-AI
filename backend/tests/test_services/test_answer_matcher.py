"""AnswerMatcher 单元测试。"""
import os

from app.features.answer_matcher import (
    _clean_explanation,
    _correct_answer_letter,
    _extract_all_separated_answers,
    _extract_inline_answer,
    _extract_inline_explanation,
    _extract_separated_answer,
    _extract_separated_explanation,
    match_answers,
)
from app.features.question_splitter import split_questions

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def _read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def _make_blocks(text: str, page: int = 1, block_index: int = 0) -> list[dict]:
    return [{"page": page, "block_index": block_index, "normalized_text": text}]


def _q(text: str) -> list[dict]:
    """快捷方式：文本 → split_questions → raw_questions。"""
    return split_questions(_make_blocks(text))


# ---------------------------------------------------------------
# 1. INLINE 答案提取
# ---------------------------------------------------------------

class TestInlineAnswer:
    def test_chinese_answer_label(self):
        r = _extract_inline_answer("答案：A")
        assert r == {"answer": "A", "raw": "答案：A"}

    def test_bracket_answer_label(self):
        r = _extract_inline_answer("【答案】B")
        assert r == {"answer": "B", "raw": "【答案】B"}

    def test_reference_answer(self):
        r = _extract_inline_answer("参考答案：C")
        assert r == {"answer": "C", "raw": "参考答案：C"}

    def test_correct_answer(self):
        r = _extract_inline_answer("正确答案：D")
        assert r == {"answer": "D", "raw": "正确答案：D"}

    def test_key_answer(self):
        r = _extract_inline_answer("KEY: A")
        assert r == {"answer": "A", "raw": "KEY: A"}

    def test_answer_lowercase(self):
        r = _extract_inline_answer("答案：b")
        assert r == {"answer": "B", "raw": "答案：b"}

    def test_answer_with_colon_variants(self):
        r1 = _extract_inline_answer("答案：A")
        r2 = _extract_inline_answer("答案: A")
        assert r1["answer"] == "A"
        assert r2["answer"] == "A"

    def test_no_answer_in_text(self):
        assert _extract_inline_answer("这是普通题目文本") is None
        assert _extract_inline_answer("A. 选项不是答案") is None


# ---------------------------------------------------------------
# 2. INLINE 解析提取
# ---------------------------------------------------------------

class TestInlineExplanation:
    def test_chinese_explanation(self):
        r = _extract_inline_explanation("解析：对 x^2 求导得 2x")
        assert r["explanation"] == "对 x^2 求导得 2x"
        assert r["raw"] == "解析：对 x^2 求导得 2x"

    def test_bracket_explanation(self):
        r = _extract_inline_explanation("【解析】单位矩阵行列式为 1")
        assert r["explanation"] == "单位矩阵行列式为 1"

    def test_solution_label(self):
        r = _extract_inline_explanation("解答：e^0 = 1")
        assert r["explanation"] == "e^0 = 1"

    def test_analysis_label(self):
        r = _extract_inline_explanation("分析：迹 = 1 + 4 = 5")
        assert r["explanation"] == "迹 = 1 + 4 = 5"

    def test_english_explanation(self):
        r = _extract_inline_explanation("Explanation: important limit")
        assert r["explanation"] == "important limit"

    def test_no_explanation(self):
        assert _extract_inline_explanation("普通文本") is None


# ---------------------------------------------------------------
# 3. 完整 INLINE 文档
# ---------------------------------------------------------------

class TestFullInlineDocument:
    def test_all_five_matched(self):
        text = _read_fixture("matcher_inline.txt")
        questions = _q(text)
        result = match_answers(questions, _make_blocks(text))

        assert len(result["matched"]) == 5
        assert len(result["unmatched"]) == 0

    def test_answers_correct(self):
        text = _read_fixture("matcher_inline.txt")
        questions = _q(text)
        result = match_answers(questions, _make_blocks(text))

        expected = ["A", "B", "B", "B", "C"]
        for i, q in enumerate(result["matched"]):
            assert q["answer"] == expected[i], f"Q{i + 1} expected {expected[i]}"
            assert q["answer_source"] == "explicit_text", f"Q{i + 1} answer_source"

    def test_explanations_extracted(self):
        text = _read_fixture("matcher_inline.txt")
        questions = _q(text)
        result = match_answers(questions, _make_blocks(text))

        for q in result["matched"]:
            assert q["explanation"] is not None
            assert len(q["explanation"]) > 0
            assert q["explanation_source"] == "inline"


# ---------------------------------------------------------------
# 4. SEPARATED 答案匹配
# ---------------------------------------------------------------

class TestSeparatedAnswer:
    def test_number_based_matching(self):
        questions = _q(_read_fixture("matcher_separated.txt"))
        # 答案区域在第 2 页
        answer_blocks = _make_blocks(
            "1. A\n2. B\n3. A", page=2
        )
        all_blocks = _make_blocks(_read_fixture("matcher_separated.txt"), page=1) + answer_blocks

        result = match_answers(questions, all_blocks, {
            "mode": "SEPARATED",
            "answer_pages": [2],
        })

        assert len(result["matched"]) == 3
        assert [q["answer"] for q in result["matched"]] == ["A", "B", "A"]

    def test_chinese_comma_separator(self):
        questions = _q("1. 题目A\nA. xx\nB. yy\n2. 题目B\nA. zz")
        answer_blocks = _make_blocks("1、B\n2、A", page=2)
        all_blocks = _make_blocks("1. 题目A\nA. xx\nB. yy\n2. 题目B\nA. zz", page=1) + answer_blocks

        result = match_answers(questions, all_blocks, {
            "mode": "SEPARATED", "answer_pages": [2],
        })
        assert [q["answer"] for q in result["matched"]] == ["B", "A"]

    def test_answer_with_label(self):
        questions = _q("1. 题目A\nA. x\n2. 题目B\nA. y")
        answer_blocks = _make_blocks("1. 答案：A\n2. 答案：B", page=2)
        all_blocks = _make_blocks("1. 题目A\nA. x\n2. 题目B\nA. y", page=1) + answer_blocks

        result = match_answers(questions, all_blocks, {
            "mode": "SEPARATED", "answer_pages": [2],
        })
        assert [q["answer"] for q in result["matched"]] == ["A", "B"]

    def test_sequential_fallback(self):
        """答案区只有字母，按顺序匹配。"""
        questions = _q("1. Q1\nA. a\n2. Q2\nA. b\n3. Q3\nA. c")
        answer_blocks = _make_blocks("1. C\n2. D\n3. A", page=2)
        all_blocks = _make_blocks("1. Q1\nA. a\n2. Q2\nA. b\n3. Q3\nA. c", page=1) + answer_blocks

        result = match_answers(questions, all_blocks, {
            "mode": "SEPARATED", "answer_pages": [2],
        })
        assert [q["answer"] for q in result["matched"]] == ["C", "D", "A"]

    def test_cross_page_answer(self):
        """答案在多个页面。"""
        questions = _q("1. Q1\nA. a\n2. Q2\nA. b\n3. Q3\nA. c")
        blocks = [
            {"page": 1, "block_index": 0, "normalized_text": "1. Q1\nA. a\n2. Q2\nA. b\n3. Q3\nA. c"},
            {"page": 4, "block_index": 1, "normalized_text": "1. A"},
            {"page": 5, "block_index": 2, "normalized_text": "2. B\n3. C"},
        ]
        result = match_answers(questions, blocks, {
            "mode": "SEPARATED", "answer_pages": [4, 5],
        })
        assert [q["answer"] for q in result["matched"]] == ["A", "B", "C"]


# ---------------------------------------------------------------
# 5. SEPARATED 解析提取
# ---------------------------------------------------------------

class TestSeparatedExplanation:
    def test_explanation_by_number(self):
        questions = _q("1. Q1\nA. a\n2. Q2\nA. b")
        expl_blocks = _make_blocks(
            "1. 解析：对 x^2 求导得 2x\n"
            "2. 解析：单位矩阵行列式为 1",
            page=2,
        )
        all_blocks = _make_blocks("1. Q1\nA. a\n2. Q2\nA. b", page=1) + expl_blocks

        result = match_answers(questions, all_blocks, {
            "mode": "SEPARATED",
            "explanation_pages": [2],
        })
        assert result["matched"][0]["explanation"] == "对 x^2 求导得 2x"
        assert result["matched"][1]["explanation"] == "单位矩阵行列式为 1"

    def test_explanation_weak_match(self):
        """无显式解析标签时，弱匹配题号后的内容。"""
        questions = _q("1. Q1\nA. a")
        expl_blocks = _make_blocks("1. 这是解析内容", page=2)
        all_blocks = _make_blocks("1. Q1\nA. a", page=1) + expl_blocks

        result = match_answers(questions, all_blocks, {
            "mode": "SEPARATED",
            "explanation_pages": [2],
        })
        assert result["matched"][0]["explanation"] is not None
        assert result["matched"][0]["explanation_source"] == "separated"


# ---------------------------------------------------------------
# 6. 缺失处理
# ---------------------------------------------------------------

class TestMissing:
    def test_missing_answer(self):
        text = _read_fixture("matcher_missing.txt")
        questions = _q(text)
        result = match_answers(questions, _make_blocks(text))

        # Q2 无答案，应标记
        assert result["matched"][1]["answer"] is None
        assert result["matched"][1]["answer_source"] == "missing"

    def test_missing_in_unmatched(self):
        text = _read_fixture("matcher_missing.txt")
        questions = _q(text)
        result = match_answers(questions, _make_blocks(text))

        unmatched_nums = [u["question_number"] for u in result["unmatched"]]
        assert 2 in unmatched_nums

    def test_partial_missing_does_not_crash(self):
        text = _read_fixture("matcher_missing.txt")
        questions = _q(text)
        result = match_answers(questions, _make_blocks(text))
        # Q1 和 Q3 有答案
        assert result["matched"][0]["answer"] == "A"
        assert result["matched"][2]["answer"] == "A"

    def test_all_missing(self):
        questions = _q("1. Q1\nA. a\n2. Q2\nA. b")
        result = match_answers(questions, _make_blocks("1. Q1\nA. a\n2. Q2\nA. b"))

        assert len(result["unmatched"]) == 2
        for q in result["matched"]:
            assert q["answer"] is None
            assert q["answer_source"] == "missing"


# ---------------------------------------------------------------
# 7. OCR 容错
# ---------------------------------------------------------------

class TestOcrTolerance:
    def test_8_to_B_inline(self):
        r = _extract_inline_answer("答案：8")
        assert r["answer"] == "B"

    def test_0_to_D_inline(self):
        r = _extract_inline_answer("【答案】0")
        assert r["answer"] == "D"

    def test_8_to_B_separated(self):
        questions = _q("1. Q1\nA. a\n2. Q2\nA. b")
        answer_blocks = _make_blocks("1. 8\n2. 0", page=2)
        all_blocks = _make_blocks("1. Q1\nA. a\n2. Q2\nA. b", page=1) + answer_blocks

        result = match_answers(questions, all_blocks, {
            "mode": "SEPARATED", "answer_pages": [2],
        })
        assert result["matched"][0]["answer"] == "B"
        assert result["matched"][1]["answer"] == "D"

    def test_lowercase_answer(self):
        r = _extract_inline_answer("答案：a")
        assert r["answer"] == "A"


# ---------------------------------------------------------------
# 8. 低阶函数
# ---------------------------------------------------------------

class TestLowLevelFunctions:
    def test_correct_answer_letter(self):
        assert _correct_answer_letter("8") == "B"
        assert _correct_answer_letter("6") == "B"
        assert _correct_answer_letter("0") == "D"
        assert _correct_answer_letter("A") == "A"
        assert _correct_answer_letter("b") == "B"

    def test_clean_explanation(self):
        assert _clean_explanation("解析：内容") == "内容"
        assert _clean_explanation("【解析】内容") == "内容"
        assert _clean_explanation("解答：内容") == "内容"

    def test_extract_all_separated_answers(self):
        text = "1. A\n2. B\n3. C\n4. D"
        result = _extract_all_separated_answers(text)
        assert len(result) == 4
        assert result[0] == {"number": 1, "answer": "A", "raw": "1. A"}

    def test_extract_all_separated_dedup(self):
        """重复题号去重。"""
        text = "1. A\n1. B\n2. C"
        result = _extract_all_separated_answers(text)
        assert len(result) == 2


# ---------------------------------------------------------------
# 9. 空输入 / 边界情况
# ---------------------------------------------------------------

class TestEdgeCases:
    def test_empty_questions(self):
        result = match_answers([], [], {})
        assert result == {"matched": [], "unmatched": []}

    def test_no_structure(self):
        questions = _q("1. Q1\n答案：A\n2. Q2\nA. a")
        result = match_answers(questions, _make_blocks("1. Q1\n答案：A\n2. Q2\nA. a"))
        assert len(result["matched"]) == 2
        # Q1 内联提取到答案
        assert result["matched"][0]["answer"] == "A"

    def test_structure_none(self):
        questions = _q("1. Q1\n答案：B")
        result = match_answers(questions, _make_blocks("1. Q1\n答案：B"), None)
        assert result["matched"][0]["answer"] == "B"

    def test_confidence_range(self):
        questions = _q("1. Q1\n答案：A\n解析：内容")
        result = match_answers(questions, _make_blocks("1. Q1\n答案：A\n解析：内容"))
        for q in result["matched"]:
            assert 0.0 <= q["confidence"] <= 1.0

    def test_answer_source_separated(self):
        questions = _q("1. Q1\nA. a")
        answer_blocks = _make_blocks("1. A", page=2)
        all_blocks = _make_blocks("1. Q1\nA. a", page=1) + answer_blocks
        result = match_answers(questions, all_blocks, {
            "mode": "SEPARATED", "answer_pages": [2],
        })
        assert result["matched"][0]["answer_source"] == "separated"

    def test_raw_answer_text_preserved(self):
        questions = _q("1. Q1\n答案：B")
        result = match_answers(questions, _make_blocks("1. Q1\n答案：B"))
        # Leading newline may be included in source_span due to regex \s prefix
        assert result["matched"][0]["raw_answer_text"].strip() == "答案：B"

    def test_raw_explanation_text_preserved(self):
        questions = _q("1. Q1\n解析：内容")
        result = match_answers(questions, _make_blocks("1. Q1\n解析：内容"))
        assert "解析：内容" in result["matched"][0]["raw_explanation_text"]


# ---------------------------------------------------------------
# 10. _extract_separated_answer / _extract_separated_explanation 单元
# ---------------------------------------------------------------

class TestSeparatedUnitFunctions:
    def test_answer_direct_match(self):
        blocks = _make_blocks("1. A\n2. B\n3. C", page=2)
        r = _extract_separated_answer(blocks, [2], 2, 1)
        assert r["answer"] == "B"
        assert r["exact_match"] is True

    def test_answer_not_found(self):
        blocks = _make_blocks("1. A\n2. B", page=2)
        r = _extract_separated_answer(blocks, [2], 99, 0)
        assert r is None

    def test_explanation_direct_match(self):
        blocks = _make_blocks("1. 解析：求导得 2x\n2. 解析：结果", page=3)
        r = _extract_separated_explanation(blocks, [3], 1)
        assert r["explanation"] == "求导得 2x"
        assert r["exact_match"] is True

    def test_explanation_not_found(self):
        blocks = _make_blocks("其他内容", page=3)
        r = _extract_separated_explanation(blocks, [3], 1)
        assert r is None

    def test_empty_pages(self):
        r = _extract_separated_answer([], [], 1)
        assert r is None
