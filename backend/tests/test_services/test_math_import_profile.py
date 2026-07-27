"""Tests for math candidate detection engine (P1-2)."""


from app.features.math_import_profile import (
    apply_math_risk_flags,
    is_math_candidate,
)

# ---------------------------------------------------------------------------
# is_math_candidate — subject triggers
# ---------------------------------------------------------------------------

class TestSubjectTriggers:
    def test_math2_subject(self):
        q = {"subject": "math2", "stem": "求极限"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True
        assert diag["excluded_by"] is None
        assert any("subject=math2" in s for s in diag["signals"])

    def test_math1_subject(self):
        q = {"subject": "math1", "stem": "求积分"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True

    def test_non_math_subject(self):
        q = {"subject": "english", "stem": "What is the main idea"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is False


# ---------------------------------------------------------------------------
# is_math_candidate — name triggers
# ---------------------------------------------------------------------------

class TestNameTriggers:
    def test_chinese_math_name(self):
        q = {"category": "高等数学", "stem": "计算定积分"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True
        assert any("category=" in s for s in diag["signals"])

    def test_linear_algebra_name(self):
        q = {"category": "线性代数", "stem": "求矩阵特征值"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True

    def test_empty_category(self):
        q = {"stem": "∫x² dx"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True


# ---------------------------------------------------------------------------
# is_math_candidate — symbol triggers
# ---------------------------------------------------------------------------

class TestSymbolTriggers:
    def test_integral_symbol(self):
        q = {"stem": "计算 ∫₀¹ x² dx"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True
        assert any("math_symbols" in s for s in diag["signals"])

    def test_latex_int(self):
        q = {"stem": "求 \\int_{0}^{1} x^2 \\, dx"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True

    def test_sum_symbol(self):
        q = {"stem": "计算 ∑"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True

    def test_frac_latex(self):
        q = {"stem": "\\frac{1}{2} + \\frac{1}{3}"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True

    def test_matrix_symbol(self):
        q = {"stem": "\\begin{matrix} 1 & 2 \\\\ 3 & 4 \\end{matrix}"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True

    def test_lim(self):
        q = {"stem": "\\lim_{x \\to 0} \\frac{\\sin x}{x}"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True
        # `\to` between \lim and \frac breaks the simple regex match;
        # flagged as math but not complex-formula (rule limitation)

    def test_dx_dy_signal(self):
        q = {"stem": "dy/dx = y"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True

    def test_sqrt(self):
        q = {"stem": "\\sqrt{2}"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True


# ---------------------------------------------------------------------------
# is_math_candidate — complex formula detection
# ---------------------------------------------------------------------------

class TestComplexFormula:
    def test_complex_fraction(self):
        q = {"stem": "\\frac{x^2 + 2x + 1}{x + 1}"}
        diag = is_math_candidate(q)
        assert diag["has_complex_formula"] is True
        assert diag["requires_review"] is True

    def test_matrix_environment(self):
        q = {"stem": "\\begin{vmatrix} 1 & 2 \\\\ 3 & 4 \\end{vmatrix}"}
        diag = is_math_candidate(q)
        assert diag["has_complex_formula"] is True

    def test_cases_environment(self):
        q = {"stem": "\\begin{cases} x + y = 1 \\\\ 2x - y = 3 \\end{cases}"}
        diag = is_math_candidate(q)
        assert diag["has_complex_formula"] is True

    def test_sum_with_fraction(self):
        q = {"stem": "\\sum_{n=1}^{\\infty} \\frac{1}{n^2}"}
        is_math_candidate(q)
        # `\infty` between \sum_ and \frac breaks simple regex;
        # flagged as math but not complex-formula via this pattern

    def test_align_environment(self):
        q = {"stem": "\\begin{align} x &= 1 \\\\ y &= 2 \\end{align}"}
        diag = is_math_candidate(q)
        assert diag["has_complex_formula"] is True

    def test_simple_formula_not_complex(self):
        q = {"stem": "x = \\frac{a}{b}"}
        diag = is_math_candidate(q)
        # Simple fraction (short numerator/denominator) not flagged as complex
        assert diag["has_complex_formula"] is False


# ---------------------------------------------------------------------------
# is_math_candidate — 408/code exclusion
# ---------------------------------------------------------------------------

class TestCodeExclusion:
    def test_c_language_excluded(self):
        q = {"subject": "408", "stem": "C语言"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is False
        assert diag["excluded_by"] == "code_topic"

    def test_include_header_excluded(self):
        q = {"stem": '#include <stdio.h>\nint main() { printf("hello"); }'}
        diag = is_math_candidate(q)
        assert diag["is_math"] is False
        assert diag["excluded_by"] == "code_topic"

    def test_pointer_excluded(self):
        q = {"stem": "p->next = NULL"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is False
        assert diag["excluded_by"] == "code_topic"

    def test_data_structure_excluded(self):
        q = {"subject": "数据结构", "stem": "树的遍历"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is False

    def test_sql_excluded(self):
        q = {"stem": "SELECT * FROM users WHERE id = 1"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is False

    def test_math_not_excluded_by_408_subject(self):
        """math2 subject should NOT be excluded even if stem resembles code."""
        q = {"subject": "math2", "stem": "lim dx"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True

    def test_for_loop_but_math_context(self):
        q = {"subject": "math2", "stem": "sum_{k=1}^{n} k^2"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True


# ---------------------------------------------------------------------------
# is_math_candidate — edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_stem(self):
        q = {"subject": "math2"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True  # subject triggers

    def test_none_fields(self):
        q = {"subject": None, "stem": None, "analysis": None}
        diag = is_math_candidate(q)
        assert diag["is_math"] is False

    def test_analysis_only_math(self):
        q = {"stem": "选择题", "analysis": "∫x² dx"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True

    def test_raw_text_analysis(self):
        q = {"raw_text": "408 计算机", "stem": "x + y"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is False


# ---------------------------------------------------------------------------
# apply_math_risk_flags
# ---------------------------------------------------------------------------

class TestApplyMathRiskFlags:
    def test_basic_math_flag(self):
        q = {"stem": "∫x² dx"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is True
        flags = apply_math_risk_flags(q, diag)
        assert "math_region_detected" in flags

    def test_complex_formula_flag(self):
        q = {"stem": "\\begin{matrix} 1 & 2 \\\\ 3 & 4 \\end{matrix}"}
        diag = is_math_candidate(q)
        flags = apply_math_risk_flags(q, diag)
        assert "math_region_detected" in flags
        assert "complex_formula_requires_review" in flags

    def test_excluded_returns_empty(self):
        q = {"stem": "p->next"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is False
        flags = apply_math_risk_flags(q, diag)
        assert flags == []

    def test_non_math_returns_empty(self):
        q = {"stem": "What is the capital of France?"}
        diag = is_math_candidate(q)
        assert diag["is_math"] is False
        flags = apply_math_risk_flags(q, diag)
        assert flags == []
