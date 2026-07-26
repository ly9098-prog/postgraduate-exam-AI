"""OCR Quality Gate 单元测试 — 污染检测 & 上下文感知 LaTeX 判断。"""
from app.features.ocr_quality_gate import (
    _assess_context,
    detect_ocr_contamination,
)

# ---------------------------------------------------------------
# 1. 上下文评估 (_assess_context)
# ---------------------------------------------------------------

class TestAssessContext:
    def test_math_context(self):
        """数学关键词文本应返回 'math'。"""
        text = "设向量 α 与 β 线性无关，求矩阵 A 的特征值。"
        assert _assess_context(text) == "math"

    def test_math_latex(self):
        """包含 LaTeX 数学公式的文本。"""
        text = r"计算积分 \int_0^1 f(x) dx 和导数 f'(x)。"
        assert _assess_context(text) == "math"

    def test_programming_context(self):
        """编程关键词文本应返回 'programming'。"""
        text = "链表结点通过指针 next 指向下一个结点。"
        assert _assess_context(text) == "programming"

    def test_unknown_context(self):
        """无关键词文本应返回 'unknown'。"""
        text = "今天天气很好。"
        assert _assess_context(text) == "unknown"

    def test_mixed_context(self):
        """同时包含两类关键词但一方未占优时返回 'mixed'。"""
        text = "向量与指针同时出现。"
        # "向量" in MATH, "指针" in PROGRAMMING, both score=1 → mixed
        assert _assess_context(text) == "mixed"

    def test_math_dominates_over_programming(self):
        """数学关键词远多于编程关键词时判定为 math。"""
        text = "向量 矩阵 行列式 特征值 和 指针有关"
        # math=4, prog=1 → math(4) > prog(1) 但 prog >= 1, 不过 math >= 2 and math > prog → "math"
        assert _assess_context(text) == "math"

    def test_programming_dominates_over_math(self):
        """编程关键词远多于数学关键词时判定为 programming。"""
        text = "链表 结点 指针 遍历 特征值 排序"
        # 链表、结点、指针、遍历、排序 = 5 prog, 特征值 = 1 math → programming
        assert _assess_context(text) == "programming"

    def test_single_math_keyword(self):
        """仅一个数学关键词仍判定为 math。"""
        text = "关于矩阵的问题"
        assert _assess_context(text) == "math"

    def test_empty_text(self):
        """空文本返回 'unknown'。"""
        assert _assess_context("") == "unknown"


# ---------------------------------------------------------------
# 2. 符号替换 — 数学上下文（不应误报）
# ---------------------------------------------------------------

class TestSymbolSubstitutionMathContext:
    def test_alpha_in_math_vector(self):
        r"""\alpha 在数学上下文中不应被扣分。"""
        text = r"设向量 α, β, γ 线性无关，\alpha = (1,0,0)^T。"
        result = detect_ocr_contamination(text)
        # 上下文为 math，symbol_score = 0.0，即使有乱码也可能不被标记为污染
        # 只要总 score < 0.30 即可
        assert result["score"] < 0.30, (
            f"数学上下文中 \\alpha 不应导致污染: score={result['score']}"
        )

    def test_latex_math_formula(self):
        r"""完整 LaTeX 公式环境中的 \alpha 不应触发污染。"""
        text = r"求极限 \lim_{x \to 0} \frac{\alpha x}{\sin x} 其中 \alpha 为常数。"
        result = detect_ocr_contamination(text)
        assert result["score"] < 0.30, (
            f"LaTeX 公式中的 \\alpha 不应导致污染: score={result['score']}"
        )

    def test_multiple_latex_symbols_in_math(self):
        r"""多个 LaTeX 符号在数学上下文中也不应扣分。"""
        text = (
            r"设 \alpha, \beta, \gamma, \delta 为矩阵 A 的特征值，"
            r"求 \det(A) 和 \lambda_{\max}。"
        )
        result = detect_ocr_contamination(text)
        assert result["score"] < 0.30, (
            f"数学上下文中多个 LaTeX 符号不应导致污染: score={result['score']}"
        )

    def test_math_with_watermark_should_still_detect_watermark(self):
        """数学上下文仍应检测其他污染维度（如水印噪声）。"""
        text = (
            "向量分析\n" * 3
            + "\n".join(["abc"] * 5)  # 短 ASCII 行 → watermark
        )
        result = detect_ocr_contamination(text)
        assert "watermark_noise_detected" in result["flags"], "水印检测不应被数学上下文影响"


# ---------------------------------------------------------------
# 3. 符号替换 — 编程上下文（正常检测）
# ---------------------------------------------------------------

class TestSymbolSubstitutionProgrammingContext:
    def test_alpha_in_linked_list(self):
        r"""\alpha 在编程上下文中应被检测为污染。"""
        text = r"链表结点通过指针 \alpha next 指向下一个结点。"
        result = detect_ocr_contamination(text)
        # 上下文 = programming, symbol_hits >= 1 → score += 0.25
        # 无其他扣分项, 所以总 score ≥ 0.25
        assert result["score"] >= 0.25, (
            f"编程上下文中 \\alpha 应被检测: score={result['score']}"
        )

    def test_multiple_greek_in_code(self):
        r"""多个希腊符号在编程上下文中加重扣分。"""
        text = (
            "void func() {\n"
            r"    struct node * \alpha = \beta;  // OCR 污染\n"
            r"    \gamma->next = NULL;\n"
            "}"
        )
        result = detect_ocr_contamination(text)
        assert result["score"] >= 0.30, (
            f"编程上下文中多个希腊符号应加重污染: score={result['score']}"
        )
        assert "symbol_substitution_detected" in result["flags"]


# ---------------------------------------------------------------
# 4. 符号替换 — 无明确上下文（默认行为）
# ---------------------------------------------------------------

class TestSymbolSubstitutionNoContext:
    def test_alpha_no_context_still_detected(self):
        r"""\alpha 在无明确上下文时仍按默认规则检测。"""
        text = r"内容包含 \alpha 和 \beta 两个标记。"
        result = detect_ocr_contamination(text)
        # 无 math/prog 关键词, context = unknown
        # symbol_hits=2 → score += 0.35
        assert result["score"] >= 0.30, (
            f"无上下文中 \\alpha 应被默认检测: score={result['score']}"
        )
        assert "symbol_substitution_detected" in result["flags"]


# ---------------------------------------------------------------
# 5. 其他检测维度不应受上下文影响
# ---------------------------------------------------------------

class TestOtherDetectionDimensions:
    def test_garbled_still_detected(self):
        """乱码检测不受上下文影响。"""
        text = "向量和矩阵 snexP Apxt ext=q 乱码混合"
        result = detect_ocr_contamination(text)
        assert "garbled_text_detected" in result["flags"]

    def test_option_structure_corrupted_still_detected(self):
        """选项结构破损检测不受上下文影响。"""
        text = "向量的长度是\nA. 1\nC. 3\nD. 4"
        result = detect_ocr_contamination(text)
        assert "option_structure_corrupted" in result["flags"]


# ---------------------------------------------------------------
# 6. 边界情况
# ---------------------------------------------------------------

class TestEdgeCases:
    def test_empty_text(self):
        result = detect_ocr_contamination("")
        assert result["score"] == 0.0
        assert result["flags"] == []
        assert result["is_contaminated"] is False

    def test_whitespace_only(self):
        result = detect_ocr_contamination("   \n  \n  ")
        assert result["score"] == 0.0
        assert result["is_contaminated"] is False

    def test_normal_math_no_contamination(self):
        """正常数学文本不应被标记为污染。"""
        text = (
            "1. 设函数 f(x) 在区间 [0,1] 上连续，且 f(0)=0，"
            r"求极限 \lim_{x \to 0} \frac{f(x)}{x}。" + "\n"
            "A. 0\nB. 1\nC. f'(0)\nD. 不存在"
        )
        result = detect_ocr_contamination(text)
        assert result["score"] < 0.30, (
            f"正常数学文本误报: score={result['score']}, flags={result['flags']}"
        )

    def test_score_bounded(self):
        """污染分数应在 [0.0, 1.0] 范围内。"""
        text = (
            r"向量 \alpha \beta \gamma \delta \theta 乱码 snexP Apxt 扫描多行短文本 "
            * 10
        )
        result = detect_ocr_contamination(text)
        assert 0.0 <= result["score"] <= 1.0
