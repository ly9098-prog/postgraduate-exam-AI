"""OCR Quality Gate — 在解析前检测 OCR 污染，阻止损坏文本进入 parser。

纯规则实现，无 AI 依赖。在 normalize_schema 前调用。
检测维度：
- 符号替换（α→q, β→B 等）
- 乱码模式（snexP, Apxt 等无意义 ASCII 串）
- 选项结构破损（A/B/C/D 不完整）
- next 指针语义断裂
"""

import re
import logging

from app.features.code_integrity import (
    _RE_CONSECUTIVE_CONSONANTS,
    _RE_KNOWN_GARBLED,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数学上下文关键词 — LaTeX 命令在此类文本中属于合法数学符号
# ---------------------------------------------------------------------------
_MATH_CONTEXT_KEYWORDS: frozenset[str] = frozenset([
    "向量", "矩阵", "行列式", "特征值", "特征向量", "二次型",
    "积分", "导数", "微分方程", "偏导", "极限", "收敛", "连续",
    "可导", "可微", "单调", "极值", "拐点", "渐近线",
    "概率", "分布", "期望", "方差", "统计",
    "方程", "不等式", "函数", "线性无关", "线性相关",
    "正交", "相似矩阵", "对角化", "秩",
])

# ---------------------------------------------------------------------------
# 编程上下文关键词 — LaTeX 命令在此类文本中更可能是 OCR 污染
# ---------------------------------------------------------------------------
_PROGRAMMING_CONTEXT_KEYWORDS: frozenset[str] = frozenset([
    "链表", "结点", "节点", "指针", "数组", "栈", "队列",
    "二叉树", "排序", "递归", "迭代", "遍历", "查找",
    "next", "prev", "NULL", "malloc", "free", "struct",
    "->", "typedef", "void", "int ", "char ", "float ",
])


def _assess_context(text: str) -> str:
    """评估文本所属上下文领域。

    Returns:
        "math": 数学上下文（LaTeX 命令应视为合法）
        "programming": 编程上下文（LaTeX 命令更可能是污染）
        "mixed": 上下文不明确
        "unknown": 无明确上下文信号
    """
    text_lower = text.lower()
    math_score = 0
    for kw in _MATH_CONTEXT_KEYWORDS:
        if kw in text_lower:
            math_score += 1
    prog_score = 0
    for kw in _PROGRAMMING_CONTEXT_KEYWORDS:
        if kw in text_lower:
            prog_score += 1

    if math_score >= 2 and math_score > prog_score:
        return "math"
    if prog_score >= 2 and prog_score > math_score:
        return "programming"
    if math_score >= 1 and prog_score >= 1:
        return "mixed"
    if math_score >= 1:
        return "math"
    if prog_score >= 1:
        return "programming"
    return "unknown"


# ---------------------------------------------------------------------------
# 符号替换检测 — OCR 将拉丁字符误识为希腊/数学符号
# ---------------------------------------------------------------------------
_SYMBOL_SUBSTITUTION_PATTERNS = [
    (re.compile(r"\\alpha"), "α→q/a 替换"),
    (re.compile(r"\\beta"), "β→B 替换"),
    (re.compile(r"\\gamma"), "γ→r 替换"),
    (re.compile(r"\\delta"), "δ→d 替换"),
    (re.compile(r"\\theta"), "θ→0 替换"),
    (re.compile(r"\\lambda"), "λ→λ 替换"),
    (re.compile(r"α"), "α 希腊字母污染"),
    (re.compile(r"β"), "β 希腊字母污染"),
    (re.compile(r"γ"), "γ 希腊字母污染"),
]

# ---------------------------------------------------------------------------
# 乱码模式 — 源自 code_integrity 的共享模式
# ---------------------------------------------------------------------------
_GARBLED_PATTERNS = [
    _RE_KNOWN_GARBLED,                    # 已知乱码片段
    _RE_CONSECUTIVE_CONSONANTS,           # 4+ 连续纯辅音字母
]

# 短 ASCII 行模式：一行内全是短 ASCII 片段且无中文字符
_RE_SHORT_GARBLED_LINE = re.compile(r"^[!-~]{1,20}$", re.MULTILINE)

# ---------------------------------------------------------------------------
# 选项结构破损检测
# ---------------------------------------------------------------------------
_RE_OPTION_MARKER = re.compile(r"(?:^|\n)\s*([A-D])\s*[.、:：)）]", re.MULTILINE)

# ---------------------------------------------------------------------------
# next 指针语义断裂检测
# ---------------------------------------------------------------------------
_RE_NEXT_PTR = re.compile(r"->\s*next", re.IGNORECASE)
_RE_BROKEN_ARROW = re.compile(r"[−–—]\s*>", re.IGNORECASE)  # 破折号替代箭头


def detect_ocr_contamination(raw_text: str) -> dict:
    """检测 OCR 原始文本中的污染信号 + 代码块完整性。

    Args:
        raw_text: OCR 原始识别文本

    Returns:
        {
            "flags": [str],           # 检测到的污染标签
            "score": float,           # 0.0 ~ 1.0 污染分数
            "is_contaminated": bool,  # 是否超过阈值
            "details": [str],         # 人类可读的检测详情
        }
    """
    if not raw_text or not raw_text.strip():
        return {
            "flags": [],
            "score": 0.0,
            "is_contaminated": False,
            "details": [],
        }

    flags: list[str] = []
    details: list[str] = []
    score = 0.0

    # ---- 0. 代码块完整性检测（在其它检测前运行） ----
    from app.features.code_integrity import detect_code_block_integrity
    code_result = detect_code_block_integrity(raw_text)
    if code_result["score"] > 0:
        for flag in code_result["flags"]:
            if flag not in flags:
                flags.append(flag)
        score += code_result["score"]
        details.extend(code_result["details"])

    # ---- 1. 符号替换检测（上下文感知） ----
    symbol_hits = 0
    for pat, desc in _SYMBOL_SUBSTITUTION_PATTERNS:
        if pat.search(raw_text):
            symbol_hits += 1
            if "symbol_substitution_detected" not in flags:
                flags.append("symbol_substitution_detected")
            details.append(desc)

    if symbol_hits >= 1:
        context = _assess_context(raw_text)
        if context == "math":
            # 数学上下文中 LaTeX 命令属于合法数学符号，不扣分
            symbol_score = 0.0
        elif context == "programming":
            # 编程上下文中希腊符号更可能是 OCR 污染，加重扣分
            symbol_score = 0.35 if symbol_hits >= 2 else 0.25
        else:
            # 无明确上下文时走默认评分
            symbol_score = 0.35 if symbol_hits >= 2 else 0.15
        score += symbol_score
        if symbol_score > 0:
            details.append(f"上下文='{context}', 符号污染分数={symbol_score:.2f}")

    # ---- 2. 乱码模式检测 ----
    garbled_hits = 0
    for pat in _GARBLED_PATTERNS:
        matches = pat.findall(raw_text)
        if matches:
            garbled_hits += len(matches)

    if garbled_hits >= 3:
        score += 0.40
        flags.append("garbled_text_detected")
        details.append(f"检测到 {garbled_hits} 处乱码模式")
    elif garbled_hits >= 1:
        score += 0.20
        if "garbled_text_detected" not in flags:
            flags.append("garbled_text_detected")
        details.append(f"检测到 {garbled_hits} 处乱码模式")

    # ---- 3. 短 ASCII 行检测（水印/噪声特征） ----
    short_ascii_lines = _RE_SHORT_GARBLED_LINE.findall(raw_text)
    if len(short_ascii_lines) >= 3:
        score += 0.25
        if "watermark_noise_detected" not in flags:
            flags.append("watermark_noise_detected")
        details.append(f"检测到 {len(short_ascii_lines)} 行疑似水印/噪声短文本")

    # ---- 4. 选项结构破损检测 ----
    option_markers = _RE_OPTION_MARKER.findall(raw_text)
    present_options = set(option_markers)
    if present_options:
        # 有选项但缺关键选项
        if "A" in present_options and "B" not in present_options:
            score += 0.20
            flags.append("option_structure_corrupted")
            details.append("选项结构破损: 有A缺B")
        if "B" in present_options and "C" not in present_options:
            score += 0.20
            flags.append("option_structure_corrupted")
            details.append("选项结构破损: 有B缺C")
        if "C" in present_options and "D" not in present_options and len(raw_text) > 100:
            score += 0.20
            flags.append("option_structure_corrupted")
            details.append("选项结构破损: 有C缺D（疑似D被水印覆盖）")
        if len(present_options) <= 2 and len(raw_text) > 150:
            score += 0.15
            if "option_structure_corrupted" not in flags:
                flags.append("option_structure_corrupted")
            details.append(f"长文本仅 {len(present_options)} 个选项标记")

    # ---- 5. next 指针语义断裂检测 ----
    next_ptrs = _RE_NEXT_PTR.findall(raw_text)
    broken_arrows = _RE_BROKEN_ARROW.findall(raw_text)
    if broken_arrows and next_ptrs:
        # 箭头被 OCR 破坏但仍有 next 引用
        score += 0.15
        flags.append("semantic_break_detected")
        details.append("next 指针箭头可能被 OCR 破坏")

    score = round(min(score, 1.0), 2)

    return {
        "flags": list(dict.fromkeys(flags)),  # 去重保序
        "score": score,
        "is_contaminated": score >= 0.30,  # 阈值 ≥ 0.30 视为污染
        "details": details,
    }


def extract_options_from_raw(raw_text: str) -> set[str]:
    """从 OCR 原始文本中提取选项标签集合。

    用于 cross-check: 比对 raw_text 与 parsed_options 的选项一致性。
    """
    if not raw_text:
        return set()
    markers = _RE_OPTION_MARKER.findall(raw_text)
    return set(markers)


def cross_check_consistency(raw_text: str, parsed_options: dict | list) -> dict:
    """校验 raw_text 选项与 parsed_options 的一致性。

    Returns:
        {
            "is_consistent": bool,
            "raw_options": set,       # raw_text 中的选项标签
            "parsed_options": set,    # parsed 中的选项标签
            "missing_in_parsed": set, # raw 有但 parsed 无
            "extra_in_parsed": set,   # parsed 有但 raw 无
            "severity": "ok" | "warning" | "critical",
        }
    """
    raw_options = extract_options_from_raw(raw_text)

    if isinstance(parsed_options, dict):
        parsed_set = {k.upper() for k in parsed_options.keys()}
    elif isinstance(parsed_options, list):
        parsed_set = set()
        for opt in parsed_options:
            if isinstance(opt, dict):
                key = opt.get("key", "")
                if key:
                    parsed_set.add(key.upper())
    else:
        parsed_set = set()

    missing = raw_options - parsed_set
    extra = parsed_set - raw_options

    severity = "ok"
    if missing:
        severity = "critical"
    elif extra:
        severity = "warning"

    return {
        "is_consistent": len(missing) == 0,
        "raw_options": raw_options,
        "parsed_options": parsed_set,
        "missing_in_parsed": missing,
        "extra_in_parsed": extra,
        "severity": severity,
    }
