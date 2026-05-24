"""PDF 文本行合并与标准化。

职责：将 PDF / OCR 提取的视觉换行文本恢复为语义连续段落。
仅处理文本；不做任何题目解析逻辑。
"""
import re

# 行首结构标记正则（这些行不能被合并到上一行）
_STRUCTURE_LINE_RE = re.compile(
    r"^("
    r"\d+\s*[.、)）]"
    r"|[A-D]\s*[.、:：]"
    r"|[（(]\s*[A-D]\s*[）)]"                          # （A）(A)（A ）( A )
    r"|(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:]"
    r"|(?:【)?(?:解析|解答)(?:】)?\s*[：:]"
    r"|(?:[（(]\s*(?:单选|多选|选择|填空|判断|简答|论述|计算)题?[）)])"
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
_SENTENCE_END = frozenset("。！？；…")  # 。！？；…

# 未使用，保留语义说明
# _CONTINUATION = frozenset("，、（【：:,(")  # ，、（【：:,(


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


def normalize_pdf_text(text: str) -> str:
    """主入口：空白归一化 → 视觉换行合并。"""
    if not text:
        return text
    text = normalize_spaces(text)
    text = merge_broken_lines(text)
    return text
