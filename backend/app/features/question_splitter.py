"""题目切分器 — 纯规则实现。

从文档块中精准切分出单道题目，识别题号和选项标记。
不做答案匹配、不做题型判断、不做内容清洗、不调用 AI。
"""

import re


# 中文数字 → 阿拉伯数字
_CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# OCR 数字混淆 → 纠正
_OCR_DIGIT_MAP = {"O": "0", "o": "0", "l": "1", "I": "1", "S": "5"}

# 题号模式：(正则, 数字提取组, 说明)
_QUESTION_PATTERNS: list[tuple[re.Pattern, int]] = [
    (re.compile(r"^(\d+)\s*[.、]"), 1),          # "1." "1、"
    (re.compile(r"^(\d+)\s*[)）]"), 1),          # "1)" "1）"
    (re.compile(r"^\((\d+)\)"), 1),                # "(1)"
    (re.compile(r"^【(\d+)】"), 1),                # "【1】"
    (re.compile(r"^第\s*(\d+)\s*题"), 1),         # "第1题"
    (re.compile(
        r"^第\s*([" + "".join(_CN_NUM.keys()) + r"]+)\s*题"
    ), 1),                                          # "第一题"
]

_PAREN_QUESTION_PATTERN = _QUESTION_PATTERNS[1][0]

# OCR 容错题号：l/I → 1
_OCR_Q_PATTERN = re.compile(r"^([lI])\s*[.、)）]")

# 选项模式
_CIRCLED_OPTION_CHARS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_OPTION_NOISE_PREFIX = r"(?:[?？]|[" + _CIRCLED_OPTION_CHARS + r"])?\s*"
_OPTION_MARKER = _OPTION_NOISE_PREFIX + r"([A-Da-d])\s*[.、:：)）]"

_OPTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"^" + _OPTION_NOISE_PREFIX + r"([A-Da-d])\s*[.、:：)）]\s*(.+)"),
    re.compile(r"^" + _OPTION_NOISE_PREFIX + r"([A-Da-d])\s+(.+)"),
]

# OCR 容错选项
_OCR_OPTION_MAP = {"8": "B", "6": "B", "0": "D", "Ｏ": "D"}

_INLINE_QUESTION_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*[.、)）]\s*\S")
_INLINE_OPTION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])" + _OPTION_MARKER +
    r"\s*(.+?)(?=\s+" + _OPTION_MARKER + r"\s*|$)"
)
_ANSWER_EXPLANATION_MARKER = re.compile(
    r"(?:答案|正确答案|参考答案|解析|解答|讲解|分析)\s*[：:]"
)
_ANSWER_EXPLANATION_LINE = re.compile(
    r"^(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:]|^(?:【)?(?:解析|解答|讲解|分析)(?:】)?\s*[：:]"
)

_OCR_OPTION_PATTERN = re.compile(
    r"^" + _OPTION_NOISE_PREFIX + r"([" + "".join(_OCR_OPTION_MAP.keys()) + r"])\s*[.、:：)）]\s*(.+)"
)


def _detect_question_number(line: str) -> tuple[int, int] | None:
    """检测行首的题号，返回 (题号, 匹配结束位置) 或 None。"""
    # 精确匹配
    for pat, group_idx in _QUESTION_PATTERNS:
        m = pat.match(line)
        if m:
            digits = m.group(group_idx)
            if group_idx == 1 and pat is _QUESTION_PATTERNS[-1][0]:
                num = 0
                for ch in digits:
                    num = num * 10 + _CN_NUM.get(ch, 0)
                return (num, m.end())
            num = int(digits)
            # 过滤明显是选项 OCR 错误的假题号
            if _is_false_question_number(num, line):
                return None
            if pat is _PAREN_QUESTION_PATTERN and not _looks_like_paren_question(line, m.end()):
                return None
            return (num, m.end())

    # OCR 容错：l/I → 1
    m = _OCR_Q_PATTERN.match(line)
    if m:
        return (1, m.end())

    return None


def _is_false_question_number(num: int, line: str) -> bool:
    """判断检测到的题号是否为选项 OCR 错误导致的假题号。"""
    # 0 永远不是有效题号
    if num == 0:
        return True
    # 6/8 可能是 B 的 OCR 错误，且该行也匹配选项模式
    if num in (6, 8):
        if _detect_option_line(line):
            return True
    return False


def _looks_like_paren_question(line: str, match_end: int) -> bool:
    rest = line[match_end:].lstrip()
    num_text = line[:match_end].rstrip(" )）")
    if len(num_text) >= 2 and rest:
        return True
    return bool(re.match(r"(?:第\s*)?\S+题", rest))


def _has_option_marker_before_question(text: str) -> bool:
    markers = list(re.finditer(_OPTION_MARKER, text))
    if not markers:
        return False
    keys = [m.group(1).upper() for m in markers]
    if len(keys) >= 2:
        return True
    marker = markers[-1]
    tail = text[marker.end():].strip()
    return bool(tail)


def _is_probable_inline_question_text(text: str) -> bool:
    return bool(re.search(r"[（(][^）)]{0,8}[）)]|下列|以下|正确|错误|问|求|计算|证明|已知|若", text))


def _looks_like_inline_question(line: str, match: re.Match, previous_num: int | None) -> bool:
    num = int(match.group(1))
    if _is_false_question_number(num, line[match.start():]):
        return False
    if previous_num is not None and num != previous_num + 1:
        return False
    before = line[:match.start()].rstrip()
    if not before:
        return False
    if _has_option_marker_before_question(before):
        return True
    if _is_probable_inline_question_text(line[match.end():]):
        return True
    return before[-1] in _SENTENCE_END


def _find_inline_question_boundaries(line: str, previous_num: int | None) -> list[tuple[int, int]]:
    boundaries: list[tuple[int, int]] = []
    expected = previous_num
    for match in _INLINE_QUESTION_PATTERN.finditer(line):
        if _looks_like_inline_question(line, match, expected):
            num = int(match.group(1))
            boundaries.append((num, match.start()))
            expected = num
    return boundaries


def _is_sub_question_line(line: str, num: int, previous_num: int | None, in_subquestion: bool) -> bool:
    if not re.match(r"^\d+\s*[)）]", line):
        return False
    if previous_num is None:
        return False
    return num == 1 or in_subquestion


def _detect_option_line(line: str) -> tuple[str, str] | None:
    """检测选项行，返回 (key, text) 或 None。"""
    # 精确匹配
    for pat in _OPTION_PATTERNS:
        m = pat.match(line)
        if m:
            key = m.group(1).upper()
            text = m.group(2).strip()
            if len(text) >= 1:
                return (key, text)

    # OCR 容错选项
    m = _OCR_OPTION_PATTERN.match(line)
    if m:
        key = _OCR_OPTION_MAP.get(m.group(1), m.group(1).upper())
        text = m.group(2).strip()
        if len(text) >= 1:
            return (key, text)

    return None


def _find_question_boundaries(text: str) -> list[tuple[int, int]]:
    """扫描全文，找到所有题号位置。返回 [(题号, 字符位置), ...]"""
    boundaries: list[tuple[int, int]] = []
    lines = text.split("\n")

    char_pos = 0
    previous_num: int | None = None
    in_subquestion = False
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        result = _detect_question_number(stripped)
        if result is not None:
            num, match_end = result
            if _is_sub_question_line(stripped, num, previous_num, in_subquestion):
                in_subquestion = True
            else:
                line_start = char_pos + indent
                boundaries.append((num, line_start))
                previous_num = num
                in_subquestion = False
                for inline_num, inline_start in _find_inline_question_boundaries(stripped, previous_num):
                    if inline_start == 0:
                        continue
                    boundaries.append((inline_num, char_pos + indent + inline_start))
                    previous_num = inline_num
        elif previous_num is not None:
            for num, inline_start in _find_inline_question_boundaries(stripped, previous_num):
                if inline_start == 0:
                    continue
                boundaries.append((num, char_pos + indent + inline_start))
                previous_num = num

        char_pos += len(line) + 1  # +1 for \n

    return boundaries


def _truncate_answer_explanation_tail(text: str) -> str:
    match = _ANSWER_EXPLANATION_MARKER.search(text)
    if match:
        return text[:match.start()].strip()
    return text.strip()


def _extract_options(text: str) -> dict[str, str]:
    """从题目文本中提取选项行。"""
    options: dict[str, str] = {}
    last_key: str | None = None
    for line in text.split("\n"):
        stripped = line.strip()
        inline_matches = list(_INLINE_OPTION_PATTERN.finditer(stripped))
        if len(inline_matches) > 1:
            for match in inline_matches:
                key = match.group(1).upper()
                value = _truncate_answer_explanation_tail(match.group(2))
                if key not in options and value:
                    options[key] = value
            last_key = inline_matches[-1].group(1).upper()
            continue

        result = _detect_option_line(stripped)
        if result:
            key, value = result
            value = _truncate_answer_explanation_tail(value)
            if key not in options and value:  # 保留第一个匹配
                options[key] = value
            last_key = key
            continue

        if (
            last_key
            and stripped
            and not _detect_question_number(stripped)
            and not _detect_option_line(stripped)
            and not _ANSWER_EXPLANATION_LINE.match(stripped)
            and last_key in options
        ):
            options[last_key] = f"{options[last_key]} {stripped}"
    return options


def _pos_to_page(
    pos: int, page_map: list[tuple[int, int, int]]
) -> int:
    """将字符位置映射到页码。"""
    last_page = 1
    for offset, page, _ in page_map:
        if pos < offset:
            break
        last_page = page
    return last_page


def split_questions(
    normalized_blocks: list[dict],
    structure: dict | None = None,
) -> list[dict]:
    """从文档块中切分出单道题目。

    Args:
        normalized_blocks: stage1 输出的标准化块列表
        structure: stage2 的结构分析结果（可选）

    Returns:
        raw_questions 列表
    """
    if not normalized_blocks:
        return []

    # 构建全文和页码映射
    parts: list[str] = []
    page_map: list[tuple[int, int, int]] = []  # (char_pos, page, block_index)
    pos = 0

    excluded_answer_pages: set[int] = set()
    if structure and structure.get("mode") == "SEPARATED":
        answer_pages = set(structure.get("answer_pages", []))
        question_pages = set(structure.get("question_pages", []))
        excluded_answer_pages = answer_pages - question_pages

    for block in normalized_blocks:
        text = block.get("normalized_text", "")
        page = block.get("page", 1)
        block_idx = block.get("block_index", 0)
        if page in excluded_answer_pages:
            continue

        page_map.append((pos, page, block_idx))
        parts.append(text)
        pos += len(text) + 1  # +1 for the joining newline

    full_text = "\n".join(parts)
    boundaries = _find_question_boundaries(full_text)

    if not boundaries:
        return []

    questions: list[dict] = []

    for i, (num, start_pos) in enumerate(boundaries):
        end_pos = boundaries[i + 1][1] if i + 1 < len(boundaries) else len(full_text)
        raw_text = full_text[start_pos:end_pos].strip()

        page_start = _pos_to_page(start_pos, page_map)
        page_end = _pos_to_page(max(start_pos, end_pos - 1), page_map)

        options = _extract_options(raw_text)

        # 置信度：基于题号格式清晰度 + 选项完整度
        conf = 0.9
        if raw_text.count("\n") <= 1:
            conf -= 0.1  # 极短文本
        if options and len(options) >= 3:
            conf = min(1.0, conf + 0.05)
        if num <= 0:
            conf -= 0.3

        questions.append({
            "number": num,
            "raw_question_text": raw_text,
            "page_start": page_start,
            "page_end": page_end,
            "has_options": len(options) > 0,
            "option_lines": options,
            "confidence": round(max(0.0, min(1.0, conf)), 2),
        })

    return questions
