"""PDF 文本行合并与标准化。

职责：将 PDF / OCR 提取的视觉换行文本恢复为语义连续段落。
仅处理文本；不做任何题目解析逻辑。
"""
import re

from app.features.roman_schema import _ROMAN_SUBITEM_TOKEN

# 行首结构标记正则（这些行不能被合并到上一行）
_STRUCTURE_LINE_RE = re.compile(
    r"^("
    r"\d+\s*[.、)）]"
    r"|[A-D]\s*[.、:：]"
    r"|[（(]\s*[A-D]\s*[）)]"                          # （A）(A)（A ）( A )
    r"|" + _ROMAN_SUBITEM_TOKEN + r"\s*[.、)）]"
    r"|(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:]"
    r"|(?:【)?(?:解析|解答)(?:】)?\s*[：:]"
    r"|(?:[（(]\s*(?:单选|多选|选择|填空|判断|简答|论述|计算)题?[）)])"
    r")"
)

# 上一行是结构行（选项/答案/解析/题号）时，下一行不允许向上合并
_PREV_STRUCTURE_LINE_RE = re.compile(
    r"^("
    r"\d+\s*[.、)）]"
    r"|[A-D]\s*[.、:：\s].+"      # 选项行（A. xxx 格式，后面必须有内容）
    r"|[（(]\s*[A-D]\s*[）)].+"
    r"|(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:].+"
    r"|(?:【)?(?:解析|解答)(?:】)?\s*[：:].+"
    r")"
)

# 独立数学表达式行：以运算符/函数/极限符号打头，不向上合并（避免粘连加剧）
_MATH_LINE_RE = re.compile(
    r"^("
    r"[+\-×÷=≥≤≠∞∫∑∏√]"        # 运算符打头
    r"|lim\b|sin\b|cos\b|tan\b|ln\b|log\b"  # 数学函数
    r"|\\[a-zA-Z]"                              # LaTeX 命令
    r")"
)

# 上一行末尾出现这些字符说明句子已完结，不应合并
_SENTENCE_END = frozenset("。！？；…，,")


def _should_merge(prev: str, curr: str) -> bool:
    """判断 curr 行是否应拼接到 prev 行末尾。"""
    if not prev or not curr:
        return False
    if _STRUCTURE_LINE_RE.match(curr):
        return False
    if prev[-1] in _SENTENCE_END:
        return False
    # 选项行双重保险
    if re.match(r"^[A-D][.、:：\s]", curr):
        return False
    # 独立数学行不向上合并，保持可读性
    if _MATH_LINE_RE.match(curr):
        return False
    # 上一行是完整的选项/答案/解析行时，不允许后续行合并进来
    # 这防止双层PDF的重复行（如"A. 1\n1"中的"1"）被错误拼接为"A. 11"
    if _PREV_STRUCTURE_LINE_RE.match(prev):
        return False
    return True


def merge_broken_lines(text: str) -> str:
    """合并 PDF 视觉断行，恢复语义连续段落。"""
    lines = text.split("\n")
    result: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            result.append("")
            continue

        if not result or result[-1] == "":
            result.append(line)
        elif _should_merge(result[-1], line):
            result[-1] += line
        else:
            result.append(line)

    merged = "\n".join(result)
    merged = re.sub(r"\n{3,}", "\n\n", merged)
    return merged.strip()


def normalize_spaces(text: str) -> str:
    """归一化空白字符：全角空格→半角，连续空格→单个，行首尾空格去除。"""
    text = text.replace("　", " ").replace("\xa0", " ")
    lines = [re.sub(r"  +", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(lines)


def deduplicate_repeated_text(text: str) -> str:
    """折叠"完全重复的上下拼接"文本，不误伤正常内容。

    处理模式：
    - "abc\\nabc"        → "abc"
    - "1\\n1"            → "1"
    - "abc\\ndef\\nabc\\ndef" → "abc\\ndef"
    - "abc\\ndef"        → 不变（不同内容不折叠）

    算法：
    1. 行级折叠：检查前半行是否等于后半行（处理整段题干重复）
    2. 整体折叠：检查文本前半是否等于后半（strip 后比较）
    3. 逐行折叠：去除相邻完全相同的行
    """
    if not text or not text.strip():
        return text

    stripped = text.strip()

    # —— 行级折叠：前半行 == 后半行 ——
    # 处理"S + 分隔符 + S"的整段重复模式，即使字符级半折叠因分割点不对齐而失败
    lines = stripped.split("\n")
    n_lines = len(lines)
    if n_lines >= 2:
        # 去除末尾可能由 trailing newline 产生的空行
        effective = n_lines - 1 if n_lines > 1 and lines[-1] == "" else n_lines
        if effective >= 2 and effective % 2 == 0:
            mid = effective // 2
            left = lines[:mid]
            right = lines[mid:effective]
            if left == right:
                return "\n".join(left)
        # 奇数行：尝试跳过中间空行（S + 空行 + S 模式）
        if effective >= 3 and effective % 2 == 1:
            mid = effective // 2
            if lines[mid].strip() == "":
                left = lines[:mid]
                right = lines[mid + 1 : effective]
                if left == right:
                    return "\n".join(left)

    # —— 整体折叠：前半 == 后半 ——
    half = len(stripped) // 2
    if half > 0:
        # 精确折叠（含分隔换行）
        if stripped[:half] == stripped[half:]:
            return stripped[:half].rstrip("\n")
        # 允许中间有换行分隔
        candidate = stripped[:half].strip()
        if candidate and stripped[half:].strip() == candidate:
            return candidate

    # —— 逐行折叠：去除相邻完全相同的行（保留顺序） ——
    deduped: list[str] = []
    for line in lines:
        if not deduped or line.strip() != deduped[-1].strip():
            deduped.append(line)
    result = "\n".join(deduped)

    # 再次整体折叠（逐行去重后可能使前后相等）
    half2 = len(result) // 2
    if half2 > 0:
        if result[:half2] == result[half2:]:
            return result[:half2].rstrip("\n")
        candidate2 = result[:half2].strip()
        if candidate2 and result[half2:].strip() == candidate2:
            return candidate2

    return result


def normalize_pdf_text(text: str) -> str:
    """主入口：空白归一化 → 视觉换行合并 → 重复折叠。"""
    if not text:
        return text
    text = normalize_spaces(text)
    text = merge_broken_lines(text)
    text = deduplicate_repeated_text(text)
    return text
