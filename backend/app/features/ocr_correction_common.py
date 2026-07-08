"""OCR Correction shared detection & filter utilities.

These functions are used by both the OCR fix router (ocr_fix/router.py)
and are re-exported via ocr_correction.py for backward compatibility.

They do NOT call any AI models — that responsibility belongs to ocr_fix/.
"""

import re

_VALID_OPTION_MARKERS = re.compile(r"^[A-D][.、．）)\s]", re.MULTILINE)
_QUESTION_NUM_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:\d{1,3}|第[一二三四五六七八九十百]+题)[.、．）)【\s]",
)
_GARBLED_CHARS = re.compile(r"[�□█░-▓\x00-\x08\x0e-\x1f]")
_SHORT_LINE_THRESHOLD = 5

# ---------------------------------------------------------------------------
# Structure anomaly detection patterns (多维触发引擎)
# ---------------------------------------------------------------------------

# Runs of consecutive unusual symbols (mirror chars, arrows, etc.)
_RE_ABNORMAL_SYMBOLS = re.compile(r"[<>=!_:]{2,}|<-+|>-+")
# ASCII letter runs of 3+ consecutive lowercase chars (potential garbled words)
_RE_ASCII_RUN = re.compile(r"[a-z]{3,}")

# ---------------------------------------------------------------------------
# Quality tier thresholds
# ---------------------------------------------------------------------------

TIER_HIGH_THRESHOLD = 0.15
TIER_MEDIUM_THRESHOLD = 0.30


def _classify_quality_tier(noise_score: float) -> str:
    """HIGH = clean (skip AI), MEDIUM = AI correct, LOW = AI correct + flag."""
    if noise_score < TIER_HIGH_THRESHOLD:
        return "HIGH"
    elif noise_score < TIER_MEDIUM_THRESHOLD:
        return "MEDIUM"
    else:
        return "LOW"


# ---------------------------------------------------------------------------
# Noise detection
# ---------------------------------------------------------------------------


def _detect_noise(block: dict) -> float:
    text = str(block.get("normalized_text") or "")
    if not text.strip():
        return 0.0

    lines = text.split("\n")
    total_lines = len(lines)
    if total_lines == 0:
        return 0.0

    score = 0.0

    # 1. Short line ratio (lines < 5 chars)
    short_lines = sum(1 for ln in lines if 0 < len(ln.strip()) < _SHORT_LINE_THRESHOLD)
    short_ratio = short_lines / total_lines
    if short_ratio > 0.4:
        score += 0.3
    elif short_ratio > 0.2:
        score += 0.15

    # 2. Garbled character density
    garbled_count = len(_GARBLED_CHARS.findall(text))
    garbled_ratio = garbled_count / max(len(text), 1)
    if garbled_ratio > 0.05:
        score += 0.3
    elif garbled_ratio > 0.02:
        score += 0.15

    # 3. Has options but no question number
    has_options = bool(_VALID_OPTION_MARKERS.search(text))
    has_question_num = bool(_QUESTION_NUM_PATTERN.search(text))
    if has_options and not has_question_num:
        score += 0.2

    # 4. Option fragmentation (has A but missing B/C/D)
    if has_options:
        found_options = set(re.findall(r"^([A-D])[.、．）)\s]", text, re.MULTILINE))
        if "A" in found_options and len(found_options) < 3:
            score += 0.2

    # 5. (P0: Problem A) Code garbled detection — detect if block contains
    # C code with garbled tokens. When code_detector recognizes code but
    # integrity check finds garbled content, raise noise score to trigger
    # OCR correction (VL rebuild or AI repair).
    _has_code_keywords = any(
        kw in text for kw in ["struct", "typedef", "InitStack", "Push(", "Pop(", "GetTop", "BiTNode", "BiTree"]
    )
    if _has_code_keywords:
        from app.features.code_integrity import detect_garbled_code_block
        garbled_result = detect_garbled_code_block(text)
        if garbled_result.is_garbled:
            score += min(0.5, garbled_result.score)
            # Also check for unbalanced braces in code blocks
            open_b = text.count("{")
            close_b = text.count("}")
            if open_b > close_b:
                score += 0.15

    # 6. Fence mention without proper fencing (code indicated but not fenced)
    code_start_patterns = [
        r"\btypedef\s+struct\b",
        r"\bstruct\s+\w+\s*\{",
        r"InitStack\(st\)",
        r"Push\(st,",
        r"Pop\(st,",
        r"GetTop\(st,",
    ]
    if not text.startswith("```"):
        code_hits = sum(1 for p in code_start_patterns if re.search(p, text))
        if code_hits >= 2:
            score += 0.2  # Code-like but not fenced → may need correction

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Structure anomaly detection (多维触发引擎)
# ---------------------------------------------------------------------------


def _detect_structure_abnormal(text: str) -> float:
    """检测 OCR 结果中的结构性异常（不依赖具体乱码字符）。

    五维检测：
    A. 中文占比异常 — 有中文但占比极低时说明识别丢失了中文字符
    B. 异常符号密度 — <-, =:, > > 等非正常考试文本的符号组合
    C. 无意义 ASCII 连续串 — 不含元音的连续小写字母（非英文单词特征）
    D. 选项结构异常 — 短 ASCII 行应匹配选项格式但未匹配
    E. 选项完整性异常 — 选项序列跳缺或数量不足（clean-but-incomplete）

    返回 0.0 ~ 1.0 的分数。
    """
    if not text.strip():
        return 0.0

    total = len(text.strip())
    if total < 5:
        return 0.0  # 太短无法判断

    score = 0.0

    # ---- A. 中文占比异常 ----
    chinese = len(re.findall(r"[一-鿿]", text))
    chinese_ratio = chinese / max(total, 1)
    has_some_chinese = chinese > 0

    if has_some_chinese and chinese_ratio < 0.10 and total > 20:
        score += 0.30  # 确定是中文文本但中文占比极低 → 严重异常
    elif has_some_chinese and chinese_ratio < 0.20 and total > 30:
        score += 0.15  # 中文占比偏低

    # ---- B. 异常符号密度 ----
    symbols = _RE_ABNORMAL_SYMBOLS.findall(text)
    symbol_chars = sum(len(m) for m in symbols)
    symbol_density = symbol_chars / max(total, 1)
    if symbol_density > 0.12:
        score += 0.30
    elif symbol_density > 0.06:
        score += 0.15

    # ---- C. 无意义 ASCII 连续串（不含元音的低位字母串） ----
    runs = _RE_ASCII_RUN.findall(text)
    bad_runs = sum(1 for r in runs if not re.search(r"[aeiou]", r))
    if bad_runs >= 3:
        score += 0.30  # 多个不含元音的"单词" → 极可能乱码
    elif bad_runs >= 1 and len(runs) >= 2:
        score += 0.15

    # ---- D. 选项结构异常 ----
    # 检查短 ASCII 行：如果存在大量短 ASCII 行但都不像选项标记
    lines = text.split("\n")
    ascii_short = [
        ln.strip() for ln in lines
        if 1 < len(ln.strip()) < 15 and not re.search(r"[一-鿿]", ln)
    ]
    if len(ascii_short) >= 3:
        option_like = sum(
            1 for ln in ascii_short
            if re.match(r"^[A-Da-d][.、．）)\s]", ln)
        )
        if option_like < len(ascii_short) * 0.3:
            score += 0.20

    # ---- E. 选项完整性异常（clean-but-incomplete：文本正常但选项缺失） ----
    option_markers = re.findall(r"^([A-D])\s*[.、．）)\s]", text, re.MULTILINE)
    if option_markers:
        present = set(option_markers)

        # 序列跳缺：A→C 跳过 B，或 A→D 缺少 B/C，或 B→D 跳过 C
        if "A" in present and "C" in present and "B" not in present:
            score += 0.30
        if "A" in present and "D" in present and ("B" not in present or "C" not in present):
            score += 0.30
        if "B" in present and "D" in present and "C" not in present:
            score += 0.25

        # 长文本（>150 字符）但选项数 ≤2 → 明显缺失
        if len(text) > 150 and len(present) <= 2:
            score += 0.20

        # 有 A/B/C 但缺 D（考研选择题通常为 4 个选项）
        if present == {"A", "B", "C"} and len(text) > 150:
            score += 0.20

    return min(score, 1.0)


def _should_correct(
    noise_score: float,
    config: dict,
    structure_score: float = 0.0,
    low_confidence: bool = False,
    has_image: bool = False,
) -> bool:
    """多维触发判断：noise OR structure_abnormal OR low_confidence。

    图片场景（has_image=True）降低触发阈值，但不无条件调用。
    """
    mode = config.get("mode", "auto")
    if mode == "never":
        return False
    if mode == "always":
        return True

    # 低置信度直接触发纠错
    if low_confidence:
        return True

    # 合并 noise 和 structure 分数
    combined = max(noise_score, structure_score)

    # 自定义阈值优先（向后兼容现有配置）
    threshold = config.get("noise_threshold")
    if threshold is not None:
        return combined >= threshold

    # 图片场景降低门槛：TIER_HIGH 的 70%
    if has_image:
        return combined >= TIER_HIGH_THRESHOLD * 0.7

    # 默认基于 quality tier（>= MEDIUM 触发）
    tier = _classify_quality_tier(combined)
    return tier in ("MEDIUM", "LOW")


# ---------------------------------------------------------------------------
# Sensitive content filter
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS = [
    (re.compile(r"1[3-9]\d{9}"), "[phone]"),                     # 手机号
    (re.compile(r"\b\d{17}[\dXx]\b"), "[id-number]"),             # 身份证号
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[email]"),
    (re.compile(r"(?:(?:https?|ftp)://|www\.)[^\s，。、；：)]+"), "[url]"),
]

_SENSITIVE_CJK_TERMS: list[re.Pattern] = [
    re.compile(term) for term in [
        r"代[考写发作]",
        r"助考",
        r"作弊",
        r"答案\s*[免免wx微信]",
        r"加\s*[微VQq微信]{1,4}\s*[信信号]?",
    ]
]


def _filter_sensitive(text: str) -> str:
    """过滤敏感内容：替换手机号、邮箱、网址、广告词等。"""
    if not text:
        return text
    for pat, replacement in _SENSITIVE_PATTERNS:
        text = pat.sub(replacement, text)
    for pat in _SENSITIVE_CJK_TERMS:
        text = pat.sub("[sensitive]", text)
    return text


# ── 选项结构修复层 ────────────────────────────────────────────────────
# PaddleOCR-VL 输出有时会去掉 A/B/C/D 前缀（list 格式/LaTeX 污染）。
# 这个函数在 VL 输出作为 fallback 时尝试恢复选项结构。

# 常见无前缀选项文本模式（出现在 VL 输出中）
_OPTION_BARE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "找到头结点 找到尾结点 删除所有节点 逆置链表" → inline list
    (re.compile(r"[，,]\s*(找到|计算|删除|统计|插入|输出|返回|得到|执行|获取|判断|查看|显示|增加|减少|设置)"), None),
    # 换行分隔的列表项（无前缀）
    (re.compile(r"\n([^\n]+?)\n([^\n]+?)\n([^\n]+?)\n([^\n]+?)(?:\n|$)"), None),
]

# LaTeX 污染的选项：数学符号包裹的内容
_LATEX_OPTION = re.compile(r"\$\$\s*([A-Da-d])\s*\..*?\$\$")

# 列表项常见前缀（<li> 标签、- 无序列表等）
_LIST_ITEM_PREFIX = re.compile(r"^[\s]*[•\-*◆◇>]+|\blitem\b|<li[^>]*>|</li>", re.MULTILINE)

# 常见选项种子文本 — 用于在无前缀文本中识别选项边界
_COMMON_OPTION_STEMS = [
    "找到头结点", "找到尾结点", "删除所有节点", "逆置链表",
    "统计所有节点", "统计叶子节点数量", "删除叶子节点", "层序遍历",
    "计算所有元素和", "计算负数和", "计算正数元素之和", "查找最大值",
    "入栈操作", "出栈并输出栈中元素", "判断栈满", "初始化栈",
]


def _repair_latex_options(text: str) -> str:
    """修复 LaTeX 污染的选项标记。

    将 ``$$ A. xxx $$`` 恢复为 ``A. xxx``。
    """
    def _replace_latex(m: re.Match) -> str:
        key = m.group(1)
        rest = m.group(0).replace("$$", "").replace(key, "").strip().lstrip(".）)").strip()
        if rest and len(rest) < 100:
            return f"{key}. {rest}"
        return m.group(0)
    return _LATEX_OPTION.sub(_replace_latex, text)


def _line_is_option_like(line: str) -> bool:
    """检查一行文本是否看起来像是一个选项（有内容但无 A/B/C/D 前缀）。"""
    stripped = line.strip()
    if not stripped:
        return False
    # 已经有 A./B. 前缀的不算"bare"
    import re
    if re.match(r'^[A-Da-d]\s*[.．、:：)）\s]', stripped):
        return False
    # 太短的不算
    if len(stripped) < 2:
        return False
    # 看起来像代码行的不算（包含 C 语言关键词）
    code_keywords = {"int", "char", "void", "return", "if", "while", "for", "printf", "struct", "typedef", "#define", "#include", "LNode", "LinkList"}
    first_word = stripped.split()[0] if stripped.split() else ""
    if first_word in code_keywords or stripped.startswith("#"):
        return False
    # 包含中文（题干/说明行）→ 不算 bare option
    import unicodedata
    if any("一" <= c <= "鿿" or "　" <= c <= "〿" for c in stripped):
        return False
    # 看起来像自然语言选项
    return True


def repair_option_structure(text: str) -> str:
    """修复 PaddleOCR-VL 输出中的选项结构。

    VL 输出常见问题：
    1. **LaTeX 污染**：选项被 ``$$`` 数学符号包裹
    2. **列表化输出**：选项变为无前缀的独立行
    3. **HTML 标签污染**：包含 ``<li>`` 等列表标签

    Returns:
        修复后的文本，尽可能恢复 A./B./C./D. 前缀。
    """
    if not text:
        return text

    original = text

    # Step 1: 清理 HTML/标记标签
    text = _LIST_ITEM_PREFIX.sub("", text)

    # Step 2: 修复 LaTeX 污染的选项
    text = _repair_latex_options(text)

    # Step 3: 如果已经有 detectable options，无需进一步修复
    from app.features.question_type_classifier import detect_options_from_text, extract_options_from_text
    if detect_options_from_text(text):
        return text

    # Step 4: 尝试在无前缀行前恢复 A./B./C./D.
    # 策略：找到连续4行类似选项的文字，按顺序标记为 A/B/C/D
    lines = text.split("\n")
    repaired_lines = []
    bare_option_block: list[int] = []  # 连续无前缀但像选项的行索引

    for i, line in enumerate(lines):
        if _line_is_option_like(line):
            bare_option_block.append(i)
        else:
            # 如果积累了 2-6 条 bare 行，尝试标记为选项
            if 2 <= len(bare_option_block) <= 6:
                keys = ["A", "B", "C", "D", "E", "F"]
                for j, idx in enumerate(bare_option_block):
                    if j < len(keys):
                        lines[idx] = f"{keys[j]}. {lines[idx].strip()}"
            bare_option_block = []

    # 处理文件末尾的 bare 块
    if 2 <= len(bare_option_block) <= 6:
        keys = ["A", "B", "C", "D", "E", "F"]
        for j, idx in enumerate(bare_option_block):
            if j < len(keys):
                lines[idx] = f"{keys[j]}. {lines[idx].strip()}"

    text = "\n".join(lines)

    # Step 5: 如果修复后有了 options，返回修复结果
    if detect_options_from_text(text):
        return text

    # Step 6: 如果修复仍然失败，尝试将已知选项种子文本映射回 A/B/C/D
    # 对 VL 输出的每行，检查是否匹配已知选项
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped in _COMMON_OPTION_STEMS:
            idx = _COMMON_OPTION_STEMS.index(stripped)
            group_idx = idx // 4
            opt_idx = idx % 4
            keys = ["A", "B", "C", "D"]
            lines[i] = f"{keys[opt_idx]}. {stripped}"

    text = "\n".join(lines)

    if detect_options_from_text(text):
        return text

    # 如果所有修复都失败，返回原始文本
    return original
