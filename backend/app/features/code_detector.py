"""代码块检测器 — 规则层。

在 OCR 原始文本上检测代码块，插入 ``` 围栏。
必须在任何空格压缩、换行合并之前运行。

约束：
- 关键词不能单独触发（必须 struct_score ≥ 1）
- 单行不触发（必须连续 ≥2 行命中）
- Flag 关闭时透传
- 调用后输出结构化命中日志
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.core.config import settings

logger = logging.getLogger(__name__)

# ============================================================
# 结构信号 — 语言无关
# ============================================================

# 行首缩进 ≥2 空格（OCR 原始文本保留的缩进）
_RE_INDENT = re.compile(r"^[ ]{2,}\S")

# 行尾分号（C/Java/JS 语句终止符）
_RE_SEMICOLON_END = re.compile(r";\s*$")

# 独立 brace 行（含 }; 等终止符）
_RE_BRACE_LINE = re.compile(r"^\s*[{}];?\s*$")

# 行尾 brace（} 或 { 出现在行尾位置，其后仅允许 ; 和空格）
_RE_BRACE_END = re.compile(r"[{}]\s*;?\s*$")

# C 风格运算符
_RE_C_OPERATORS = re.compile(
    r"->|::|\+\+|--|&&|\|\||==|!=|<=|>=|\+=|-=|\*=|/=|%=|<<|>>"
)

# Python 冒号结尾（函数/类/循环定义行）
_RE_COLON_END = re.compile(r":\s*$")

# 角括号结构 — HTML/XML 标签或 C++ 模板
_RE_ANGLE_BRACKETS = re.compile(r"</?[a-zA-Z_]\w*\b")

# SQL 行首大写关键词（强结构约定）
_RE_SQL_LINE_START = re.compile(r"^\s*(?:SELECT|FROM|WHERE|INSERT|UPDATE|DELETE"
    r"|CREATE|DROP|ALTER|ORDER\s+BY|GROUP\s+BY|HAVING|JOIN"
    r"|LEFT\s+JOIN|INNER\s+JOIN|UNION|DISTINCT)\b")

# ============================================================
# 关键词信号 — 分语言
# ============================================================

# 通用编程关键词（\b 边界匹配，避免中文子串误判）
# 这些词在编程语境中极常见，在中文题干中极少独立出现
_COMMON_KW = (
    r"\b(?:"
    r"for|while|if|else|switch|case|return|break|continue|do|goto"
    r"|int|float|double|char|void|long|short|struct|enum|union"
    r"|typedef|const|static|sizeof|unsigned|signed"
    r"|class|public|private|protected|new|extends|implements|interface|abstract"
    r"|def|import|from|lambda|yield|raise|except|try|finally|with|elif|pass"
    r"|function|var|let|const|console|async|await|export"
    r"|printf|scanf|malloc|free|NULL|true|false|include|define"
    r"|cout|endl|cin|iterator|namespace|template|typename|virtual|override"
    r"|int\s*\*|char\s*\*|void\s*\*"  # pointer type patterns in 408 C code
    r"|ListNode|TreeNode|LinkedList|LNode|TNode|BiTree|BSTNode"
    r"|BiTNode|LinkList|SqList|Stack|Queue|DeQueue|SqStack"
    r"|ElemType|ElemType\s*\*|Status|bool|NULL|nullptr"
    r")\b"
)
_RE_COMMON_KW = re.compile(_COMMON_KW)

# SQL 关键词（大写，高特异性）
_RE_SQL_KW = re.compile(
    r"\b(?:SELECT|FROM|WHERE|INSERT\s+INTO|UPDATE|DELETE\s+FROM"
    r"|CREATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE"
    r"|ORDER\s+BY|GROUP\s+BY|HAVING|JOIN|LEFT\s+JOIN|INNER\s+JOIN"
    r"|UNION|DISTINCT|COUNT|SUM|AVG|MAX|MIN)\b"
)

# HTML/XML 标签
_RE_HTML_TAG = re.compile(
    r"</?(?:html|div|span|table|tr|td|th|body|head|p|a|ul|ol|li"
    r"|script|style|meta|link|input|form|button|h[1-6])\b"
)

# Python 函数定义（高特异性：def 跟标识符跟括号）
_RE_PYTHON_DEF = re.compile(r"^\s*def\s+\w+\s*\(")

# Java/C++ 类定义
_RE_CLASS_DEF = re.compile(r"^\s*(?:public\s+)?class\s+\w+")

# Java main 方法
_RE_JAVA_MAIN = re.compile(r"public\s+static\s+void\s+main")

# ============================================================
# 误判防护 — 不应触发的中文模式
# ============================================================

# 含 CJK 字符的行通常在中文语境中，需更高阈值
_RE_CJK = re.compile(r"[一-鿿]")

# 中文题干常见模式（即使含英文关键词也不应触发）
_CN_QUESTION_PATTERNS = (
    "下列", "以下", "正确", "错误", "的是", "哪一", "选择",
    "判断", "计算", "已知", "设", "若", "求", "问",
    "根据", "按照", "关于", "对于", "下列选项",
)


# ============================================================
# 检测统计
# ============================================================

@dataclass
class CodeDetectStats:
    """代码检测统计"""
    question_count: int = 0
    block_count: int = 0
    total_code_lines: int = 0
    languages: dict[str, int] = field(default_factory=dict)

    @property
    def avg_code_lines(self) -> float:
        if self.block_count == 0:
            return 0.0
        return self.total_code_lines / self.block_count

    def to_log(self, trace_id: str = "") -> str:
        langs = ",".join(f"{k}:{v}" for k, v in sorted(self.languages.items())) or "none"
        return (
            f"[CodeDetector] trace_id={trace_id} "
            f"questions={self.question_count} blocks={self.block_count} "
            f"avg_lines={self.avg_code_lines:.1f} languages={langs}"
        )


# ============================================================
# 公开接口
# ============================================================


def wrap_code_fences(text: str, *, trace_id: str = "") -> str:
    """在 OCR 原始文本上检测代码块并插入 ``` 围栏。

    Flag 关闭时透传，行为与线上完全一致。
    """
    if not settings.CODE_DETECTOR_ENABLED:
        return text

    result, stats = _detect_and_wrap(text)
    logger.info(stats.to_log(trace_id))
    return result


# ============================================================
# 内部实现
# ============================================================


def _detect_and_wrap(text: str) -> tuple[str, CodeDetectStats]:
    """检测代码块并包裹围栏，返回 (result_text, stats)。"""
    if not text or "\n" not in text:
        return text, CodeDetectStats()

    # 先按已有围栏切分，保护已存在围栏区域
    parts = re.split(r"(```[\s\S]*?```)", text)

    stats = CodeDetectStats()
    result: list[str] = []

    for i, part in enumerate(parts):
        if part.startswith("```"):
            result.append(part)
        else:
            fenced, part_stats = _fence_code_blocks(part)
            result.append(fenced)
            stats.question_count += part_stats.question_count
            stats.block_count += part_stats.block_count
            stats.total_code_lines += part_stats.total_code_lines
            for lang, cnt in part_stats.languages.items():
                stats.languages[lang] = stats.languages.get(lang, 0) + cnt

    return "".join(result), stats


def _fence_code_blocks(text: str) -> tuple[str, CodeDetectStats]:
    """在单个文本块中检测并包裹代码区域。"""
    lines = text.split("\n")
    n = len(lines)

    # Step 1: 逐行打分
    scores: list[int] = []  # 0 = 非代码, 1+ = 代码信号强度
    for line in lines:
        scores.append(_score_line(line))

    # Step 1.5: 桥接单行低分噪声，防止代码块因单行乱码断裂
    for i in range(1, n - 1):
        if scores[i] == 0 and scores[i - 1] >= 1 and scores[i + 1] >= 1:
            scores[i] = 1

    # Step 2: 找连续 ≥2 行且每行 score ≥ 1 的区域
    in_block = False
    block_start = 0
    result: list[str] = []
    stats = CodeDetectStats()
    block_count = 0

    for i in range(n + 1):
        is_code = i < n and scores[i] >= 1

        if is_code and not in_block:
            in_block = True
            block_start = i
        elif not is_code and in_block:
            in_block = False

            # 检查是否有前导空行（向上追溯到非空行）
            while block_start > 0 and not lines[block_start - 1].strip():
                block_start -= 1

            # 向后扩展：将代码块前的 # 预处理指令和 typedef 行纳入 fence
            while block_start > 0:
                prev = lines[block_start - 1].strip()
                if prev.startswith("#") and not _RE_CJK.search(prev):
                    block_start -= 1
                elif prev.startswith("typedef"):
                    block_start -= 1
                else:
                    break

            block_len = i - block_start

            if block_len >= 2:
                # 排除已在围栏内的内容
                code_lines = lines[block_start:i]
                block_count += 1
                stats.block_count += 1
                stats.total_code_lines += len(code_lines)
                lang = "text"
                stats.languages[lang] = stats.languages.get(lang, 0) + 1

                result.append(f"```{lang}")
                result.extend(code_lines)
                result.append("```")
                stats.question_count = 1 if block_count >= 1 else 0
            else:
                result.extend(lines[block_start:i])

        if not in_block and i < n:
            result.append(lines[i])

    return "\n".join(result), stats


def _score_line(line: str) -> int:
    """对单行打分。返回 ≥1 表示该行被判定为代码行。

    约束：关键词不能单独触发（关键词命中但无结构信号时返回 0）。
    """
    stripped = line.strip()
    if not stripped:
        return 0

    # ── 结构信号 ──
    struct_score = 0

    # 缩进在 OCR 文本中几乎只出现在代码块中（中文段落不缩进）
    if _RE_INDENT.match(line):
        struct_score += 2
    if _RE_SEMICOLON_END.search(stripped):
        struct_score += 1
    if _RE_BRACE_LINE.match(stripped):
        struct_score += 1
    if _RE_BRACE_END.search(stripped):
        struct_score += 1
    if _RE_C_OPERATORS.search(stripped):
        struct_score += 1
    if _RE_ANGLE_BRACKETS.search(stripped):
        struct_score += 1
    if _RE_SQL_LINE_START.search(stripped):
        struct_score += 1
    # C++ 访问修饰符 / switch case 标签 / goto 标签（冒号结尾 + 关键词上下文）
    if _RE_COLON_END.search(stripped) and not _RE_CJK.search(stripped):
        struct_score += 1
    # C 预处理器指令（#define, #include, #ifdef 等） — 仅当无 CJK 时免误判
    if stripped.startswith("#") and not _RE_CJK.search(stripped):
        struct_score += 1

    # ── 关键词信号 ──
    keyword_score = 0

    if _RE_COMMON_KW.search(stripped):
        keyword_score += 1
    if _RE_SQL_KW.search(stripped):
        keyword_score += 1
    if _RE_HTML_TAG.search(stripped):
        keyword_score += 1
    if _RE_PYTHON_DEF.search(stripped):
        keyword_score += 1
    if _RE_CLASS_DEF.search(stripped):
        keyword_score += 1
    if _RE_JAVA_MAIN.search(stripped):
        keyword_score += 1

    # ── 双重判断 ──
    # 关键词不能单独触发：必须有 struct_score ≥ 1
    # struct_score ≥ 2 时即使无关键词也触发（纯结构代码如独立 brace 行）
    if struct_score >= 2:
        return struct_score
    if struct_score >= 1 and keyword_score >= 1:
        return struct_score + keyword_score

    # ── Python 冒号结尾特殊处理 ──
    # def/class 定义行的冒号是强信号
    if _RE_COLON_END.search(stripped) and (_RE_PYTHON_DEF.search(stripped) or _RE_CLASS_DEF.search(stripped)):
        return 2

    return 0


# ============================================================
# P1 post-pass: 未闭合围栏修复
# ============================================================

# 最大 fence 扩展行数 — 防止吞噬选项行/噪声
_FENCE_EXTENSION_LIMIT = 15


def _is_valid_fence_extension(line: str) -> bool:
    """判断是否可以将 line 纳入 fence 扩展。

    保守策略：仅当行有明确代码信号时才允许扩展。
    不满足则终止扩展（防止吞入选项行 A.、噪声乱码等）。
    """
    stripped = line.strip()
    if not stripped:
        return False  # 空行不扩展

    # 强信号：大括号（最常见的 fence 未闭合场景 — 缺少闭合 }）
    if "{" in stripped or "}" in stripped:
        return True

    # 行首缩进 ≥2 空格（代码延续的典型特征）
    if re.match(r"^[ ]{2,}\S", line):
        return True

    # 行尾分号（语句继续）
    if re.search(r";\s*$", stripped):
        return True

    # 预处理器 / typedef 延续
    if re.match(r"^\s*(?:#|typedef|using|namespace)", stripped):
        return True

    # C 风格运算符承接
    if re.search(r"^(?:&&|\|\||->|\.)", stripped.lstrip()):
        return True

    # 代码关键词行（return/break/continue/case/default）
    if re.match(r"^\s*(?:return|break|continue|case\s|default\s*:)", stripped):
        return True

    return False


def repair_unclosed_fences(text: str, *, trace_id: str = "") -> str:
    """P1 post-pass: 修复未闭合代码围栏。

    检查每个 fenced block 的 {} 平衡。如果 { 多于 }，
    谨慎扩展 fence 边界以包含后续行，直到括号平衡或遇到非代码行。

    扩展是保守的：仅当后续行有代码信号（}、{、缩进、分号等）时
    才纳入，且最多扩展 _FENCE_EXTENSION_LIMIT 行，避免吞入选项/噪声。

    Args:
        text: 经过 wrap_code_fences() 处理后的文本。
        trace_id: 可选的跟踪 ID。

    Returns:
        修复围栏边界后的文本（无修复时原样返回）。
    """
    if not text or "```" not in text:
        return text

    FENCE_PATTERN = re.compile(r"(```[\s\S]*?```)")
    parts = FENCE_PATTERN.split(text)

    result: list[str] = []
    i = 0
    while i < len(parts):
        part = parts[i]
        if part.startswith("```") and part.count("```") == 2:
            fence_content = _extract_fence_content(part)
            open_braces = fence_content.count("{")
            close_braces = fence_content.count("}")
            deficit = open_braces - close_braces

            if deficit > 0 and i + 1 < len(parts):
                merged = part.rstrip()
                if merged.endswith("```"):
                    merged = merged[:-3].rstrip()

                next_part = parts[i + 1]
                if not next_part.startswith("```"):
                    lines = next_part.split("\n")
                    consumed = 0
                    for k, line in enumerate(lines):
                        if not _is_valid_fence_extension(line):
                            break  # 非代码行，停止扩展
                        if consumed >= _FENCE_EXTENSION_LIMIT:
                            break  # 达到上限，防止过度扩展
                        merged += "\n" + line
                        consumed += 1
                        deficit -= line.count("{")
                        deficit += line.count("}")
                        if deficit <= 0:
                            break

                    if consumed > 0:
                        merged += "\n```"
                        remaining = lines[consumed:]
                        if remaining and any(l.strip() for l in remaining):
                            result.append(merged)
                            parts[i + 1] = "\n".join(remaining)
                        else:
                            result.append(merged)
                            i += 1
                    else:
                        result.append(part)
                else:
                    result.append(part)
            else:
                result.append(part)
        else:
            result.append(part)
        i += 1

    return "".join(result)


def _extract_fence_content(fence_part: str) -> str:
    """从 fence 块中提取内容（不含 ``` 标记和语言标签）。"""
    lines = fence_part.split("\n")
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1])
    return lines[-1] if len(lines) > 1 else ""
