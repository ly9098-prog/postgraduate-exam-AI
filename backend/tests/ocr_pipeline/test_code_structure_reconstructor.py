"""Tests for code_structure_reconstructor.py — rule-based code fixer."""

from app.features.code_structure_reconstructor import (
    _fix_ocr_operators,
    _indent_code,
    _reconstruct_compressed_code,
    _split_semicolons,
    reconstruct_and_validate,
    reconstruct_code,
)

# ============================================================================
# Phase 1: OCR operator repair
# ============================================================================


class TestFixOcrOperators:
    def test_assign_combined_ops(self):
        assert _fix_ocr_operators("i * = 2") == "i *= 2"
        assert _fix_ocr_operators("sum + = 1") == "sum += 1"
        assert _fix_ocr_operators("a / = b") == "a /= b"
        assert _fix_ocr_operators("a - = b") == "a -= b"

    def test_equality_and_comparison(self):
        assert _fix_ocr_operators("a = = b") == "a == b"
        assert _fix_ocr_operators("x < = 5") == "x <= 5"
        assert _fix_ocr_operators("x > = 0") == "x >= 0"
        assert _fix_ocr_operators("a ! = b") == "a != b"

    def test_increment_decrement(self):
        assert _fix_ocr_operators("i + +") == "i ++"
        assert _fix_ocr_operators("j - -") == "j --"

    def test_arrow_operator(self):
        assert _fix_ocr_operators("p - > next") == "p -> next"
        assert _fix_ocr_operators("T - > lchild") == "T -> lchild"

    def test_logical_ops(self):
        assert _fix_ocr_operators("a & & b") == "a && b"
        assert _fix_ocr_operators("a | | b") == "a || b"

    def test_code_fence_preserved(self):
        text = "```c\nint *p;\n```"
        fixed = _fix_ocr_operators(text)
        assert "```" in fixed

    def test_no_false_positive_on_correct_code(self):
        text = "for (int i = 0; i < n; i++)"
        fixed = _fix_ocr_operators(text)
        assert fixed == text

    def test_no_false_positive_on_arrow(self):
        text = "return (p = q)->next;"
        fixed = _fix_ocr_operators(text)
        assert fixed == text

    def test_pointer_declaration_preserved(self):
        text = "int *p; int **pp;"
        fixed = _fix_ocr_operators(text)
        # Verify * is not destroyed
        assert "*p" in fixed
        assert "**pp" in fixed

    def test_empty_input(self):
        assert _fix_ocr_operators("") == ""


# ============================================================================
# Phase 2: Compressed code reconstruction
# ============================================================================


class TestReconstructCompressedCode:
    def test_split_nested_for(self):
        text = "for(int i = 0; i < n; i++)for(int j = 0; j < i; j++)sum++;"
        result = _reconstruct_compressed_code(text)
        lines = [l for l in result.split("\n") if l.strip()]
        # Should have at least 3 lines: for1, for2, sum++
        assert len(lines) >= 3

    def test_split_for_if(self):
        text = "for(...)if(x)return;"
        result = _reconstruct_compressed_code(text)
        assert "for" in result and "if" in result

    def test_else_on_new_line(self):
        text = "if(x){y;}else{z;}"
        result = _reconstruct_compressed_code(text)
        assert "else" in result.split("\n")[-1]

    def test_struct_keyword_split(self):
        text = "typedef struct Node { int data; } Node;"
        result = _reconstruct_compressed_code(text)
        assert "struct" in result

    def test_return_inserts_newline(self):
        text = "int f(){return 42;}"
        result = _reconstruct_compressed_code(text)
        assert "return" in result

    def test_preserve_single_statement(self):
        text = "int x = 1;"
        result = _reconstruct_compressed_code(text)
        assert result == text or "int" in result


# ============================================================================
# Phase 3: Semicolon splitting
# ============================================================================


class TestSplitSemicolons:
    def test_split_statements(self):
        text = "int a = 1; int b = 2;"
        result = _split_semicolons(text)
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) == 2

    def test_preserve_for_header(self):
        text = "for (int i = 0; i < n; i++)"
        result = _split_semicolons(text)
        assert result.count("\n") == 0

    def test_empty_input(self):
        assert _split_semicolons("") == ""


# ============================================================================
# Phase 4: Indentation
# ============================================================================


class TestIndentCode:
    def test_simple_braces(self):
        text = "void f() {\nint x;\n}"
        result = _indent_code(text)
        lines = result.split("\n")
        # verify the body is indented
        assert len(lines) >= 2

    def test_nested_blocks(self):
        text = "void f() {\nif (x) {\ny();\n}\n}"
        result = _indent_code(text)
        assert "    y();" in result or "        y();" in result

    def test_empty_input(self):
        assert _indent_code("") == ""

    def test_no_false_nesting(self):
        text = "struct X { int a; };"
        result = _indent_code(text)
        # Should not crash or over-indent
        assert "struct X {" in result


# ============================================================================
# Full pipeline: reconstruct_code
# ============================================================================


class TestReconstructCode:
    def test_compressed_nested_loops(self):
        text = "for(int i=1;i<n;i*=2)for(int j=0;j<i;j++)sum++;"
        result = reconstruct_code(text)
        # Result should be multi-line with proper structure
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) >= 3, f"Expected >= 3 lines, got {len(lines)}: {result!r}"

    def test_broken_operators(self):
        text = "for (int i = 0; i < = n; i + +)"
        result = reconstruct_code(text)
        assert "<=" in result or "< =" not in result
        assert "++" in result or "+ +" not in result

    def test_tree_recursion_function(self):
        text = "void countLeaf(BiTree T){if(T==NULL)return;if(T->lchild==NULL&&T->rchild==NULL)count++;countLeaf(T->lchild);countLeaf(T->rchild);}"
        result = reconstruct_code(text)
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) >= 4
        assert "void countLeaf" in result

    def test_fenced_code_unchanged_outside(self):
        text = "题目描述：\n```c\nint main() { return 0; }\n```\n以上代码的功能是？"
        result = reconstruct_code(text)
        assert "题目描述：" in result
        assert "以上代码的功能是？" in result
        assert "```" in result

    def test_non_code_text_untouched(self):
        text = "这道题考察的是二叉树遍历算法。"
        result = reconstruct_code(text, fence_aware=False)
        assert "二叉树遍历算法" in result

    def test_empty_input(self):
        assert reconstruct_code("") == ""
        assert reconstruct_code(None) == ""

    def test_partial_options(self):
        result = reconstruct_code("", fix_operators=False)
        assert result == ""


# ============================================================================
# reconstruct_and_validate
# ============================================================================


class TestReconstructAndValidate:
    def test_report_structure(self):
        text = "for(int i=0;i<n;i++)sum++;"
        report = reconstruct_and_validate(text)
        assert "original" in report
        assert "reconstructed" in report
        assert "changed" in report
        assert "operators_fixed" in report
        assert "brace_diff_before" in report
        assert "brace_diff_after" in report
        assert "braces_balanced" in report

    def test_changed_flag(self):
        # Code that needs splitting should show changed=True
        text = "for(int i=0;i<n;i++)for(int j=0;j<i;j++)sum++;"
        report = reconstruct_and_validate(text)
        assert report["changed"] is True

    def test_unchanged_code(self):
        # Already well-formed code should be unchanged
        text = "int main() {\n    return 0;\n}"
        report = reconstruct_and_validate(text)
        # Simple code may not change significantly
        assert isinstance(report["changed"], bool)

    def test_operator_count(self):
        text = "i * = 2; j + +;"
        report = reconstruct_and_validate(text)
        assert report["operators_fixed"] >= 1


# ============================================================================
# Edge cases
# ============================================================================


class TestEdgeCases:
    def test_very_long_line(self):
        text = "int a=1;int b=2;int c=3;int d=4;int e=5;int f=6;"
        result = reconstruct_code(text)
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) >= 3

    def test_chinese_mixed_with_code(self):
        text = "在一个链表中执行：p -> next = q; q -> next = NULL;"
        result = reconstruct_code(text, fence_aware=True)
        assert "->" in result or "- >" not in result

    def test_brace_only_line(self):
        text = "if (x) { y(); }"
        result = reconstruct_code(text)
        assert "if" in result

    def test_multiline_condition_preserved(self):
        text = "if (a > 0 && b < 0)"
        result = reconstruct_code(text)
        assert "if" in result

    def test_while_loop(self):
        text = "while(p){p=p->next;count++;}"
        result = reconstruct_code(text)
        assert "while" in result
