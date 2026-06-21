"""数学候选题识别与公式区域风险标记。

在 normalize_schema 后、review 入库前调用。纯规则引擎，不涉及 AI。
对每题判断是否属于数学候选题，并打上 risk_flags。
"""

import logging
import re

logger = logging.getLogger(__name__)

# ── 数学触发信号 ──

_MATH_SUBJECT_TRIGGERS = {"math2", "math1", "math3", "math2-calculus", "math2-linalg"}

_MATH_NAME_TRIGGERS = re.compile(
    r"数学|高数|高等数学|线性代数|概率论|数理统计|概率统计"
)

_MATH_SYMBOL_TRIGGER = re.compile(
    r"[∫∑√∞αβγδεθλμσπϕφψω]|"
    r"\\int|\\sum|\\frac|\\sqrt|\\lim|\\infty|"
    r"\\begin\{matrix\}|\\begin\{cases\}|\\begin\{vmatrix\}|"
    r"\\begin\{bmatrix\}|\\begin\{align\}|"
    r"\\displaystyle|\\partial|\\Delta|\\nabla|"
    r"\blim\b|\bdx\b|\bdy\b|\bdt\b|\bdu\b"
)

# ── 408/代码排除信号 ──

_CODE_EXCLUDE_TRIGGERS = re.compile(
    r"408|计算机|C语言|C\s*语言|数据结构|操作系统|计算机组成原理|"
    r"计组|计算机网络|计网|SQL|数据库|"
    r"#include|int\s+main|struct\s*{|typedef|"
    r"for\s*\(|while\s*\(|if\s*\(|printf|scanf|"
    r"SELECT|WHERE|FROM\s+\w+|ORDER\s+BY|GROUP\s+BY|"
    r"->next|->data|->val|\.next|\.data|"
    r"p\s*->|head\s*->|malloc|free\b|"
    r"return\s+0|void\s+main"
)

# ── 复杂公式风险检测信号 ──

_COMPLEX_FORMULA_PATTERNS = re.compile(
    r"\\frac\{[^}]{3,}\}\{[^}]{3,}\}|"        # 复杂分式
    r"\\begin\{matrix\}|\\begin\{vmatrix\}|"     # 矩阵/行列式
    r"\\begin\{bmatrix\}|\\begin\{cases\}|"       # 矩阵/分段函数
    r"\\sum_[^\\]+\\frac|"                       # 求和+分式
    r"\\int_[^\\]+\\frac|"                       # 积分+分式
    r"\\lim[^\\]+\\frac|"                        # 极限+分式
    r"\\sum\{[^}]{2,}\}|\\prod\b|"              # 多符号求和/连乘
    r"\\overline|\\underline|\\binom|"           # 复杂修饰
    r"\\begin\{align\}|\\begin\{eqnarray\}"      # 多行公式
)


def is_math_candidate(question: dict) -> dict:
    """判断题目是否为数学候选题，返回诊断信息。

    Returns:
        {"is_math": bool, "signals": [...], "excluded_by": str | None,
         "has_complex_formula": bool, "requires_review": bool}
    """
    signals: list[str] = []
    excluded_by: str | None = None
    has_complex = False
    requires_review = False

    # 1. 排除 408/代码题
    text_to_check = " ".join(filter(None, [
        question.get("subject") or "",
        question.get("category") or "",
        question.get("stem") or "",
        question.get("analysis") or "",
        question.get("raw_text") or "",
    ]))
    if _CODE_EXCLUDE_TRIGGERS.search(text_to_check):
        return {
            "is_math": False,
            "signals": [],
            "excluded_by": "code_topic",
            "has_complex_formula": False,
            "requires_review": False,
        }

    # 2. Subject 信号
    subject = (question.get("subject") or "").lower().strip()
    if subject in _MATH_SUBJECT_TRIGGERS:
        signals.append(f"subject={subject}")

    category = question.get("category") or ""
    if isinstance(category, str) and _MATH_NAME_TRIGGERS.search(category):
        signals.append(f"category={category}")

    # 3. 题干/解析中的数学符号
    stem = question.get("stem") or question.get("parsed_content", {}).get("text") or ""
    analysis = question.get("analysis") or ""
    full_text = f"{stem} {analysis}"

    symbol_matches = _MATH_SYMBOL_TRIGGER.findall(full_text)
    if symbol_matches:
        signals.append(f"math_symbols={len(symbol_matches)}")

    # 4. 复杂公式检测
    complex_matches = _COMPLEX_FORMULA_PATTERNS.findall(full_text)
    if complex_matches:
        signals.append("complex_formula")
        has_complex = True
        requires_review = True

    is_math = len(signals) > 0

    return {
        "is_math": is_math,
        "signals": signals,
        "excluded_by": excluded_by,
        "has_complex_formula": has_complex,
        "requires_review": requires_review,
    }


def apply_math_risk_flags(question: dict, diagnosis: dict) -> list[str]:
    """根据诊断结果对题目打风险标记。

    Returns:
        新增的 risk_flags 列表
    """
    if diagnosis["excluded_by"]:
        return []

    if not diagnosis["is_math"]:
        return []

    new_flags: list[str] = ["math_region_detected"]

    if diagnosis["has_complex_formula"]:
        new_flags.append("complex_formula_requires_review")

    return new_flags
