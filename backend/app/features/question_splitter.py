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
_OPTION_PREFIX_MARKER = r"(?:[?？]\s*|[" + _CIRCLED_OPTION_CHARS + r"]\s*)?"
_OPTION_MARKER = _OPTION_PREFIX_MARKER + r"([A-Da-d])\s*[.．、:：)）]"

_OPTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"^" + _OPTION_PREFIX_MARKER + r"([A-Da-d])\s*[.．、:：)）]\s*(.+)"),
    re.compile(r"^" + _OPTION_PREFIX_MARKER + r"([A-Da-d])\s+(.+)"),
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
    r"^" + _OPTION_PREFIX_MARKER + r"([" + "".join(_OCR_OPTION_MAP.keys()) + r"])\s*[.、:：)）]\s*(.+)"
)

# 章节号模式：X.X 或 X.X.X 格式（非题号）
_SECTION_NUMBER_PATTERN = re.compile(
    r"^\d+\.\d+(\.\d+)?\s*\S"
)

# 正文标题特征：数字后跟纯中文标题（允许年份标注）
_CONTENT_TITLE_PATTERN = re.compile(
    r"^\d+\s*[.．、]\s*[一-鿿]{2,}[一-鿿\s、]*(?:[（(]\d{4}[）)])?[一-鿿\s、]*$"
)

# 年份标注模式：（2019）(2020) 等，王道教材标注考过年份
_YEAR_ANNOTATION_RE = re.compile(r"[（(]\d{4}[）)]")

# 试卷大题节标题：一、选择题 / 二、填空题 / 三、解答题 / Part I
_EXAM_SECTION_HEADER = re.compile(
    r"^(?:"
    r"[一二三四五六七八九十]+\s*[、.．]\s*"
    r"(?:单项选择|多项选择|选择|单选|多选|判断|填空|简答|"
    r"计算|证明|综合应用|综合|解答|论述|分析|程序设计|应用)"
    r"(?:题|部分)?"
    r"|Part\s+[IVX]+\b"
    r"|第\s*[一二三四五六七八九十]+\s*(?:部分|大?题)"
    r")"
)

_SENTENCE_END = frozenset("。！？；…")

# 正文散文检测：用于内容页上区分知识点编号和真实题号
_PROSE_SENTENCE_END_RE = re.compile(r"。")
_OPTION_ABCD_RE = re.compile(r"[A-D]\s*[.．、:：)）]")


# P1-1: book 模式下的"软 prose"检测信号。比 pipeline_orchestrator
# `_looks_like_book_pdf_prose_candidate` 更宽松——后者会**整道丢弃**明显正文
# （marker ≥ 2 + 句号 ≥ 2 + 长度 ≥ 90），这里只**打 risk_flag 降权**，让 edge
# case（短 prose / 单一 marker）仍能进入审核，但前端醒目展示 "疑似正文"。
# 与 ai_repair `_looks_like_non_question_text` 保持词表一致，避免链路漂移。
_BOOK_SOFT_PROSE_MARKER_RE = re.compile(
    r"定义|定理|知识点|证明|证毕|解法|例题|例如|如下|因此可得|由此可知|综上|性质|推论|注意|本节|本章"
)
_BOOK_SOFT_QUESTION_SIGNAL_RE = re.compile(
    r"下列|以下|正确|错误|的是|哪|选择|计算|判断|已知|设|若|试述|简述|回答|为什么|求|问|\?|？"
)
_BOOK_SOFT_INLINE_OPTION_RE = re.compile(r"(?:^|\n|\s)[A-D]\s*[.．、:：)）]")
_BOOK_EXERCISE_MARKER_RE = re.compile(r"习题精选|练习题|巩固练习|单项选择题|多项选择题|选择题")
_BOOK_ANSWER_ONLY_RE = re.compile(r"答案与解析|参考答案|正确答案")


def _trim_book_text_before_exercises(text: str) -> str:
    marker = _BOOK_EXERCISE_MARKER_RE.search(text)
    if not marker:
        return text
    tail = text[marker.end():]
    question = re.search(r"\d+\s*[.．、)）]", tail)
    if not question:
        return text
    return tail[question.start():].lstrip()


def _looks_like_book_non_question_segment(question: dict) -> bool:
    text = str(question.get("raw_question_text") or "").strip()
    if not text:
        return True
    if _BOOK_ANSWER_ONLY_RE.search(text) and not question.get("has_options"):
        return True
    if re.search(r"(?:^|\n)\s*解析[：:]", text) and not question.get("has_options"):
        return True
    if question.get("has_options") or question.get("option_lines"):
        return False
    if _BOOK_SOFT_INLINE_OPTION_RE.search(text):
        return False
    marker_count = len(_BOOK_SOFT_PROSE_MARKER_RE.findall(text))
    if marker_count == 0:
        return False
    if re.search(r"(?:^|\n)\s*(?:证明|证毕|例题解析|解法)[：:]", text) and not question.get("has_options"):
        return True
    if _BOOK_SOFT_QUESTION_SIGNAL_RE.search(text):
        return marker_count >= 2 and len(text) >= 90
    if marker_count == 1 and len(text) < 60:
        return True
    return marker_count >= 2 and len(text) >= 90


def _looks_like_book_soft_prose(question: dict) -> bool:
    """P1-1: 判断一道已切出的题目是否"疑似教材正文"。

    标准比 pipeline 的硬过滤更宽松，命中时给题目打 ``book_pdf_prose_like``
    flag、保留进审核队列，让人工最后裁判：
    - 长度 ≥ 60；
    - 没有 has_options / option_lines（已抽出选项的就别再判）；
    - segment 内无 A./B./C./D. 选项行；
    - segment 内无题问信号（下列/以下/求/问/?/？等）；
    - segment 内出现至少 1 个 prose marker（定义/定理/性质/例题/证明 等）。
    """
    text = str(question.get("raw_question_text") or "").strip()
    if len(text) < 60:
        return False
    if question.get("has_options") or question.get("option_lines"):
        return False
    if _BOOK_SOFT_INLINE_OPTION_RE.search(text):
        return False
    if _BOOK_SOFT_QUESTION_SIGNAL_RE.search(text):
        return False
    return bool(_BOOK_SOFT_PROSE_MARKER_RE.search(text))


def _iter_lines_with_pos(text: str):
    """Yield (line_start_pos, line_text) for each line in text."""
    start = 0
    for line in text.split("\n"):
        yield start, line
        start += len(line) + 1


def _has_exam_section_before(pos: int, section_positions: set[int], full_text: str) -> bool:
    """Check if there's an exam section header between the previous question and pos."""
    if not section_positions:
        return False
    # Look backward from pos for a section header within 500 chars
    search_start = max(0, pos - 500)
    for sp in section_positions:
        if search_start <= sp < pos:
            return True
    return False


def _is_section_number(line: str, page: int | None = None, content_pages: set | None = None) -> bool:
    """判断一行是否为章节号（而非题号）。"""
    stripped = line.strip()
    # X.X.X 格式一定是章节号
    if _SECTION_NUMBER_PATTERN.match(stripped):
        return True
    # "3.分组交换" 类格式：数字+纯中文标题（允许年份标注）
    # 仅在有正文页上下文时应用，避免误过滤简短题目
    if content_pages and _CONTENT_TITLE_PATTERN.match(stripped):
        if page in content_pages:
            return True
    # 含年份标注的知识点编号行（如 "3. 快重传算法（2019）"）
    if content_pages and page in content_pages:
        if re.match(r"^\d+\s*[.．、]", stripped) and _YEAR_ANNOTATION_RE.search(stripped):
            if not re.search(r"[A-D]\s*[.．、:：)）]", stripped):
                return True
    return False


def _is_content_prose(text_segment: str) -> bool:
    """判断从题号开始的文本段是否为正文散文（而非题目）。

    在内容页上，编号后跟多句解释性文字（≥2个句号且无选项标记）几乎一定是课本正文。
    """
    if _OPTION_ABCD_RE.search(text_segment):
        return False
    periods = len(_PROSE_SENTENCE_END_RE.findall(text_segment))
    if periods >= 2:
        return True
    if len(text_segment) > 150 and periods >= 1:
        return True
    return False


def _has_question_characteristics(line: str) -> bool:
    """判断一行是否有选择题特征（括号、选项标记等）。"""
    if "（" in line or "(" in line:
        # 年份标注不算题目特征
        line_no_year = _YEAR_ANNOTATION_RE.sub("", line)
        if "（" in line_no_year or "(" in line_no_year:
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


def _parse_options_from_text(text: str) -> dict[str, str]:
    options: dict[str, str] = {}
    for match in _INLINE_OPTION_PATTERN.finditer(text.strip()):
        key = match.group(1).upper()
        value = _truncate_answer_explanation_tail(match.group(2))
        if key not in options and value:
            options[key] = value
    return options


def _line_group_marker(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    for marker in _CIRCLED_OPTION_CHARS:
        for prefix in (marker, f"（{marker}）", f"({marker})"):
            if stripped == prefix:
                return marker, ""
            if stripped.startswith(prefix) and stripped[len(prefix):len(prefix) + 1].isspace():
                rest = stripped[len(prefix):].strip()
                if rest and re.match(r"^(?:[?？]\s*)?[A-Da-d]\s*[.．、:：)）\s]", rest):
                    return marker, rest
    return None


def _extract_grouped_options(text: str) -> list[dict]:
    groups: list[dict] = []
    current: dict | None = None
    last_key: str | None = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        marker_result = _line_group_marker(stripped)
        if marker_result:
            marker, rest = marker_result
            current = {"id": marker, "options": {}}
            groups.append(current)
            last_key = None
            if rest:
                parsed = _parse_options_from_text(rest)
                current["options"].update(parsed)
                if parsed:
                    last_key = next(reversed(parsed))
            continue

        if current is None:
            continue

        inline_options = _parse_options_from_text(stripped)
        if inline_options:
            current["options"].update(inline_options)
            last_key = next(reversed(inline_options))
            continue

        result = _detect_option_line(stripped)
        if result:
            key, value = result
            current["options"][key] = _truncate_answer_explanation_tail(value)
            last_key = key
            continue

        if (
            last_key
            and not _detect_question_number(stripped)
            and not _ANSWER_EXPLANATION_LINE.match(stripped)
            and last_key in current["options"]
        ):
            current["options"][last_key] = f"{current['options'][last_key]} {stripped}"

    return [group for group in groups if len(group.get("options", {})) >= 2]


def _has_numbered_blank_markers(text: str, grouped_options: list[dict]) -> bool:
    if len(grouped_options) < 2:
        return False
    markers = {group.get("id") for group in grouped_options}
    marker_positions = [match.start() for match in re.finditer(r"(?<![（(])[" + _CIRCLED_OPTION_CHARS + r"]\s+[A-Da-d]\s*[.．、:：)）]", text)]
    stem_part = text
    if marker_positions:
        stem_part = text[:min(marker_positions)]
    return sum(1 for marker in markers if marker and re.search(rf"[（(]\s*{re.escape(str(marker))}\s*[）)]", stem_part)) >= 2


def _flatten_first_option_group(grouped_options: list[dict]) -> dict[str, str]:
    if not grouped_options:
        return {}
    return dict(grouped_options[0].get("options") or {})


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
    gap_tolerance: int = 10,
    import_mode: str | None = None,
) -> list[dict]:
    """从文档块中切分出单道题目。

    Args:
        normalized_blocks: stage1 输出的标准化块列表
        structure: stage2 的结构分析结果（可选）
        gap_tolerance: 题号跳跃容忍度，超过此值且无选择题特征则跳过
        import_mode: ``"book"`` / ``"exam"`` / ``"image"`` / ``"txt"`` / None。
            book 模式下会额外给"疑似教材正文"的候选题打
            ``risk_flags=["book_pdf_prose_like"]``，由前端审核页提示，但仍保留
            到审核队列让人工最终裁决。

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
    book_mode = isinstance(import_mode, str) and import_mode.lower() == "book"
    if book_mode:
        full_text = _trim_book_text_before_exercises(full_text)
    boundaries = _find_question_boundaries(full_text)

    if not boundaries:
        return []

    # Detect exam section headers in full_text (allow number resets after them)
    exam_section_positions: set[int] = set()
    for line_start, line in _iter_lines_with_pos(full_text):
        stripped = line.strip()
        if _EXAM_SECTION_HEADER.match(stripped):
            exam_section_positions.add(line_start)

    # Filter out section numbers masquerading as question numbers
    filtered_boundaries: list[tuple[int, int]] = []
    previous_valid_num: int | None = None
    for bound_idx, (num, start_pos) in enumerate(boundaries):
        page = _pos_to_page(start_pos, page_map)
        # Extract the line at this position for section-number check
        line_end = full_text.find("\n", start_pos)
        if line_end == -1:
            line_end = len(full_text)
        line_text = full_text[start_pos:line_end]

        if book_mode and _is_section_number(line_text, page, content_pages):
            continue

        # Content page prose detection: numbered paragraphs of explanatory text
        if book_mode and content_pages and page in content_pages:
            next_pos = boundaries[bound_idx + 1][1] if bound_idx + 1 < len(boundaries) else len(full_text)
            segment = full_text[start_pos:next_pos]
            if _is_content_prose(segment):
                continue

        # Context-aware: skip pages before any exercise section starts
        if exercise_start_pages and page < min(exercise_start_pages):
            continue

        # Allow number resets after exam section headers
        if previous_valid_num is not None and num < previous_valid_num:
            if num == 1 and _has_exam_section_before(start_pos, exam_section_positions, full_text):
                previous_valid_num = None

        # Large gap check: if number jumps by more than expected, lower trust
        if previous_valid_num is not None and num > previous_valid_num + gap_tolerance:
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

        grouped_options = _extract_grouped_options(raw_text)
        has_grouped_options = _has_numbered_blank_markers(raw_text, grouped_options)
        options = _flatten_first_option_group(grouped_options) if has_grouped_options else _extract_options(raw_text)

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
            "blank_option_groups": grouped_options if has_grouped_options else [],
            "has_grouped_options": has_grouped_options,
            "confidence": round(max(0.0, min(1.0, conf)), 2),
            "section_type": section_type,
        })

    questions = _recover_cross_page_options(questions)

    # P1-1: book 模式下软 prose 标记。命中条件比 pipeline 的硬过滤宽松，
    # 仅打 risk_flags 不丢弃，让人工最终裁决。orchestrator `_run_split`
    # 已把 import_mode 透传过来；其它模式（exam/image/txt/None）无影响。
    if book_mode:
        questions = [q for q in questions if not _looks_like_book_non_question_segment(q)]
        for q in questions:
            if _looks_like_book_soft_prose(q):
                existing = q.get("risk_flags") or []
                q["risk_flags"] = list(dict.fromkeys([*existing, "book_pdf_prose_like"]))
                q["confidence"] = min(q.get("confidence", 0.4), 0.4)

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

        grouped_options = _extract_grouped_options(raw_text)
        has_grouped_options = _has_numbered_blank_markers(raw_text, grouped_options)
        options = _flatten_first_option_group(grouped_options) if has_grouped_options else _extract_options(raw_text)

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
            "blank_option_groups": grouped_options if has_grouped_options else [],
            "has_grouped_options": has_grouped_options,
            "confidence": conf,
            "detection_method": "visual_boundary",
        })

    return questions


# ---------------------------------------------------------------------------
# Cross-page option recovery
# ---------------------------------------------------------------------------

_EXPECTED_CHOICE_KEYS = ["A", "B", "C", "D"]


def _detect_incomplete_options(question: dict) -> tuple[bool, set[str]]:
    """Check if a choice question has incomplete ABCD options.

    Returns (is_incomplete, found_keys).
    Only flags questions that have SOME options but are missing others.
    """
    option_lines = question.get("option_lines", {})
    if not option_lines:
        return False, set()

    found_keys = {k.upper() for k in option_lines.keys()}

    if "A" not in found_keys:
        return False, found_keys

    missing = set(_EXPECTED_CHOICE_KEYS) - found_keys
    if missing:
        return True, found_keys

    return False, found_keys


def _detect_orphan_options_at_start(raw_text: str) -> tuple[bool, dict[str, str], int]:
    """Check if text starts with orphaned option lines (no preceding question number).

    Returns (has_orphans, orphan_options, chars_consumed).
    """
    lines = raw_text.split("\n")
    orphan_options: dict[str, str] = {}
    chars_consumed = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            chars_consumed += len(line) + 1
            continue

        if _detect_question_number(stripped) is not None:
            break

        result = _detect_option_line(stripped)
        if result:
            key, text = result
            orphan_options[key] = text
            chars_consumed += len(line) + 1
            continue

        if orphan_options:
            break
        break

    if not orphan_options:
        return False, {}, 0

    return True, orphan_options, chars_consumed


def _recover_cross_page_options(questions: list[dict]) -> list[dict]:
    """Post-process split results to recover orphaned options from page breaks.

    Detects pattern:
    - Question i has options A, B but not C, D (incomplete)
    - Question i+1 starts with orphan option lines C, D (no question number first)

    Merges the orphaned content back into question i and recalculates.
    """
    if len(questions) < 2:
        return questions

    i = 0
    while i < len(questions) - 1:
        current = questions[i]
        next_q = questions[i + 1]

        if current.get("has_grouped_options") or current.get("blank_option_groups"):
            i += 1
            continue

        is_incomplete, found_keys = _detect_incomplete_options(current)
        if not is_incomplete:
            i += 1
            continue

        if current.get("page_end", 0) == next_q.get("page_start", 0):
            i += 1
            continue

        has_orphans, orphan_opts, chars_consumed = _detect_orphan_options_at_start(
            next_q.get("raw_question_text", "")
        )
        if not has_orphans:
            i += 1
            continue

        orphan_keys = {k.upper() for k in orphan_opts.keys()}
        missing_keys = set(_EXPECTED_CHOICE_KEYS) - found_keys
        if not (orphan_keys & missing_keys):
            i += 1
            continue

        orphan_text = next_q["raw_question_text"][:chars_consumed]
        current["raw_question_text"] = current["raw_question_text"].rstrip() + "\n" + orphan_text.strip()
        current["option_lines"].update(orphan_opts)
        current["has_options"] = True
        current["page_end"] = next_q.get("page_start", current.get("page_end", 1))

        remaining_text = next_q["raw_question_text"][chars_consumed:].lstrip("\n")
        if remaining_text.strip():
            next_q["raw_question_text"] = remaining_text
            next_q["option_lines"] = _extract_options(remaining_text)
            next_q["has_options"] = len(next_q["option_lines"]) > 0
        else:
            questions.pop(i + 1)
            continue

        i += 1

    return questions
