"""代码块完整性检测 — 在质量问题门禁后、结构化前后调用。

纯规则实现，检测以下代码块结构异常：
- fenced code block 未闭合
- { } 括号不平衡
- ( ) 括号不平衡
- 代码块中混入乱码
- 异常断行（n <=\\n1)）
- 代码块截断（struct/func/if 不完整）
- C/C++ 结构体、函数定义被截断
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 代码块提取 — 从 ``` 围栏中取内容
# ---------------------------------------------------------------------------

_RE_FENCE = re.compile(r"```(\w*)")

# ---------------------------------------------------------------------------
# 括号平衡检测
# ---------------------------------------------------------------------------

_RE_OPEN_BRACE = re.compile(r"\{")
_RE_CLOSE_BRACE = re.compile(r"\}")
_RE_OPEN_PAREN = re.compile(r"\(")
_RE_CLOSE_PAREN = re.compile(r"\)")

# ---------------------------------------------------------------------------
# 乱码模式 — 仅在代码块上下文中判定
# ---------------------------------------------------------------------------

# 连续 4+ 纯辅音字母（无元音 → 无意义）
_RE_CONSECUTIVE_CONSONANTS = re.compile(r"[b-df-hj-np-tv-z]{4,}")

# 混合数字+字母的无意义序列（如 1typu, p1tysI, apo11ta）
_RE_GARBLED_MIXED = re.compile(r"\b[a-zA-Z]+\d+[a-zA-Z]+\b")

# 高频乱码模式（从已知案例提取）
_RE_KNOWN_GARBLED = re.compile(
    r"(?:"
    r"1typu\s*\*|p1tysI|apo11ta|aonu2s"
    r"|snexP|Apxt|(?<![a-zA-Z])ext=q"
    r")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# 异常断行检测 — 操作符与其操作数被拆到两行
# ---------------------------------------------------------------------------

# 行尾只剩操作符（暗示下一行是操作数）
_RE_LINE_END_OPERATOR = re.compile(
    r"(?:<=|>=|!=|==|&&|\|\||[+\-*/%]|->|[=,;])\s*$"
)

# 行首以操作符或右括号开头（暗示上行被截断）
_RE_LINE_START_OPERATOR = re.compile(r"^\s*(?:<=|>=|!=|==|&&|\|\||[+\-*/%]|[)\]}])")

# 单独一行只有 `{` 或 `}`（常见于代码格式化，不视为异常）
_RE_SINGLE_BRACE_LINE = re.compile(r"^\s*[{}]\s*;?\s*$")

# ---------------------------------------------------------------------------
# 截断检测 — 不完整的结构体/函数/控制流
# ---------------------------------------------------------------------------

# C 结构体定义开始（不完整意味着无 "}" 结束）
_RE_STRUCT_DEF = re.compile(r"\b(?:typedef\s+)?struct\s+\w+\s*\{")

# 函数定义开始
_RE_FUNC_DEF = re.compile(r"\b(?:int|void|char|float|double|long|short|Status|bool|ElemType)\s+\*?\w+\s*\(")

# if/while/for 没有闭合大括号（只有 ")" 没有后续 "{"）
_RE_IF_WHILE_FOR = re.compile(r"\b(?:if|while|for)\s*\([^)]*\)\s*\{?")

# 原始文本中存在的但代码块中丢失的闭合 brace
_RE_HAS_OPEN_BLOCK = re.compile(r"\{")
_RE_HAS_CLOSE_BLOCK = re.compile(r"\}")

# ---------------------------------------------------------------------------
# C/C++ 关键词（用于判断文本段是否包含代码）
# ---------------------------------------------------------------------------

_C_CODE_KEYWORDS = frozenset({
    "int", "void", "char", "float", "double", "long", "short", "struct",
    "typedef", "return", "if", "else", "for", "while", "do", "switch",
    "case", "break", "continue", "enum", "union", "const", "static",
    "sizeof", "unsigned", "signed", "NULL", "malloc", "free",
    "printf", "scanf", "true", "false", "include", "define",
    "->", "::",
})

# 代码题信号阈值检测关键词（按信号强度排序）
_CODE_SIGNALS = [
    "typedef", "struct", "class",
    "public:", "private:",
    "return", "void ", "int ", "char ",
    "void*", "int*", "char*",  # 指针形式（void * 会被 "void " 匹配）
    "{", "}", "(", ")",
]

# 408 数据结构关键字
_DS_KEYWORDS = frozenset({
    "LNode", "TNode", "BiTNode", "BiTree", "BSTNode", "LinkList",
    "SqList", "Stack", "Queue", "SqStack", "DeQueue", "ListNode",
    "TreeNode", "LinkedList", "ElemType", "Status",
})


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def contains_code(text: str) -> bool:
    """判断文本是否包含代码。

    检测指标：
    - 存在 ``` 围栏
    - 包含 C/C++ 关键词
    - 包含指针符号 `->`
    - 包含结构体/函数定义模式
    """
    if not text:
        return False
    if "```" in text:
        return True
    if "->" in text:
        return True
    for kw in _C_CODE_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", text):
            return True
    for kw in _DS_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", text):
            return True
    if _RE_STRUCT_DEF.search(text) or _RE_FUNC_DEF.search(text):
        return True
    return False


def is_code_question(text: str) -> bool:
    """基于信号阈值判断是否为代码题。

    使用简单的子串匹配 + 计分方式，检测以下代码信号：
    typedef, struct, class, public:, private:,
    return, void, int, char, {, }, (, )

    当信号计数 >= 4 时判定为代码题。

    相比 contains_code()，此函数更激进（不依赖 word boundary），
    适用于 OCR 输出中关键词可能被污染的场景。
    """
    if not text:
        return False

    score = sum(1 for s in _CODE_SIGNALS if s in text)
    return score >= 4


def compute_code_integrity_score(text: str) -> dict:
    """计算代码完整性分数（0-5 整数分，5=完美）。

    委托 detect_code_block_integrity() 执行实际检测，
    将 0.0-1.0（高=损坏）转换为 0-5（高=完整）格式。

    Returns:
        {
            "score": int,         # 0-5, 5=完整无损坏
            "flags": [str],       # 风险标签
            "details": [str],     # 检测详情
        }
    """
    raw = detect_code_block_integrity(text)
    # 反转分数: 0.0(完美) → 5, 1.0(全损) → 0
    task_score = max(0, 5 - round(raw["score"] * 5))
    return {
        "score": task_score,
        "flags": raw["flags"],
        "details": raw["details"],
    }


def detect_code_block_integrity(text: str) -> dict:
    """检测代码块完整性。

    Args:
        text: 待检测文本（题干或 raw_text）

    Returns:
        {
            "has_code": bool,         # 是否包含代码
            "flags": [str],           # 检测到的风险标签（空列表 = 无风险）
            "details": [str],         # 人类可读的检测详情
            "score": float,           # 0.0 ~ 1.0 代码损坏分数
        }
    """
    if not text:
        return {"has_code": False, "flags": [], "details": [], "score": 0.0}

    has_code = contains_code(text)
    if not has_code:
        return {"has_code": False, "flags": [], "details": [], "score": 0.0}

    flags: list[str] = []
    details: list[str] = []
    score = 0.0

    # 提取代码块内容（fenced）
    code_blocks = _extract_fenced_blocks(text)

    # ---- 确定用于完整性检查的代码内容 ----
    # 有 fence 时仅检查围栏内内容（避免自然语言误报）
    # 无 fence 但有代码时检查整个文本（捕获 OCR 后无围栏代码的损坏）
    has_fenced_blocks = bool(code_blocks["content"])
    code_content = "\n".join(code_blocks["content"])
    if not has_fenced_blocks and has_code:
        code_content = text

    # ---- 1. fenced code block 闭合检测 ----
    if code_blocks["unclosed"]:
        flags.append("code_fence_unclosed")
        score += 0.40
        details.append(f"{len(code_blocks['unclosed'])} 个 fenced code block 未闭合")

    # ---- 2. 大括号平衡检测 ----
    open_braces = len(_RE_OPEN_BRACE.findall(code_content))
    close_braces = len(_RE_CLOSE_BRACE.findall(code_content))
    if open_braces > 0 or close_braces > 0:
        brace_diff = open_braces - close_braces
        if brace_diff > 0:
            flags.append("code_brace_unbalanced")
            score += 0.35
            details.append(f"大括号不平衡: 缺 {brace_diff} 个 '}}'")
        elif brace_diff < 0:
            flags.append("code_brace_unbalanced")
            score += 0.25
            details.append(f"大括号不平衡: 多 {abs(brace_diff)} 个 '}}'")

    # ---- 3. 小括号平衡检测 ----
    open_parens = len(_RE_OPEN_PAREN.findall(code_content))
    close_parens = len(_RE_CLOSE_PAREN.findall(code_content))
    if open_parens > 0 or close_parens > 0:
        paren_diff = open_parens - close_parens
        if abs(paren_diff) >= 2:
            flags.append("code_paren_unbalanced")
            score += 0.20
            details.append(f"括号不平衡: {paren_diff} (open {open_parens}, close {close_parens})")

    # ---- 4. 乱码检测（围栏内 + 代码上下文中的围栏外） ----
    garbled_matches = []
    for block in code_blocks["content"]:
        garbled_matches.extend(_RE_CONSECUTIVE_CONSONANTS.findall(block))
        garbled_matches.extend(_RE_GARBLED_MIXED.findall(block))
        garbled_matches.extend(_RE_KNOWN_GARBLED.findall(block))
    # 当文本中包含代码时，也检测围栏外的乱码模式（案例二: fence 提前闭合后出现乱码）
    if has_fenced_blocks or has_code:
        remaining = _get_unfenced_remaining_text(text, code_blocks)
        garbled_matches.extend(_RE_KNOWN_GARBLED.findall(remaining))
        garbled_matches.extend(_RE_GARBLED_MIXED.findall(remaining))
    if garbled_matches:
        flags.append("code_garbled_text")
        score += 0.40
        details.append(f"代码块中检测到 {len(garbled_matches)} 处疑似乱码")

    # ---- 5. 异常断行检测 ----
    suspicious_break_count = 0
    # 有 fence 时仅检查围栏内内容（避免自然语言误报）
    # 无 fence 时使用 code_content（含自然语言，保守阈值 +1）
    blocks_to_check = list(code_blocks["content"])
    if not has_fenced_blocks and has_code:
        blocks_to_check = [code_content]
    break_threshold = 2 if has_fenced_blocks else 3

    for block in blocks_to_check:
        lines = block.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            # 跳过单 brace 行（代码格式化的正常现象）
            if _RE_SINGLE_BRACE_LINE.match(stripped):
                continue
            # 行尾是操作符/分隔符但下一行存在且非空
            if i + 1 < len(lines) and _RE_LINE_END_OPERATOR.search(stripped):
                next_line = lines[i + 1].strip()
                if next_line and not _RE_SINGLE_BRACE_LINE.match(next_line):
                    suspicious_break_count += 1
            # 行首以操作符开始且上一行非空
            if i > 0 and _RE_LINE_START_OPERATOR.match(stripped):
                prev_line = lines[i - 1].strip()
                if prev_line and not _RE_SINGLE_BRACE_LINE.match(prev_line):
                    suspicious_break_count += 1
    if suspicious_break_count >= break_threshold:
        flags.append("code_line_break_suspicious")
        score += 0.30
        details.append(f"代码块中检测到 {suspicious_break_count} 处异常断行")

    # ---- 6. 截断检测 ----
    # 有结构体定义但没有闭合大括号（检查末尾 100 字符，容纳代码后自然语言说明）
    struct_defs = _RE_STRUCT_DEF.findall(code_content)
    if struct_defs and "}" not in code_content.rstrip()[-100:]:
        flags.append("code_block_truncated")
        score += 0.45
        details.append("结构体定义未闭合（缺少结尾 '}'）")

    # 有函数定义但没有闭合大括号
    func_defs = _RE_FUNC_DEF.findall(code_content)
    if func_defs and open_braces > close_braces:
        flags.append("code_block_incomplete")
        score += 0.40
        details.append("函数定义不完整（大括号未闭合）")

    # if/while/for 后缺少动作
    if_while_count = len(_RE_IF_WHILE_FOR.findall(code_content))
    if if_while_count > 0 and open_braces == 0 and close_braces == 0:
        # 有控制流但完全没有大括号，可能也被截断了
        # 但这种情况也可能是一行代码，需要谨慎
        pass

    # ---- 7. 代码围栏内容截断（fenced 块尾部被截断的启发式） ----
    for content in code_blocks["content"]:
        # 围栏内容以不完整行结尾（首行有内容但末行无结尾标记）
        last_line = content.rstrip().split("\n")[-1].strip()
        if last_line and not last_line.endswith((";", "}", ")", "]", ",", "\"", "'", ">")):
            # 代码行数 > 2 且末行不是正常语句结尾，可能被截断
            lines = content.strip().split("\n")
            if len(lines) >= 3:
                # 检查是否已有其他更严重的 flag
                if "code_block_truncated" not in flags:
                    flags.append("code_block_incomplete")
                    score += 0.25
                    details.append("代码块末尾可能被截断: 末行不以语句结尾")

    # 去重
    flags = list(dict.fromkeys(flags))
    score = round(min(score, 1.0), 2)

    return {
        "has_code": True,
        "flags": flags,
        "details": details,
        "score": score,
    }


def detect_code_regression(raw_text: str, stem: str) -> dict:
    """检测 raw_text 与 stem 之间的代码块退化。

    raw_text 中的代码块在进入 parsed_content/stem 后，
    如果出现截断、拆行、丢失闭合符号等情况，标记为退化。

    Returns:
        {
            "has_regression": bool,
            "flags": [str],
            "details": [str],
            "score": float,
        }
    """
    if not raw_text or not stem:
        return {"has_regression": False, "flags": [], "details": [], "score": 0.0}

    raw_blocks = _extract_fenced_blocks(raw_text)
    stem_blocks = _extract_fenced_blocks(stem)

    # 如果 raw 有 fence 但 stem 没有，可能是退化（长文本被截断）
    if raw_blocks["content"] and not stem_blocks["content"]:
        # 检查 stem 中是否至少有代码关键词
        if contains_code(stem):
            return {"has_regression": False, "flags": [], "details": [], "score": 0.0}
        return {
            "has_regression": True,
            "flags": ["code_structure_regression"],
            "details": ["raw_text 中存在代码围栏但 stem 中完全丢失"],
            "score": 0.50,
        }

    # 逐个对比代码块内容
    for i, raw_block in enumerate(raw_blocks["content"]):
        if i >= len(stem_blocks["content"]):
            # 原始代码块在 stem 中完全消失
            return {
                "has_regression": True,
                "flags": ["code_structure_regression"],
                "details": [f"raw_text 中第 {i + 1} 个代码块在 stem 中消失"],
                "score": 0.45,
            }

        stem_block = stem_blocks["content"][i]

        # 检查围栏中的闭合大括号是否丢失
        raw_close_braces = len(_RE_CLOSE_BRACE.findall(raw_block))
        stem_close_braces = len(_RE_CLOSE_BRACE.findall(stem_block))
        if raw_close_braces > stem_close_braces:
            return {
                "has_regression": True,
                "flags": ["code_structure_regression"],
                "details": [
                    f"raw_text 中代码块有 {raw_close_braces} 个 '}}'，"
                    f"stem 中仅 {stem_close_braces} 个"
                ],
                "score": 0.45,
            }

        # 检查 stem 是否在围栏内混入了不属于代码的乱码
        raw_garbled = _RE_KNOWN_GARBLED.findall(raw_block)
        stem_garbled = _RE_KNOWN_GARBLED.findall(stem_block)
        if len(stem_garbled) > len(raw_garbled) + 1:
            return {
                "has_regression": True,
                "flags": ["code_structure_regression"],
                "details": ["stem 代码块中出现了 raw_text 中不存在的乱码"],
                "score": 0.40,
            }

        # 检查内容级别退化：压缩空白后相同，但存在异常拆行
        raw_compact = re.sub(r"\s+", " ", raw_block.strip())
        stem_compact = re.sub(r"\s+", " ", stem_block.strip())
        if raw_compact == stem_compact:
            # 逐行比对：检查 stem 中是否有 raw 的某一行被拆成两行
            raw_code_lines = raw_block.strip().split("\n")
            stem_code_lines = stem_block.strip().split("\n")
            si = 0
            for raw_line in raw_code_lines:
                if si >= len(stem_code_lines):
                    break
                raw_s = raw_line.strip()
                stem_s = stem_code_lines[si].strip()
                if raw_s == stem_s:
                    si += 1
                    continue
                # 尝试合并两行 stem 重建 raw 行（拆行退化模式）
                if si + 1 < len(stem_code_lines):
                    combined = stem_s + " " + stem_code_lines[si + 1].strip()
                    if combined == raw_s:
                        # 区分 OCR 损坏 vs 合法格式化：
                        # OCR 损坏的续行没有缩进（紧贴行首），合法格式化有缩进
                        next_line_raw = stem_code_lines[si + 1]
                        no_indent = not next_line_raw.startswith((" ", "\t"))
                        if no_indent:
                            return {
                                "has_regression": True,
                                "flags": ["code_structure_regression"],
                                "details": [
                                    f"代码块内容退化: '{raw_s[:40]}' "
                                    f"被拆成 '{stem_s[:30]}' + "
                                    f"'{stem_code_lines[si + 1].strip()[:30]}'"
                                ],
                                "score": 0.40,
                            }
                si += 1

    return {"has_regression": False, "flags": [], "details": [], "score": 0.0}


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------


def _extract_fenced_blocks(text: str) -> dict:
    """提取所有 fenced code block 的内容。

    Returns:
        {
            "content": [str],      # 每个围栏内的代码文本
            "unclosed": [str],     # 未闭合围栏的片段
        }
    """
    parts = re.split(r"(```)", text)
    content: list[str] = []
    unclosed: list[str] = []

    i = 0
    while i < len(parts):
        if parts[i] == "```":
            # 检查是否走到末尾（未闭合）
            if i + 1 >= len(parts):
                unclosed.append("")
                break
            fence_content = parts[i + 1]
            if fence_content == "```":
                # 空块或围栏结束标记紧跟开始标记
                content.append("")
                i += 2
                continue
            # 检查围栏是否闭合
            if i + 2 < len(parts) and parts[i + 2] == "```":
                content.append(fence_content)
                i += 3
            else:
                # 围栏未闭合 — fence_content 实际是文本剩余部分
                unclosed.append(fence_content)
                break
        else:
            i += 1

    return {
        "content": content,
        "unclosed": unclosed,
    }


def reconstruct_code_block(lines: list[str]) -> str:
    """Reconstruct a truncated code block by merging lines.

    Detection triggers (code start):
    - contains: ``for``, ``while``, ``if``, ``struct``, ``typedef``

    Then merges subsequent lines until:
    - braces are balanced ({ == }), OR
    - blank line encountered, OR
    - question boundary detected (next number marker)

    Returns the reconstructed code block string.
    """
    if not lines:
        return ""

    code_lines: list[str] = []
    in_code = False
    open_braces = 0
    close_braces = 0

    # Code start signals
    _CODE_START_RE = re.compile(
        r"\b(for|while|if|struct|typedef)\b"
    )

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_code:
                # blank line ends code block
                break
            continue

        if not in_code:
            if _CODE_START_RE.search(stripped):
                in_code = True
                code_lines.append(line)
                open_braces += stripped.count("{")
                close_braces += stripped.count("}")
                if open_braces > 0 and open_braces == close_braces:
                    break
                continue
            else:
                continue

        # In code: check for question boundary (number marker at line start)
        if re.match(r"^\d+\s*[.、)）]", stripped):
            break

        code_lines.append(line)
        open_braces += stripped.count("{")
        close_braces += stripped.count("}")

        if open_braces > 0 and open_braces == close_braces:
            break

    return "\n".join(code_lines)


def fix_braces(code: str, confidence: float = 1.0) -> str:
    """Fix unbalanced braces in code.

    Auto-closes ``{`` with ``}`` only if confidence < 0.8.

    Args:
        code: The code text (may be inside or outside fence markers).
        confidence: Integrity confidence score (0.0-1.0). Only auto-fix below 0.8.

    Returns:
        Code string with balanced braces.
    """
    if not code or confidence >= 0.8:
        return code

    open_braces = code.count("{")
    close_braces = code.count("}")

    if open_braces > close_braces:
        code += "\n" + "}" * (open_braces - close_braces)

    return code


def classify_line(line: str) -> str:
    """Classify a line as ``"code"`` or ``"text"``.

    Scoring:
    - code_score: line contains ``{``, ``->``, ``;``, ``struct``, ``int``, ``for``
    - text_score: natural language patterns (Chinese chars, sentence ends)

    Rule:
    - code_score > 0.6 → ``"code"``
    - else → ``"text"``

    Args:
        line: A single line of text.

    Returns:
        ``"code"`` or ``"text"``.
    """
    if not line or not line.strip():
        return "text"

    stripped = line.strip()
    total_len = len(stripped)
    if total_len == 0:
        return "text"

    # Code signals
    _CODE_SIGNALS_WEIGHTED = {
        "{": 0.3, "}": 0.2,
        "->": 0.3,
        ";": 0.25,
        "struct": 0.35,
        "typedef": 0.35,
        "int ": 0.25,
        "char ": 0.25,
        "void ": 0.25,
        "float ": 0.25,
        "double ": 0.25,
        "for ": 0.25,
        "while ": 0.25,
        "if ": 0.2,
        "return ": 0.25,
        "NULL": 0.2,
        "malloc": 0.3,
        "printf": 0.25,
        "//": 0.15,
        "sizeof": 0.25,
        "!=": 0.1,
        "==": 0.1,
    }

    code_score = 0.0
    for signal, weight in _CODE_SIGNALS_WEIGHTED.items():
        if signal in stripped:
            code_score += weight

    # Text signals (natural language)
    has_cjk = any("一" <= c <= "鿿" for c in stripped)
    text_score = 0.0
    if has_cjk:
        text_score += 0.4
    if stripped.endswith(("。", "？", "！", "；", "。")):
        text_score += 0.3
    if re.search(r"[的得地是在了着过被把对于]", stripped):
        text_score += 0.2
    if re.search(r"[一-鿿]{4,}", stripped):
        text_score += 0.3
    # Short lines with CJK are text
    if has_cjk and total_len < 20:
        text_score += 0.2

    # Newline check: non-CJK code lines often end without punctuation
    if not has_cjk and not stripped.endswith((".", "?", "!", ";")):
        code_score += 0.1

    return "code" if code_score >= 0.5 else "text"


def fix_tree_recursion_breaks(text: str) -> str:
    """Fix fragmented tree recursion code by merging split conditions.

    Detects patterns split across lines:
    - ``if (T->lchild == NULL`` followed by ``T->rchild == NULL)``
    - ``if (T->lchild != NULL`` / ``T->rchild != NULL)``
    - ``while (p->next != NULL`` / ``p != NULL)``

    Ensures the full condition stays on one logical line.

    Args:
        text: Code text possibly with split recursion conditions.

    Returns:
        Fixed text with conditions merged.
    """
    if not text:
        return text

    lines = text.split("\n")
    result: list[str] = []
    i = 0

    # Pattern: first line ends with a condition fragment
    _COND_START_RE = re.compile(
        r"(?:if|while|else\s+if)\s*\([^)]*$"
    )
    _COND_CONT_RE = re.compile(r"^\s*(?:[A-Za-z_][\w*]*)\s*(?:->|\.)\s*(?:lchild|rchild|next|prior|data|key)\s*(?:==|!=)\s*(?:NULL|null|0)\s*\)?\s*\{?\s*$")
    _PTR_COND_MID_RE = re.compile(r"^\s*(?:&&|\|\|)\s*$")

    while i < len(lines):
        current = lines[i]
        stripped = current.strip()

        # Detect: line ends with an incomplete tree condition
        if _COND_START_RE.search(stripped):
            # Peek ahead: merge subsequent lines until the closing paren
            merged = current
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                if not next_stripped:
                    break
                # Stop at question boundary
                if re.match(r"^\d+\s*[.、)）]", next_stripped):
                    break
                # Stop if next line starts a new statement (not a continuation)
                if re.match(r"^(?:if|while|for|return|struct)\b", next_stripped) and j > i + 1:
                    break
                merged = merged.rstrip() + " " + next_stripped
                j += 1
                # Check if we've found the closing paren
                open_parens = merged.count("(") - merged.count(")")
                if open_parens <= 0:
                    break
            result.append(merged)
            i = j
            continue

        # Detect: line is a dangling condition mid (&& or || alone)
        if _PTR_COND_MID_RE.match(stripped):
            if result:
                # Merge with previous
                prev = result.pop()
                merged = prev.rstrip() + " " + stripped
                # Continue merging next lines
                j = i + 1
                while j < len(lines):
                    next_stripped = lines[j].strip()
                    if not next_stripped:
                        break
                    if re.match(r"^\d+\s*[.、)）]", next_stripped):
                        break
                    merged = merged + " " + next_stripped
                    j += 1
                    open_parens = merged.count("(") - merged.count(")")
                    if open_parens <= 0:
                        break
                result.append(merged)
                i = j
                continue

        result.append(current)
        i += 1

    return "\n".join(result)


def _get_unfenced_remaining_text(text: str, fenced_result: dict) -> str:
    """获取围栏外剩余的文本片段（用于围栏闭合后紧跟的乱码检测）。"""
    if not fenced_result["content"] and not fenced_result["unclosed"]:
        return text
    # 移除所有围栏内容以得到剩余文本
    remaining = text
    for content in fenced_result["content"]:
        remaining = remaining.replace(f"```{content}```", "", 1)
    for unclosed in fenced_result["unclosed"]:
        remaining = remaining.replace(f"```{unclosed}", "", 1)
    return remaining


# ── Garbled code block detection (P0: Problem A from audit) ──
from dataclasses import dataclass, field


@dataclass
class CodeGarbledResult:
    """Result of garbled code block detection."""
    is_garbled: bool
    score: float
    reasons: list[str]
    expected_language: str | None


# C struct field declaration pattern
_RE_C_FIELD_DECL = re.compile(
    r"\b(struct\s+\w+\s*\*?\s*\w+|"
    r"char\s+\w+|int\s+\w+|float\s+\w+|double\s+\w+|"
    r"void\s*\*?\s*\w+|"
    r"\w+\s+\*?\w+\s*;|"
    r"\w+\s+\*?\w+\s*,\s*\*?\w+)"  # multi-decl like "lchild, *rchild"
)

# C struct definition markers
_RE_STRUCT_TYPEDEF = re.compile(r"typedef\s+struct")
_RE_STRUCT_DEF_OPEN = re.compile(r"struct\s+\w+\s*\{")
_RE_STRUCT_DEF_CLOSE = re.compile(r"\}\s*\w+\s*,\s*\*?\w+\s*;")

# Garbled token patterns
_RE_GARBLED_TOKEN = re.compile(
    r"(?:"
    r"\d+[a-zA-Z]{2,}\d*|"     # digits followed by letters: 1typu
    r"[a-zA-Z]+\d+[a-zA-Z]+|"  # letters-digits-letters: p1tysI, apo11ta
    r"[a-z]{5,}[A-Z]\w*|"       # lowercase-heavy with cap in middle
    r"[A-Z][a-z]{0,2}\d{2,}"   # single cap + digits: P2s → but NOT P_2
    r")"
)

# High-specificity known garbled patterns from production cases
_RE_KNOWN_GARBLED_CODE = re.compile(
    r"(?:"
    r"1typu\s*\*|p1tysI|apo11ta|aonu2s"
    r"|snexP|Apxt|ext=q"
    r"|\(\s*\d+\s*typu|tysI"  # C field with embedded noise
    r")",
    re.IGNORECASE,
)


def detect_garbled_code_block(code: str) -> CodeGarbledResult:
    """Detect garbled code in a code block.

    Checks for:
    1. C struct body validation — if typedef struct is present, verify
       field declarations are semantically valid
    2. Abnormal token density — mixed digit-letter tokens
    3. Known garbled patterns from production cases

    Args:
        code: The code text (may include fenced block markers or just content).

    Returns:
        CodeGarbledResult with is_garbled flag, score (0-1), reasons, language.
    """
    if not code or not code.strip():
        return CodeGarbledResult(
            is_garbled=False, score=0.0, reasons=[], expected_language=None,
        )

    reasons: list[str] = []
    score = 0.0
    expected_language = None

    # Remove fence markers for detection
    clean_code = re.sub(r"```\w*\n?|```", "", code).strip()

    # 1. C struct body validation
    has_typedef = bool(_RE_STRUCT_TYPEDEF.search(clean_code))
    has_struct_open = bool(_RE_STRUCT_DEF_OPEN.search(clean_code))
    has_struct_close = bool(_RE_STRUCT_DEF_CLOSE.search(clean_code))

    if has_typedef and has_struct_open:
        expected_language = "c"
        # Extract struct body lines (between { and })
        struct_body = ""
        in_body = False
        for line in clean_code.split("\n"):
            stripped = line.strip()
            if "{" in stripped:
                in_body = True
                body_part = stripped[stripped.index("{")+1:]
                if body_part:
                    struct_body += body_part + "\n"
                continue
            if "}" in stripped:
                in_body = False
                body_part = stripped[:stripped.index("}")]
                if body_part.strip():
                    struct_body += body_part + "\n"
                continue
            if in_body:
                struct_body += stripped + "\n"

        if struct_body.strip():
            # Count valid field declarations
            valid_fields = _RE_C_FIELD_DECL.findall(struct_body)
            # Check for garbled content
            garbled_matches = _RE_GARBLED_TOKEN.findall(struct_body)
            known_garbled = _RE_KNOWN_GARBLED_CODE.findall(struct_body)

            if not valid_fields and garbled_matches:
                reasons.append("c_struct_body_garbled")
                score = max(score, 0.45)
            if known_garbled:
                reasons.append("known_garbled_pattern")
                score = max(score, 0.50)

            # Check if struct body lines look like field declarations
            struct_lines = [l for l in struct_body.split("\n") if l.strip()]
            garbled_line_count = 0
            for sl in struct_lines:
                # Valid C field: type name; or type name, *name;
                if not re.match(
                    r"^\s*(?:struct\s+\w+|char|int|float|double|void|short|long)"
                    r"\s+\*?\w+(?:\s*,\s*\*?\w+)*\s*;?\s*$",
                    sl,
                ):
                    # Count as garbled if it doesn't look like a valid field
                    if len(sl.strip()) >= 5:  # only meaningful lines
                        garbled_line_count += 1

            if struct_lines and garbled_line_count / len(struct_lines) > 0.5:
                if "c_struct_body_garbled" not in reasons:
                    reasons.append("c_struct_body_garbled")
                score = max(score, 0.55)

    # 2. General garbled token detection (any code)
    garbled_tokens = _RE_GARBLED_TOKEN.findall(clean_code)
    if len(garbled_tokens) >= 2:
        reasons.append("garbled_code_token_density_high")
        score = max(score, 0.35)
    known_garbled = _RE_KNOWN_GARBLED_CODE.findall(clean_code)
    if known_garbled:
        if "known_garbled_pattern" not in reasons:
            reasons.append("known_garbled_pattern")
        score = max(score, 0.40)

    # 3. Check for unbalanced braces
    open_braces = clean_code.count("{")
    close_braces = clean_code.count("}")
    if has_typedef and open_braces > close_braces:
        reasons.append("c_struct_missing_close_brace")
        score = max(score, 0.30)

    # 4. Check for code that has struct keyword but no valid field declarations
    if "struct" in clean_code.lower() and not has_struct_open and not has_struct_close:
        reasons.append("c_struct_syntax_incomplete")
        score = max(score, 0.35)

    is_garbled = score >= 0.3
    score = round(min(score, 1.0), 2)

    return CodeGarbledResult(
        is_garbled=is_garbled,
        score=score,
        reasons=list(dict.fromkeys(reasons)),  # deduplicate
        expected_language=expected_language,
    )
