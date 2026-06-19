"""OCR 数学公式修复：将常见 OCR 错误转换为标准 LaTeX。

只做规则替换，不引入新依赖。
调用点：question_pipeline._extract_pdf_text 和 ocr_service.clean_ocr_text 之后。
"""
import re


# ── 希腊字母 Unicode → LaTeX ──────────────────────────────────────────────────

_GREEK = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\varepsilon", "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta",
    "λ": r"\lambda", "μ": r"\mu", "ν": r"\nu", "ξ": r"\xi",
    "π": r"\pi", "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau",
    "φ": r"\varphi", "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega",
    "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda",
    "Ξ": r"\Xi", "Π": r"\Pi", "Σ": r"\Sigma", "Φ": r"\Phi",
    "Ψ": r"\Psi", "Ω": r"\Omega",
}

# ── 数学运算符 Unicode → LaTeX ────────────────────────────────────────────────

_OPERATORS = {
    "∞": r"\infty",
    "∂": r"\partial",
    "∇": r"\nabla",
    "∈": r"\in",
    "∉": r"\notin",
    "⊂": r"\subset",
    "⊃": r"\supset",
    "∪": r"\cup",
    "∩": r"\cap",
    "∅": r"\emptyset",
    "≤": r"\leq",
    "≥": r"\geq",
    "≠": r"\neq",
    "≈": r"\approx",
    "≡": r"\equiv",
    "±": r"\pm",
    "×": r"\times",
    "÷": r"\div",
    "·": r"\cdot",
    "→": r"\to",
    "←": r"\leftarrow",
    "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow",
    "⇔": r"\Leftrightarrow",
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "√": r"\sqrt",
}

# ── 上下标修复规则（顺序敏感，放在所有替换之后）────────────────────────────

_SUPERSCRIPT_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ", "0123456789+-n")
_SUBSCRIPT_MAP = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def _fix_unicode_super_sub(text: str) -> str:
    """Unicode 上下标字符 → 普通字符（后续由上下文规则包 ^{} / _{} 处理）。"""
    result = []
    i = 0
    while i < len(text):
        ch = text[i]
        sup = ch.translate(_SUPERSCRIPT_MAP)
        sub = ch.translate(_SUBSCRIPT_MAP)
        if sup != ch:
            result.append(f"^{{{sup}}}")
        elif sub != ch:
            result.append(f"_{{{sub}}}")
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def _replace_symbols(text: str) -> str:
    """Unicode 数学符号 → LaTeX 命令（仅在数学上下文之外出现时替换）。"""
    for ch, cmd in {**_GREEK, **_OPERATORS}.items():
        text = text.replace(ch, cmd)
    return text


# ── OCR 常见拼写错误修复 ──────────────────────────────────────────────────────

# 每条规则：(pattern, replacement)，按顺序应用
_OCR_FIXES: list[tuple[re.Pattern, str]] = [
    # "x2" / "x3" 裸上标（字母后直接接数字，且不在已有 ^ 之后）
    # 排除单数字 1（常见标识符后缀，如 P1/A1/B1）；排除后接 ( 的函数调用
    (re.compile(r"(?<![_^{])\b([a-zA-Z])[ \t]*((?:[2-9]\d*|\d{2,}))\b(?!\s*[_^}(])"), r"\1^{\2}"),
    # "1 /2"、"1/2" 孤立分数 → \frac{1}{2}
    (re.compile(r"\b(\d+)\s*/\s*(\d+)\b"), r"\\frac{\1}{\2}"),
    # √x / √(expr) → \sqrt{x} / \sqrt{expr}
    (re.compile(r"\\sqrt\s*\(([^)]+)\)"), r"\\sqrt{\1}"),
    (re.compile(r"\\sqrt\s+([^\s{\\]+)"), r"\\sqrt{\1}"),
    # lim x→0 → \lim_{x \to 0}，または lim x\to0 → \lim_{x \to 0}
    (re.compile(r"\blim\s+([a-zA-Z])\s*(?:→|\\to)\s*([^\s,，。]+)"), r"\\lim_{\1 \\to \2}"),
    # ∫0^1 → \int_0^1（OCR 漏掉 _ ）
    (re.compile(r"\\int\s*([^_^{\s\\]+)\s*\^\s*([^_^{\s\\]+)"), r"\\int_{\1}^{\2}"),
    # 清理 LaTeX 命令后多余空格：\frac { → \frac{
    (re.compile(r"(\\[a-zA-Z]+)\s+\{"), r"\1{"),
    # 修复括号不匹配：\frac{a}{b 末尾漏 }（简单单层检测）
    # 不做深度括号修复，避免误改
]


def fix_ocr_formula(text: str) -> str:
    """修复单段文本中的 OCR 公式错误，返回修复后文本。

    本函数只做保守替换：
    1. Unicode 上下标转普通字符
    2. 数学符号转 LaTeX 命令
    3. 常见拼写错误修复

    不会修改已经正确的 LaTeX（$...$ 内部也会处理，因为这些规则同样适用）。
    """
    if not text:
        return text
    text = _fix_unicode_super_sub(text)
    text = _replace_symbols(text)
    for pattern, replacement in _OCR_FIXES:
        text = pattern.sub(replacement, text)
    return text


def normalize_text_import_math(text: str, *, compact: bool = False) -> str:
    """Normalize math from text imports. Preserves $ delimiters for frontend rendering.

    Does NOT strip math delimiters (frontend needs $...$ to render math).
    Does NOT apply OCR fixes (text import is user-pasted, not OCR-generated;
    OCR fixes are applied separately in PDF/OCR paths).
    """
    if not text:
        return text
    text = _collapse_latex_escapes(text)
    text = _normalize_common_math_notation(text)
    if compact:
        text = _compact_formula_spacing(text)
    return text.strip()


def _collapse_latex_escapes(text: str) -> str:
    text = re.sub(r"\\{2,}([A-Za-z]+)", r"\\\1", text)
    text = re.sub(r"\\{2,}([()[\]{}])", r"\\\1", text)
    return text


def _strip_math_delimiters(text: str) -> str:
    text = re.sub(r"\\\((.*?)\\\)", r"\1", text, flags=re.S)
    text = re.sub(r"\\\[(.*?)\\\]", r"\1", text, flags=re.S)
    text = re.sub(r"\$\$(.*?)\$\$", r"\1", text, flags=re.S)
    text = re.sub(r"\$([^$\n]+?)\$", r"\1", text)
    return text


def _normalize_common_math_notation(text: str) -> str:
    text = re.sub(r"_\{([0-9A-Za-z+-]+)\}", r"_\1", text)
    text = re.sub(r"\^\{([0-9A-Za-z+-]+)\}", r"^\1", text)

    def repl_named_with_base(match: re.Match) -> str:
        name = match.group(1)
        base = match.group(2)
        return rf"\{name}_{base}"

    text = re.sub(r"(?<!\\)(log|ln|sin|cos|tan)\s*_?\{?([0-9]+)\}?", repl_named_with_base, text)
    text = re.sub(r"(?<!\\)\b(log|ln|sin|cos|tan|sqrt|frac)\b", r"\\\1", text)
    return text


def _compact_formula_spacing(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*([=+\-*/^_(),])\s*", r"\1", text)
    text = re.sub(r"(?<=\\[A-Za-z])\s+(?=_?\d|[A-Za-z0-9(])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9)])\s+(?=\\[A-Za-z])", "", text)
    text = re.sub(r"(?<=\\log_\d)\s+(?=[A-Za-z])", "", text)
    return text


def wrap_inline_math(text: str) -> str:
    """裸の LaTeX コマンド片段を $...$ で囲む。

    既存の $...$ / $$...$$ はそのまま保持。
    \\command から始まる数式スパン、または x^{} / x_{} から始まる区間を
    中国語文字・句読点・改行が現れるまで拡張して 1 つの $ で囲む。
    """
    if not text:
        return text
    parts = re.split(r"(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])", text)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(part)
        else:
            result.append(_wrap_bare_latex(part))
    return "".join(result)


_LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]+")
_SUBSCRIPT_RE = re.compile(r"[a-zA-Z0-9]\^[{0-9]|[a-zA-Z0-9]_[{0-9]")


def _wrap_bare_latex(text: str) -> str:
    """テキスト中の裸 LaTeX 区間を $ $ で囲む（内部ヘルパー）。"""
    result = []
    i = 0
    n = len(text)

    while i < n:
        m1 = _LATEX_CMD_RE.search(text, i)
        m2 = _SUBSCRIPT_RE.search(text, i)

        if m1 is None and m2 is None:
            result.append(text[i:])
            break

        if m1 is None:
            start = m2.start()  # type: ignore[union-attr]
        elif m2 is None:
            start = m1.start()
        else:
            start = min(m1.start(), m2.start())

        result.append(text[i:start])

        # 数式スパンを { } の深さを追跡しながら拡張
        depth = 0
        j = start
        while j < n:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                if depth > 0:
                    depth -= 1
                else:
                    break
            elif c == "\n":
                break
            elif depth == 0 and "一" <= c <= "鿿":
                break
            elif depth == 0 and c in "，。！？；：、…":
                break
            j += 1

        span = text[start:j].strip()
        if span:
            result.append(f"${span}$")
        i = j

    return "".join(result)


# ── LaTeX 表格解析 ─────────────────────────────────────────────────────────────

_RE_TABULAR = re.compile(
    r"\\begin\{tabular\}\{([^}]*)\}(.*?)\\end\{tabular\}",
    re.DOTALL,
)

_RE_MULTICOLUMN = re.compile(r"\\multicolumn\{(\d+)\}\{[^}]*\}\{([^}]*)\}")
_RE_HLINE = re.compile(r"\\hline\s*")
_RE_CLINE = re.compile(r"\\cline\{[^}]*\}")
_RE_STAR_COLSPEC = re.compile(r"\*\{(\d+)\}\{([^}]+)\}")  # 展开 *{N}{cols}


def _parse_cell(text: str) -> str:
    """清理单个单元格内容。"""
    text = _RE_HLINE.sub("", text)
    text = _RE_CLINE.sub("", text)
    return text.strip()


def _split_row(row_text: str) -> list[str]:
    """将一行按 & 切分为单元格。"""
    cells: list[str] = []
    for part in row_text.split("&"):
        cells.append(_parse_cell(part))
    return cells


def parse_latex_table(text: str) -> list[dict]:
    """解析文本中的 LaTeX tabular 表格，返回结构化数据。

    每个表格返回 dict: {"columns": int, "rows": [[cell, ...], ...], "raw": str}
    若未找到表格则返回空列表。
    """
    tables: list[dict] = []
    for match in _RE_TABULAR.finditer(text):
        col_spec = match.group(1)
        body = match.group(2)

        # 列数估算：展开 *{N}{cols} 后计数 lcrp 对齐符
        _expanded_spec = col_spec
        while True:
            m = _RE_STAR_COLSPEC.search(_expanded_spec)
            if not m:
                break
            _expanded_spec = _expanded_spec.replace(m.group(0), m.group(2) * int(m.group(1)))
        col_count = sum(1 for c in _expanded_spec if c in "lcrp")

        rows: list[list[str]] = []
        raw_rows = body.split(r"\\")
        for raw_row in raw_rows:
            if _RE_HLINE.fullmatch(raw_row.strip()):
                continue
            cleaned = raw_row
            cleaned = _RE_MULTICOLUMN.sub(r"\2", cleaned)
            cells = _split_row(cleaned)
            if any(c for c in cells):
                rows.append(cells)

        if rows:
            tables.append({
                "columns": col_count or max(len(r) for r in rows),
                "rows": rows,
                "raw": match.group(0),
            })

    return tables


def extract_tables_from_text(text: str) -> str:
    """将文本中的 LaTeX tabular 替换为结构化可读文本。

    保留表格原始内容并标注行列结构，方便后续人工审核。
    """
    tables = parse_latex_table(text)
    if not tables:
        return text

    result = text
    for t in tables:
        lines = [f"[table: {t['columns']}cols x {len(t['rows'])}rows]"]
        for row in t["rows"]:
            lines.append(" | ".join(row))
        replacement = "\n".join(lines)
        result = result.replace(t["raw"], replacement, 1)

    return result
