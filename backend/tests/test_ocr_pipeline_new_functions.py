"""Unit tests for newly added OCR pipeline functions.

Covers:
- extract_options_robust (question_splitter)
- reconstruct_code_block / fix_braces (code_integrity)
- filter_isolated_tokens (question_normalizer)
- merge_pointer_lines / remove_single_letter_noise (text_normalizer)
- classify_line / fix_tree_recursion_breaks (code_integrity)
- normalize_output (question_normalizer)
- should_send_to_llm (repair_stage)
"""

from app.features.code_integrity import (
    classify_line,
    fix_braces,
    fix_tree_recursion_breaks,
    reconstruct_code_block,
)
from app.features.pipeline_stages.repair_stage import should_send_to_llm
from app.features.question_normalizer import (
    QT_MULTIPLE_CHOICE,
    QT_SINGLE_CHOICE,
    filter_isolated_tokens,
    normalize_output,
)
from app.features.text_normalizer import (
    merge_pointer_lines,
    remove_single_letter_noise,
)

# =========================================================================
# reconstruct_code_block
# =========================================================================

class TestReconstructCodeBlock:
    """TASK 2: Code block reconstruction from truncated lines."""

    def test_simple_for_loop(self):
        lines = ["    for (i = 0; i < n; i++) {", "        sum += i;", "    }", "extra text"]
        result = reconstruct_code_block(lines)
        assert "for" in result
        assert "sum += i" in result
        assert "extra text" not in result  # stops after balanced braces

    def test_while_loop(self):
        lines = ["    while (p != NULL) {", "        p = p->next;", "    }", "下一行"]
        result = reconstruct_code_block(lines)
        assert "while" in result
        assert "p->next" in result

    def test_if_statement(self):
        lines = ["    if (x > 0) {", "        return x;", "    }", "after"]
        result = reconstruct_code_block(lines)
        assert "if (x > 0)" in result
        assert "return x" in result
        assert "after" not in result

    def test_struct_definition(self):
        lines = ["typedef struct LNode {", "    int data;", "    struct LNode *next;", "} LNode;"]
        result = reconstruct_code_block(lines)
        assert "typedef struct" in result
        assert "LNode *next" in result

    def test_stops_at_blank_line(self):
        lines = ["for (i = 0; i < n; i++) {", "    do_work();", "", "next thing"]
        result = reconstruct_code_block(lines)
        assert "do_work" in result
        assert "next thing" not in result

    def test_stops_at_question_boundary(self):
        lines = ["    for (i = 0; i < n; i++)", "1. 下一题"]
        result = reconstruct_code_block(lines)
        # Should capture the for line but stop before question number
        assert "for (i" in result
        assert "下一题" not in result

    def test_no_code_signal(self):
        lines = ["这是一行普通文本", "这是另一行"]
        result = reconstruct_code_block(lines)
        assert result == ""  # no code signal detected

    def test_empty_lines(self):
        assert reconstruct_code_block([]) == ""


class TestFixBraces:
    """TASK 2: Brace balancing fix."""

    def test_no_fix_high_confidence(self):
        code = "int f() { return 1; }"
        assert fix_braces(code, confidence=0.9) == code

    def test_auto_close_low_confidence(self):
        code = "int f() {\n    return 1;"
        result = fix_braces(code, confidence=0.5)
        assert result.count("{") == result.count("}")

    def test_balanced_stays_same(self):
        code = "int f() {\n    return 1;\n}"
        result = fix_braces(code, confidence=0.5)
        assert result == code

    def test_empty_code(self):
        assert fix_braces("", confidence=0.5) == ""

    def test_confidence_boundary(self):
        code = "int f() {"
        # At 0.8, should NOT fix
        assert fix_braces(code, confidence=0.8) == code
        # Below 0.8, should fix
        result = fix_braces(code, confidence=0.79)
        assert result.count("}") == 1


# =========================================================================
# filter_isolated_tokens
# =========================================================================

class TestFilterIsolatedTokens:
    """TASK 3: Remove isolated noise tokens from stem."""

    def test_removes_isolated_c_at_end(self):
        stem = "下面说法正确的是\nC"
        result = filter_isolated_tokens(stem)
        assert "C" not in result

    def test_removes_isolated_b_standalone_line(self):
        stem = "以下选项错误的是\nB"
        result = filter_isolated_tokens(stem)
        assert "B" not in result

    def test_keeps_options_when_context_provided(self):
        stem = "下列说法正确的是"
        context = {"has_options": True, "option_lines": {"A": "opt1", "B": "opt2"}}
        result = filter_isolated_tokens(stem, context)
        assert result == stem  # unchanged

    def test_does_not_remove_inside_words(self):
        stem = "BEAD, CAB, DAB"
        result = filter_isolated_tokens(stem)
        # These are part of words, not isolated
        assert "BEAD" in result

    def test_empty_text(self):
        assert filter_isolated_tokens("") == ""

    def test_keeps_normal_text(self):
        stem = "下列关于线性表的说法正确的是"
        result = filter_isolated_tokens(stem)
        assert result == stem


# =========================================================================
# merge_pointer_lines
# =========================================================================

class TestMergePointerLines:
    """TASK 4: Merge lines broken at pointer operators."""

    def test_merge_arrow_break(self):
        lines = ["p->", "next = NULL;"]
        result = merge_pointer_lines(lines)
        assert len(result) == 1
        assert "p-> next" in result[0]

    def test_merge_double_ampersand(self):
        lines = ["if (p != NULL &&", " q != NULL) {"]
        result = merge_pointer_lines(lines)
        assert len(result) == 1
        assert "&& q" in result[0]

    def test_merge_double_pipe(self):
        lines = ["if (a == 0 ||", " b == 1) {"]
        result = merge_pointer_lines(lines)
        assert len(result) == 1
        assert "|| b " in result[0]

    def test_merge_open_paren(self):
        lines = ["func(", "a, b, c);"]
        result = merge_pointer_lines(lines)
        assert len(result) == 1
        assert "func( a," in result[0]

    def test_no_merge_normal_lines(self):
        lines = ["int a = 1;", "int b = 2;"]
        result = merge_pointer_lines(lines)
        assert len(result) == 2

    def test_no_merge_at_question_boundary(self):
        lines = ["for (i = 0; i < n;", "1. 下一题"]
        result = merge_pointer_lines(lines)
        # Should not merge past a question number
        assert len(result) == 2

    def test_empty_lines(self):
        assert merge_pointer_lines([]) == []

    def test_consecutive_merges(self):
        lines = ["p->", "next->", "prev = NULL;"]
        result = merge_pointer_lines(lines)
        assert len(result) == 1
        assert "p-> next-> prev" in result[0]


# =========================================================================
# remove_single_letter_noise
# =========================================================================

class TestRemoveSingleLetterNoise:
    """TASK 9: Remove standalone single-letter tokens."""

    def test_removes_isolated_c(self):
        tokens = ["下列", "说法", "正确", "的", "是", "C"]
        result = remove_single_letter_noise(tokens)
        assert "C" not in result

    def test_keeps_letters_in_option_context(self):
        tokens = ["A", ".", "选项一"]
        result = remove_single_letter_noise(tokens)
        assert "A" in result  # kept because followed by "."

    def test_keeps_normal_words(self):
        tokens = ["BEAD", "CAB", "DAB"]
        result = remove_single_letter_noise(tokens)
        assert result == tokens

    def test_removes_isolated_b(self):
        tokens = ["x", "B", "y"]
        result = remove_single_letter_noise(tokens)
        assert "B" not in result

    def test_empty_tokens(self):
        assert remove_single_letter_noise([]) == []

    def test_keeps_all_when_no_noise(self):
        tokens = ["hello", "world"]
        result = remove_single_letter_noise(tokens)
        assert result == tokens


# =========================================================================
# classify_line
# =========================================================================

class TestClassifyLine:
    """TASK 5: Classify line as code or text."""

    def test_code_with_braces(self):
        assert classify_line("int main() {") == "code"

    def test_code_with_pointer(self):
        assert classify_line("p->next = NULL;") == "code"

    def test_code_with_struct(self):
        assert classify_line("typedef struct LNode {") == "code"

    def test_code_with_for(self):
        assert classify_line("for (i = 0; i < n; i++) {") == "code"

    def test_text_chinese(self):
        assert classify_line("下列说法正确的是") == "text"

    def test_text_sentence(self):
        assert classify_line("线性表是具有相同数据类型的 n 个数据元素的有限序列。") == "text"

    def test_text_question(self):
        assert classify_line("下列选项中错误的是？") == "text"

    def test_empty_line(self):
        assert classify_line("") == "text"
        assert classify_line("  ") == "text"

    def test_code_with_return(self):
        assert classify_line("return result;") == "code"

    def test_code_with_malloc(self):
        assert classify_line("L = (LinkList)malloc(sizeof(LNode));") == "code"

    def test_short_junk(self):
        # Random short text with no code signals
        assert classify_line("abc xyz") == "text"


# =========================================================================
# fix_tree_recursion_breaks
# =========================================================================

class TestFixTreeRecursionBreaks:
    """TASK 6: Fix fragmented tree recursion code."""

    def test_fix_if_lchild_null(self):
        text = "if (T->lchild == NULL\n&& T->rchild == NULL)"
        result = fix_tree_recursion_breaks(text)
        assert "lchild" in result
        assert "rchild" in result
        # Both conditions should be on the same logical line
        assert result.count("(") == result.count(")")

    def test_fix_consecutive_conditions(self):
        text = "if (p->next != NULL\n&& p->data > 0) {"
        result = fix_tree_recursion_breaks(text)
        assert "NULL &&" in result or "NULL\n&&" not in result

    def test_no_fix_simple_code(self):
        text = "int x = 1;"
        result = fix_tree_recursion_breaks(text)
        assert result == text

    def test_empty_text(self):
        assert fix_tree_recursion_breaks("") == ""

    def test_fix_while_next_not_null(self):
        text = "while (p->next != NULL\n&& p->data != key) {"
        result = fix_tree_recursion_breaks(text)
        assert "NULL" in result
        assert "key" in result



# =========================================================================
# normalize_output
# =========================================================================

class TestNormalizeOutput:
    """TASK 10: Final schema enforcement."""

    def test_basic_schema(self):
        question = {
            "stem": "下列说法正确的是",
            "options": [{"key": "A", "text": "一"}, {"key": "B", "text": "二"}],
            "answer": "A",
            "analysis": "因为...",
        }
        result = normalize_output(question)
        assert result["stem"] == "下列说法正确的是"
        assert result["code_blocks"] == []
        assert len(result["options"]) >= 2
        assert result["answer"] == "A"
        assert result["analysis"] == "因为..."

    def test_missing_fields_filled(self):
        question = {}
        result = normalize_output(question)
        assert result["stem"] == ""
        assert result["code_blocks"] == []
        assert result["answer"] == ""
        assert result["analysis"] == ""

    def test_single_choice_no_padding(self):
        question = {
            "question_type": QT_SINGLE_CHOICE,
            "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}],
        }
        result = normalize_output(question)
        # Layer 0/3: No padding. Only the options provided are kept.
        assert len(result["options"]) == 2
        keys = [o["key"] for o in result["options"]]
        assert keys == ["A", "B"]

    def test_multiple_choice_not_padded(self):
        question = {
            "question_type": QT_MULTIPLE_CHOICE,
            "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}, {"key": "C", "text": "z"}],
        }
        result = normalize_output(question)
        assert len(result["options"]) == 3  # not padded

    def test_preserves_extra_keys(self):
        question = {
            "stem": "test",
            "question_type": QT_SINGLE_CHOICE,
            "confidence_score": 0.85,
            "is_valid": True,
            "schema_version": "v1",
        }
        result = normalize_output(question)
        assert result["confidence_score"] == 0.85
        assert result["is_valid"] is True

    def test_code_blocks_extracted(self):
        question = {
            "stem": "代码:\n```c\nint x = 1;\n```\n问输出",
            "options": [{"key": "A", "text": "1"}],
        }
        result = normalize_output(question)
        assert len(result["code_blocks"]) == 1
        assert "int x = 1;" in result["code_blocks"][0]


# =========================================================================
# should_send_to_llm
# =========================================================================

class TestShouldSendToLlm:
    """TASK 8: Pre-filter gate for LLM repair."""

    def test_high_score_allows_llm(self):
        assert should_send_to_llm(0.9) is True
        assert should_send_to_llm(0.7) is True
        assert should_send_to_llm(0.6) is True

    def test_low_score_blocks_llm(self):
        assert should_send_to_llm(0.59) is False
        assert should_send_to_llm(0.3) is False
        assert should_send_to_llm(0.0) is False

    def test_boundary_exact(self):
        assert should_send_to_llm(0.6) is True
        assert should_send_to_llm(0.599) is False
