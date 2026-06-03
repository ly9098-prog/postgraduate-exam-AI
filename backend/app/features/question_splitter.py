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
    (re.compile(r"^(\d+)\s*[.．、]"), 1),          # "1." "1．" "1、"
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
_OPTION_MARKER = _OPTION_NOISE_PREFIX + r"([A-Da-d])\s*[.．、:：)）]"

_OPTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"^" + _OPTION_NOISE_PREFIX + r"([A-Da-d])\s*[.．、:：)）]\s*(.+)"),
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

# 章节号模式：X.X 或 X.X.X 格式（非题号）
_SECTION_NUMBER_PATTERN = re.compile(
    r"^\d+\.\d+(\.\d+)?\s*\S"
)

# 正文标题特征：数字后跟纯中文标题（无括号）
_CONTENT_TITLE_PATTERN = re.compile(
    r"^\d+\s*[.、]\s*[一-鿿]{2,}[一-鿿\s]*$"
)

_SENTENCE_END = frozenset("。！？；…")


def _is_section_number(line: str, page: int | None = None, content_pages: set | None = None) -> bool:
    """判断一行是否为章节号（而非题号）。"""
    stripped = line.strip()
    # X.X.X 格式一定是章节号
    if _SECTION_NUMBER_PATTERN.match(stripped):
        return True
    # "3.分组交换" 类格式：数字+纯中文标题，无括号特征
    # 仅在有正文页上下文时应用，避免误过滤简短题目
    if content_pages and _CONTENT_TITLE_PATTERN.match(stripped):
        if "（" not in stripped and "(" not in stripped:
            if page in content_pages:
                return True
    return False


def _has_question_characteristics(line: str) -> bool:
    """判断一行是否有选择题特征（括号、选项标记等）。"""
    if "（" in line or "(" in line:
        return True
    if re.search(r"[A-D]\s*[.、:：)）]", line):
        return True
    if re.search(r"下列|以下|正确|错误|哪|属于|不属于", line):
        return True
    return False


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
    content_pages: set[int] = set()
    exercise_start_pages: set[int] = set()

    if structure and structure.get("mode") == "SEPARATED":
        answer_pages = set(structure.get("answer_pages", []))
        question_pages = set(structure.get("question_pages", []))
        excluded_answer_pages = answer_pages - question_pages

    # Build section_type lookup: ordered list of (page, marker_type) for question_type_* markers
    section_type_markers: list[tuple[int, str]] = []

    if structure:
        content_pages = set(structure.get("content_pages", []))
        for marker in structure.get("section_markers", []):
            if marker.get("marker_type") == "exercise_start":
                exercise_start_pages.add(marker["page"])
            mt = marker.get("marker_type", "")
            if mt.startswith("question_type_"):
                section_type_markers.append((marker["page"], mt))

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

    # Filter out section numbers masquerading as question numbers
    filtered_boundaries: list[tuple[int, int]] = []
    previous_valid_num: int | None = None
    for num, start_pos in boundaries:
        page = _pos_to_page(start_pos, page_map)
        # Extract the line at this position for section-number check
        line_end = full_text.find("\n", start_pos)
        if line_end == -1:
            line_end = len(full_text)
        line_text = full_text[start_pos:line_end]

        if _is_section_number(line_text, page, content_pages):
            continue

        # Context-aware: skip pages before any exercise section starts
        if exercise_start_pages and page < min(exercise_start_pages):
            continue

        # Large gap check: if number jumps by more than expected, lower trust
        if previous_valid_num is not None and num > previous_valid_num + 10:
            # Likely a false positive from content text
            if not _has_question_characteristics(line_text):
                continue

        filtered_boundaries.append((num, start_pos))
        previous_valid_num = num

    if not filtered_boundaries:
        return []

    questions: list[dict] = []

    for i, (num, start_pos) in enumerate(filtered_boundaries):
        end_pos = filtered_boundaries[i + 1][1] if i + 1 < len(filtered_boundaries) else len(full_text)
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

        # Determine section_type from the most recent question_type_* marker
        section_type = None
        if section_type_markers:
            for marker_page, marker_type in reversed(section_type_markers):
                if page_start >= marker_page:
                    section_type = marker_type
                    break

        questions.append({
            "number": num,
            "raw_question_text": raw_text,
            "page_start": page_start,
            "page_end": page_end,
            "has_options": len(options) > 0,
            "option_lines": options,
            "confidence": round(max(0.0, min(1.0, conf)), 2),
            "section_type": section_type,
        })

    return questions


def split_by_visual_boundaries(
    normalized_blocks: list[dict],
    boundaries: list[dict],
) -> list[dict]:
    """按视觉边界位置切分文本为题目列表。

    Args:
        normalized_blocks: 标准化后的 blocks（含 normalized_text）
        boundaries: detect_visual_boundaries() 的输出

    Returns:
        raw_questions 列表，格式同 split_questions 输出
    """
    if not boundaries:
        return []

    # 建立 block_index → block 的映射
    block_map: dict[int, dict] = {}
    for block in normalized_blocks:
        block_map[block.get("block_index", 0)] = block

    # 为每个边界获取对应的文本行位置
    segments: list[dict] = []
    for i, bound in enumerate(boundaries):
        blk_idx = bound["block_index"]
        line_idx = bound["line_index"]
        page = bound["page"]

        block = block_map.get(blk_idx)
        if not block:
            continue

        text = block.get("normalized_text") or block.get("text", "")
        lines = text.split("\n")

        # 确定当前段的结束位置
        if i + 1 < len(boundaries):
            next_bound = boundaries[i + 1]
            if next_bound["block_index"] == blk_idx:
                # 同一 block 内的下一个边界
                end_line = next_bound["line_index"]
                segment_lines = lines[line_idx:end_line]
            else:
                # 当前 block 剩余 + 中间 blocks 直到下一个边界 block
                segment_lines = lines[line_idx:]
                for mid_idx in range(blk_idx + 1, next_bound["block_index"]):
                    mid_block = block_map.get(mid_idx)
                    if mid_block:
                        mid_text = mid_block.get("normalized_text") or mid_block.get("text", "")
                        segment_lines.extend(mid_text.split("\n"))
                # 下一个边界 block 的前几行
                next_block = block_map.get(next_bound["block_index"])
                if next_block:
                    next_text = next_block.get("normalized_text") or next_block.get("text", "")
                    next_lines = next_text.split("\n")
                    segment_lines.extend(next_lines[:next_bound["line_index"]])
        else:
            # 最后一个边界：取当前 block 剩余 + 后续所有 blocks
            segment_lines = lines[line_idx:]
            max_blk_idx = max(block_map.keys()) if block_map else blk_idx
            for tail_idx in range(blk_idx + 1, max_blk_idx + 1):
                tail_block = block_map.get(tail_idx)
                if tail_block:
                    tail_text = tail_block.get("normalized_text") or tail_block.get("text", "")
                    segment_lines.extend(tail_text.split("\n"))

        raw_text = "\n".join(segment_lines).strip()
        if not raw_text:
            continue

        segments.append({
            "raw_text": raw_text,
            "page": page,
            "signal": bound.get("signal", ""),
        })

    # 转为标准 raw_question 格式
    questions: list[dict] = []
    for idx, seg in enumerate(segments):
        raw_text = seg["raw_text"]
        first_line = raw_text.split("\n")[0].strip()

        # 尝试从首行提取题号
        num_result = _detect_question_number(first_line)
        number = num_result[0] if num_result else idx + 1

        options = _extract_options(raw_text)

        conf = 0.6
        if options and len(options) >= 3:
            conf = 0.7
        if seg["signal"] == "large_gap":
            conf = 0.4

        questions.append({
            "number": number,
            "raw_question_text": raw_text,
            "page_start": seg["page"],
            "page_end": seg["page"],
            "has_options": len(options) > 0,
            "option_lines": options,
            "confidence": conf,
            "detection_method": "visual_boundary",
        })

    return questions
