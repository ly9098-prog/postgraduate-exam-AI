"""公式归一化纯函数兼容基线。

覆盖 formula_normalizer 中可独立测试的纯规则：
- fix_ocr_formula：OCR 公式修复
- is_math_subject：数学学科判断
- safe_fix_ocr_formula：安全公式修复（非数学学科透传）
- normalize_text_import_math：文本导入数学归一化
- parse_latex_table：LaTeX 表格解析
- extract_tables_from_text：表格提取替换
"""

from __future__ import annotations

from app.services.formula_normalizer import (
    extract_tables_from_text,
    fix_ocr_formula,
    is_math_subject,
    normalize_text_import_math,
    parse_latex_table,
    safe_fix_ocr_formula,
)


class TestFixOcrFormula:
    """fix_ocr_formula 保守修复 OCR 公式错误。"""

    def test_empty_returns_empty(self) -> None:
        assert fix_ocr_formula("") == ""

    def test_bare_superscript(self) -> None:
        assert fix_ocr_formula("x2") == "x^{2}"

    def test_fraction(self) -> None:
        assert fix_ocr_formula("1/2") == "\\frac{1}{2}"

    def test_sqrt_paren(self) -> None:
        assert fix_ocr_formula("\\sqrt(x)") == "\\sqrt{x}"

    def test_preserves_correct_latex(self) -> None:
        result = fix_ocr_formula("\\frac{1}{2}")
        assert result == "\\frac{1}{2}"


class TestIsMathSubject:
    """is_math_subject 判断学科是否为数学类。"""

    def test_none_returns_false(self) -> None:
        assert is_math_subject(None) is False

    def test_empty_returns_false(self) -> None:
        assert is_math_subject("") is False

    def test_math(self) -> None:
        assert is_math_subject("math") is True

    def test_math2(self) -> None:
        assert is_math_subject("math2") is True

    def test_chinese_math(self) -> None:
        assert is_math_subject("数学") is True

    def test_chinese_gaoshu(self) -> None:
        assert is_math_subject("高数") is True

    def test_english_returns_false(self) -> None:
        assert is_math_subject("english") is False

    def test_exam408_returns_false(self) -> None:
        assert is_math_subject("exam408") is False

    def test_dash_normalized(self) -> None:
        assert is_math_subject("math-2") is True

    def test_underscore_normalized(self) -> None:
        assert is_math_subject("math_2") is True


class TestSafeFixOcrFormula:
    """safe_fix_ocr_formula 仅在数学学科时启用修复。"""

    def test_math_subject_fixes(self) -> None:
        assert safe_fix_ocr_formula("x2", "math") == "x^{2}"

    def test_non_math_subject_passthrough(self) -> None:
        assert safe_fix_ocr_formula("x2", "english") == "x2"

    def test_none_subject_fixes(self) -> None:
        assert safe_fix_ocr_formula("x2", None) == "x^{2}"

    def test_exam408_passthrough(self) -> None:
        assert safe_fix_ocr_formula("1/2", "exam408") == "1/2"


class TestNormalizeTextImportMath:
    """normalize_text_import_math 归一化文本导入数学公式。"""

    def test_empty_returns_empty(self) -> None:
        assert normalize_text_import_math("") == ""

    def test_preserves_dollar_math(self) -> None:
        assert normalize_text_import_math("$x$") == "$x$"

    def test_preserves_display_math(self) -> None:
        assert normalize_text_import_math("$$x^2$$") == "$$x^2$$"


class TestParseLatexTable:
    """parse_latex_table 解析 LaTeX tabular 表格。"""

    def test_no_table_returns_empty(self) -> None:
        assert parse_latex_table("no table here") == []

    def test_simple_table(self) -> None:
        table = r"\begin{tabular}{ll} a & b \\ c & d \end{tabular}"
        result = parse_latex_table(table)
        assert len(result) == 1
        assert result[0]["columns"] == 2
        assert result[0]["rows"] == [["a", "b"], ["c", "d"]]

    def test_three_columns(self) -> None:
        table = r"\begin{tabular}{lll} a & b & c \end{tabular}"
        result = parse_latex_table(table)
        assert len(result) == 1
        assert result[0]["columns"] == 3

    def test_raw_preserved(self) -> None:
        table = r"\begin{tabular}{ll} a & b \end{tabular}"
        result = parse_latex_table(table)
        assert result[0]["raw"] == table


class TestExtractTablesFromText:
    """extract_tables_from_text 将表格替换为可读文本。"""

    def test_no_table_passthrough(self) -> None:
        assert extract_tables_from_text("hello") == "hello"

    def test_table_replaced(self) -> None:
        table = r"\begin{tabular}{ll} a & b \\ c & d \end{tabular}"
        result = extract_tables_from_text(table)
        assert "[table:" in result
        assert "a | b" in result
        assert "c | d" in result
        assert "\\begin{tabular}" not in result
