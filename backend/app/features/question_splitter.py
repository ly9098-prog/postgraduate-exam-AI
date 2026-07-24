"""题目切分器 — 纯规则实现。

从文档块中精准切分出单道题目，识别题号和选项标记。
不做答案匹配、不做题型判断、不做内容清洗、不调用 AI。

题号解析统一委托 ``question_numbering`` 模块。
"""

import logging
import re

logger = logging.getLogger(__name__)


# 题号解析 — 统一委托 question_numbering 模块
# 不允许本模块单独维护题号正则 (OCR-103)
from app.features.question_numbering import (
    NumberingType,
    _is_false_question_number,
    extract_first_question_label,
    parse_numbering,
)

# Legacy exports for backward compatibility
_CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# Compatibility patterns used by heuristic helpers below
# (not for primary question number detection — that goes through parse_numbering)
_PAREN_QUESTION_PATTERN = re.compile(r"^(\d+)\s*[)）]")
_PARENED_QUESTION_PATTERN = re.compile(r"^\((\d+)\)")
_OCR_Q_PATTERN = re.compile(r"^([lI])\s*[.、)）]")

# ASCII 罗马数字子项标记 I./II./III. ——多选题子项枚举，区别于阿拉伯题号。
# 用于避免把行首子项 "I." 误当成题号 "1." 而把一道多选题切成两题。
# Constants imported from shared module (single source of truth)
from app.features.roman_schema import (  # noqa: E402
    _RE_ROMAN_SUBITEM_MARKER,
)
from app.features.roman_schema import (
    has_roman_subitem_list as _has_roman_subitem_list,
)

# 选项模式
_CIRCLED_OPTION_CHARS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_ROMAN_MARKER_CHARS = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
_OPTION_PREFIX_MARKER = r"(?:[?？]\s*|[" + _CIRCLED_OPTION_CHARS + r"]\s*)?"
_OPTION_MARKER = _OPTION_PREFIX_MARKER + r"([A-Da-d])\s*[.．、:：)）]"

_OPTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"^" + _OPTION_PREFIX_MARKER + r"([A-Da-d])\s*[.．、:：)）]\s*(.+)"),
    re.compile(r"^" + _OPTION_PREFIX_MARKER + r"([A-Da-d])\s+(.+)"),
]

# OCR 容错选项 — defense-in-depth fallback for option detection during
# splitting. Primary OCR character fixes are handled upstream in
# text_normalizer._fix_option_line(); this map catches edge cases that
# survive normalization (e.g., composite glyph rendering artifacts).
_OCR_OPTION_MAP = {"8": "B", "6": "B", "0": "D", "Ｏ": "D"}

_INLINE_QUESTION_PATTERN = re.compile(r"(?<![\d（(])(\d{1,3})\s*[.、)）]\s*\S")
_INLINE_OPTION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])" + _OPTION_MARKER +
    r"\s*(.+?)(?=[、，,，\s]+" + _OPTION_MARKER + r"\s*|$)"
)
_LEADING_SPACE_OPTION_PATTERN = re.compile(
    r"^" + _OPTION_PREFIX_MARKER + r"([A-Da-d])\s+(.+?)(?=[、，,，\s]+" + _OPTION_MARKER + r"\s*|$)"
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


# ── Frozen option stem stripping (P0: Problem C from audit) ──
_FROZEN_OPTION_LINE_RE = re.compile(
    r"(?:^|\n)\s*([A-Da-d])\s*[.．、:：)）]\s*(?:\S+)?(?=\s*(?:\n|$|[A-Da-d]\s*[.．、:：)）]))"
)
_FROZEN_ANSWER_LINE_RE = re.compile(
    r"(?:^|\n)\s*(?:参考|正确)?答案\s*[:：]\s*[A-Da-d]+\s*(?:\n|$)"
)


def strip_frozen_options_from_stem(stem: str, frozen_options: dict[str, str]) -> str:
    """Remove frozen option text and answer lines from stem.

    Detects patterns like:
        A.ABDECF, B.ABDCEF, C.ABDFEC, D.ACBEDF
        A. ABDECF, B. ABDCEF  (with space after dot)
        A.ABDECF B.ABDCEF C.ABDFEC D.ACBEDF  (single line)
        答案：A, 答案:A

    Preserves traversal sequences like DBEAFC, DEBFCA that are part of the stem.

    Args:
        stem: The question stem text (may contain option text).
        frozen_options: Dict of {key: value} from structure freeze stage.

    Returns:
        Cleaned stem with option and answer text removed.
    """
    if not stem or not frozen_options:
        return stem

    lines = stem.split("\n")
    cleaned_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append(line)
            continue

        # Check if this line matches an option line exactly
        is_option_line = False
        for key, value in frozen_options.items():
            # Match patterns like "A.ABDECF", "A. ABDECF", "A.ABDCEF"
            # Also "A.ABDECF" without space (no space between dot and text)
            for prefix_sep in [". ", "．", ".", "、", ": ", "：", ") ", ")", "） "]:
                pattern_no_space = f"{key}{prefix_sep}{value}"
                pattern_with_space = f"{key}{prefix_sep} {value}"
                if stripped == pattern_no_space.strip() or stripped == pattern_with_space.strip():
                    is_option_line = True
                    break
                # Also check if stripped equals just the option prefix + value
                simple_pattern = f"{key}{prefix_sep}{value}"
                if stripped == simple_pattern.strip():
                    is_option_line = True
                    break
            if is_option_line:
                break

        if is_option_line:
            continue

        # Check for "答案：A" or "答案:A" lines
        if _FROZEN_ANSWER_LINE_RE.match(stripped):
            continue

        # Check for inline option patterns on this line
        # Remove inline option patterns like "A.ABDECF B.ABDCEF" within a line
        remaining = stripped
        for key, value in frozen_options.items():
            for prefix_sep in [".", "．", "、", ":", "："]:
                # Match "key.value" or "key. value" patterns
                pat = re.compile(
                    r"\s*" + re.escape(key) + re.escape(prefix_sep) + r"\s*" + re.escape(value) + r"\s*"
                )
                remaining = pat.sub(" ", remaining).strip()

        # Only keep if remaining has meaningful content
        if remaining and remaining != stripped:
            # Check if remaining is just whitespace or empty
            if remaining.strip():
                cleaned_lines.append(remaining)
            # If remaining is empty, skip line entirely
        else:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


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
    """检测行首的题号，返回 (题号, 匹配结束位置) 或 None。

    统一委托 ``question_numbering.parse_numbering()`` 实现。
    """
    result = parse_numbering(line)
    if result is None:
        return None

    # Skip non-question types
    if result.numbering_type in (
        NumberingType.SECTION,
        NumberingType.FALSE_POSITIVE,
        NumberingType.ORDINAL,
        NumberingType.ANSWER,
        NumberingType.OPTION,
        NumberingType.OPTION_ROMAN,
        NumberingType.OPTION_CIRCLED,
    ):
        return None

    # Legacy: keep paren heuristics for specific edge cases
    after_text = line[result.end:].lstrip()
    if result.numbering_type is NumberingType.SUB_QUESTION:
        # Check if (N) looks like a grouped option marker (not a sub-question)
        if _looks_like_grouped_option_marker(line, result.end):
            return None
        # Check if (N) looks like a real parenthetical question
        if not _looks_like_paren_question(line, result.end):
            return None

    # OCR false-positive filter (6→B, 8→B)
    if _is_false_question_number(result.normalized_value, line):
        return None

    # Section number filter: "1.1" should not be a question number
    if result.numbering_type is NumberingType.MAIN_QUESTION:
        if after_text and (after_text[0].isdigit() or after_text[0] in ".．"):
            return None

    return (result.normalized_value, result.end)


def _extract_first_line_label(text: str) -> str | None:
    """从原始题目文本的首行提取完整题号标签（如 "12."、"第12题"）。

    统一委托 ``question_numbering.extract_first_question_label``。

    返回匹配到的完整前缀（包括标点），用于审核页展示。
    若匹配不到则返回 None。
    """
    return extract_first_question_label(text)


def _is_false_question_number(num: int, line: str) -> bool:
    """判断检测到的题号是否为选项 OCR 错误导致的假题号。

    统一委托 ``question_numbering._is_false_question_number``。
    """
    from app.features.question_numbering import _is_false_question_number as _qn_is_false
    return _qn_is_false(num, line)


def _looks_like_paren_question(line: str, match_end: int) -> bool:
    rest = line[match_end:].lstrip()
    num_text = line[:match_end].rstrip(" )）")
    if len(num_text) >= 2 and rest:
        return True
    return bool(re.match(r"(?:第\s*)?\S+题", rest))


def _looks_like_grouped_option_marker(line: str, match_end: int) -> bool:
    rest = line[match_end:].lstrip()
    return bool(re.match(r"(?:[?？]\s*)?[A-Da-d]\s*[.．、:：)）\s]", rest))


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
    if not re.match(r"^(?:\d+\s*[)）]|[（(]\s*\d+\s*[）)])", line):
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

    # 文本含罗马数字子项枚举时，行首 "I." 是多选子项而非题号，
    # 跳过其边界检测，避免把一道多选题切成两题（docs/BUGS.md 案例一/二/五/六）。
    roman_list = _has_roman_subitem_list(text)

    char_pos = 0
    previous_num: int | None = None
    in_subquestion = False
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if roman_list and _RE_ROMAN_SUBITEM_MARKER.match(stripped):
            char_pos += len(line) + 1
            continue

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


def _parse_leading_space_option_from_text(text: str) -> tuple[str, str] | None:
    match = _LEADING_SPACE_OPTION_PATTERN.match(text.strip())
    if not match:
        return None
    key = match.group(1).upper()
    value = _truncate_answer_explanation_tail(match.group(2))
    if not value:
        return None
    return key, value


def _parse_grouped_options_from_text(text: str) -> dict[str, str]:
    parsed = _parse_options_from_text(text)
    leading_option = _parse_leading_space_option_from_text(text)
    if leading_option and leading_option[0] not in parsed:
        key, value = leading_option
        parsed = {key: value, **parsed}

    if len(parsed) >= 2:
        return parsed

    text = text.strip()
    options: dict[str, str] = {}
    token_pattern = re.compile(
        r"(?<![A-Za-z0-9])([A-Da-d])\s*(?:[.．、:：)）]\s*|[、，,，]|\s+)"
    )
    matches = list(token_pattern.finditer(text))
    if len(matches) < 2:
        return parsed

    for idx, match in enumerate(matches):
        key = match.group(1).upper()
        value_start = match.end()
        value_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        value = _truncate_answer_explanation_tail(text[value_start:value_end])
        if key not in options and value:
            options[key] = value

    return options if len(options) >= 2 else parsed


def _line_group_marker(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    marker_chars = re.escape(_CIRCLED_OPTION_CHARS)
    roman_chars = re.escape(_ROMAN_MARKER_CHARS)
    m = re.match(
        rf"^(?:"
        rf"[（(]\s*([{marker_chars}])\s*[）)]"
        rf"|([{marker_chars}])"
        rf"|[（(]\s*(\d{{1,2}})\s*[）)]"
        rf"|([{roman_chars}])"
        rf")\s*(.*)$",
        stripped,
    )
    if not m:
        return None

    marker = next(group for group in m.groups()[:-1] if group)
    rest = m.group(5).strip()
    if not rest:
        return marker, ""
    if re.match(r"^(?:[?？]\s*)?[A-Da-d]\s*[.．、:：)）\s]", rest):
        return marker, rest
    return None


def _extract_grouped_options(text: str) -> list[dict]:
    marker_chars = re.escape(_CIRCLED_OPTION_CHARS)
    text = re.sub(rf"(?<!^)\s*([{marker_chars}])\s*(?=[A-Da-d]\s)", r"\n\1 ", text)
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
                parsed = _parse_grouped_options_from_text(rest)
                if not parsed:
                    option_result = _detect_option_line(rest)
                    if option_result:
                        key, value = option_result
                        parsed[key] = _truncate_answer_explanation_tail(value)
                current["options"].update(parsed)
                if parsed:
                    last_key = next(reversed(parsed))
            continue

        if current is None:
            continue

        inline_options = _parse_grouped_options_from_text(stripped)
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


def _blank_marker_patterns(marker: str) -> list[str]:
    escaped = re.escape(marker)
    patterns = [rf"[（(]\s*{escaped}\s*[）)]"]
    if marker.isdigit():
        patterns.append(rf"[（(]\s*{escaped}\s*[）)]")
    elif marker in _ROMAN_MARKER_CHARS:
        patterns.append(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])")
    else:
        patterns.append(rf"(?<![（(]){escaped}(?!\s*[A-Da-d]\s*[.．、:：)）])")
    return patterns


def _has_numbered_blank_markers(text: str, grouped_options: list[dict]) -> bool:
    if len(grouped_options) < 2:
        return False
    markers = {str(group.get("id") or "") for group in grouped_options}
    marker_chars = re.escape(_CIRCLED_OPTION_CHARS)
    roman_chars = re.escape(_ROMAN_MARKER_CHARS)
    marker_positions = [
        match.start()
        for match in re.finditer(
            rf"(?:[{marker_chars}]|[（(]\s*(?:[{marker_chars}]|\d{{1,2}})\s*[）)]|[{roman_chars}])\s*[A-Da-d]\s*[.．、:：)）]",
            text,
        )
    ]
    stem_part = text
    if marker_positions:
        stem_part = text[:min(marker_positions)]
    marker_count = 0
    for marker in markers:
        if not marker:
            continue
        if any(re.search(pattern, stem_part) for pattern in _blank_marker_patterns(marker)):
            marker_count += 1
    return marker_count >= 2


def _flatten_first_option_group(grouped_options: list[dict]) -> dict[str, str]:
    if not grouped_options:
        return {}
    return dict(grouped_options[0].get("options") or {})


def _split_option_blocks_by_repeated_keys(text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    last_key: str | None = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or _ANSWER_EXPLANATION_LINE.match(stripped):
            continue

        inline_options = _parse_options_from_text(stripped)
        if inline_options:
            for key, value in inline_options.items():
                if key == "A" and len(current) >= 2:
                    blocks.append(current)
                    current = {}
                current[key] = value
                last_key = key
            continue

        result = _detect_option_line(stripped)
        if result:
            key, value = result
            if key == "A" and len(current) >= 2:
                blocks.append(current)
                current = {}
            current[key] = _truncate_answer_explanation_tail(value)
            last_key = key
            continue

        if last_key and last_key in current and not _detect_question_number(stripped):
            current[last_key] = f"{current[last_key]} {stripped}"

    if len(current) >= 2:
        blocks.append(current)
    return blocks


def _repair_repeated_degraded_groups(blocks: list[dict[str, str]]) -> list[dict[str, str]]:
    if len(blocks) < 2:
        return blocks

    complete_groups = [block for block in blocks if "A" in block and len(block) >= 4]
    if not complete_groups:
        return blocks

    repaired: list[dict[str, str]] = []
    for block in blocks:
        if "A" in block:
            repaired.append(block)
            continue
        matched_group = next(
            (
                group
                for group in complete_groups
                if all(group.get(key) == value for key, value in block.items())
            ),
            None,
        )
        if matched_group:
            repaired.append({"A": matched_group["A"], **block})
        else:
            repaired.append(block)
    return repaired


def _extract_degraded_blank_groups(text: str) -> list[dict]:
    plain_blank_count = len(re.findall(r"[（(]\s*[）)]", text))
    if plain_blank_count < 2:
        return []

    blocks = _repair_repeated_degraded_groups(_split_option_blocks_by_repeated_keys(text))
    if len(blocks) < plain_blank_count:
        return []

    groups = [
        {"id": str(i + 1), "options": dict(blocks[i])}
        for i in range(plain_blank_count)
        if len(blocks[i]) >= 2
    ]
    if not groups:
        return []

    unique_groups: list[dict] = []
    seen_signatures: set[tuple[tuple[str, str], ...]] = set()
    for group in groups:
        options = group.get("options") or {}
        signature = tuple((key, options[key]) for key in sorted(options))
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        unique_groups.append(group)

    return unique_groups if len(unique_groups) >= 2 else unique_groups


def scan_entire_block_including_surrounding_lines(text: str) -> dict[str, str]:
    """扫描全文（含代码块内部及周围行），提取所有选项模式。

    此函数确保 code block 不阻断 options scan：
    - 不跳过 ``` fence 内部内容
    - 扫描全文每一行

    委托至 ``question_type_classifier.extract_options_from_text``（SSOT）。

    Args:
        text: 完整题目文本（含代码块和选项行）。

    Returns:
        {key: text} 字典，至少包含 2 个选项。
    """
    from app.features.question_type_classifier import extract_options_from_text
    return extract_options_from_text(text)


# ── Code quarantine patterns (P1: Problems A/B from audit) ──
# These patterns identify lines that are code, not options.
# When a line matches, it's quarantined BEFORE option extraction so
# code content like "a)" or "b)" doesn't get extracted as options.

# Function call pattern: word(word) or word(word, word)
_RE_CODE_FUNC_CALL = re.compile(
    r"\b(?:InitStack|Push|Pop|GetTop|GetElem|ListInsert|ListDelete|"
    r"EnQueue|DeQueue|malloc|free|printf|scanf|sort|swap)\s*\("
)
# C struct/typedef patterns
_RE_CODE_STRUCT_DEF = re.compile(
    r"\b(?:typedef|struct|union|enum)\b"
)
# C keyword lines
_RE_CODE_C_KEYWORD = re.compile(
    r"\b(?:int|char|void|float|double|long|short|unsigned|signed|"
    r"const|static|extern|volatile|return|if|else|for|while|do|switch|case|break|continue|"
    r"goto|sizeof|NULL|true|false|bool|Status|ElemType)\b"
)
# Pointer operator
_RE_CODE_PTR_OP = re.compile(r"->")
# Brace or semicolon lines (code structure)
_RE_CODE_BRACE_SEMI = re.compile(r"[\{\};]")
# Struct member declaration: type *name
_RE_CODE_MEMBER_DECL = re.compile(
    r"\b(struct\s+\w+\s*\*?\s*\w+|"
    r"\w+\s+\*?\w+\s*(?:,\s*\*?\w+\s*)*;?)"
)
# C++ access specifiers
_RE_CODE_ACCESS = re.compile(r"^\s*(public|private|protected)\s*:")
# Data structure keywords
_RE_CODE_DS_KW = re.compile(
    r"\b(BiTNode|BiTree|LNode|LinkList|SqList|SqStack|BSTNode|TNode|"
    r"ListNode|LinkedList|TreeNode|Stack|Queue|DeQueue)\b"
)


def _is_code_line(line: str) -> bool:
    """Check if a line is code (not an option or natural language)."""
    stripped = line.strip()
    if not stripped:
        return False

    # CRITICAL: If the line matches an option pattern (A.xxx B.xxx etc.),
    # it is NOT code, even if it contains code-like keywords (e.g. "D.false"
    # is an option, not code). Check this FIRST.
    # Use _detect_option_line for strict validation: requires that the
    # option has a valid key (A-D), followed by separator, followed by
    # text that does NOT look like code continuation.
    _opt_match = _detect_option_line(stripped)
    if _opt_match:
        _key, _text = _opt_match
        # Even if it matches option pattern, check if the content after
        # the option marker looks like code (e.g. "a); Push(st," has "; Push(")
        # In that case, it's likely code, not an option.
        if _text and not _text.lstrip().startswith((";", "{", "}", ")", "->")):
            return False

    # Strong code signals (individually sufficient)
    if _RE_CODE_FUNC_CALL.search(stripped):
        return True
    if _RE_CODE_DS_KW.search(stripped):
        return True
    if _RE_CODE_STRUCT_DEF.search(stripped):
        return True
    if _RE_CODE_ACCESS.match(stripped):
        return True
    # Member declaration pattern
    if _RE_CODE_MEMBER_DECL.match(stripped):
        return True

    # Composite signal: needs at least 2 indicators
    signals = 0
    if _RE_CODE_C_KEYWORD.search(stripped):
        signals += 1
    if _RE_CODE_BRACE_SEMI.search(stripped):
        signals += 1
    if _RE_CODE_PTR_OP.search(stripped):
        signals += 1
    # Line starts with a closing paren (code continuation)
    if stripped.startswith(")") or stripped.startswith("}"):
        signals += 1

    return signals >= 2


def _reconstruct_code_lines(text: str) -> str:
    """Reconstruct broken code lines that were split across lines.

    Detects patterns like:
        Push(st,
        a); Push(st,
        b); Pop(st, x);

    And merges them into:
        Push(st, a); Push(st, b); Pop(st, x);
    """
    if not text:
        return text

    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()

        # Check if line ends with a comma or open paren (code continuation)
        # e.g. "Push(st," or "InitStack(st); Push(st,"
        if stripped and (stripped.rstrip().endswith(",") or
                         stripped.rstrip().endswith("(") or
                         re.search(r"\w+\([^)]*$", stripped.rstrip())):
            # Look ahead: merge subsequent lines until we find closing paren
            merged = stripped
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if not next_line:
                    break
                # Merge: remove leading spaces from continuation
                merged += " " + next_line
                j += 1
                # Stop when we've closed all open parens
                open_parens = merged.count("(") - merged.count(")")
                if open_parens <= 0:
                    break
            result.append(merged)
            i = j
        else:
            result.append(line)
            i += 1

    return "\n".join(result)


def _quarantine_code_regions(text: str) -> tuple[str, list[tuple[int, int, str]]]:
    """Identify and quarantine code regions in text before option extraction.

    Scans text line by line. Lines identified as code are replaced with
    placeholders. The original code lines are returned separately so they
    can be restored as code_blocks after option extraction.

    Args:
        text: Full text (stem + possibly options + possibly code).

    Returns:
        (cleaned_text, code_regions) where cleaned_text has code lines
        replaced with placeholders, and code_regions is a list of
        (start_line, end_line, code_content) tuples.
    """
    lines = text.split("\n")
    code_regions: list[tuple[int, int, str]] = []

    # First pass: detect code regions (contiguous code lines)
    in_code = False
    region_start = 0
    code_lines: list[str] = []

    for i, line in enumerate(lines):
        is_code = _is_code_line(line)
        if is_code and not in_code:
            in_code = True
            region_start = i
            code_lines = [line]
        elif is_code and in_code:
            code_lines.append(line)
        elif not is_code and in_code:
            in_code = False
            # Quarantine code regions: multi-line (≥2) or single line with
            # strong code signals (multiple function calls with semicolons)
            if len(code_lines) >= 2:
                code_regions.append((region_start, i - 1, "\n".join(code_lines)))
            elif len(code_lines) == 1 and code_lines[0].count(";") >= 2:
                # Single line with multiple statements (e.g. after code reconstruction)
                code_regions.append((region_start, i - 1, code_lines[0]))
            code_lines = []

    # Handle trailing code region
    trailing_code = code_lines
    if in_code:
        if len(trailing_code) >= 2:
            code_regions.append((region_start, len(lines) - 1, "\n".join(trailing_code)))
        elif len(trailing_code) == 1 and trailing_code[0].count(";") >= 2:
            code_regions.append((region_start, len(lines) - 1, trailing_code[0]))

    if not code_regions:
        return text, []

    # Second pass: replace code lines with placeholders
    result_lines = list(lines)
    for start, end, content in reversed(code_regions):
        for li in range(start, end + 1):
            result_lines[li] = f"__CODE_LINE_{li}__"

    return "\n".join(result_lines), code_regions


def _is_ocr_garbage_line(line: str) -> bool:
    """Check if a non-option line between options is likely OCR corruption.

    Detects lines with non-ASCII characters outside CJK ranges
    (Greek, Cyrillic, etc.), which are strong signals of OCR corruption
    in code or Chinese exam option text. Legitimate continuation lines
    contain only ASCII (code) or CJK characters (Chinese text).

    Returns:
        True if the line appears to be OCR garbage.
    """
    for ch in line:
        cp = ord(ch)
        if cp > 127:
            # Allow common CJK ranges
            if 0x3000 <= cp <= 0x303F:   # CJK symbols and punctuation
                continue
            if 0x4E00 <= cp <= 0x9FFF:   # CJK unified ideographs
                continue
            if 0xFF00 <= cp <= 0xFFEF:   # Fullwidth forms
                continue
            # Any other non-ASCII (Greek, Cyrillic, arrows, etc.) → signal
            return True
    return False


def _extract_options(text: str) -> dict[str, str]:
    """从题目文本中提取选项行。

    使用多级检测：
    0. 代码隔离 — 识别代码区域并 quarantine，防止代码被误识别为选项
    1. 标准行内检测（_INLINE_OPTION_PATTERN）
    2. 逐行检测（_detect_option_line）
    3. SSOT 回退（extract_options_from_text）— 委托至 question_type_classifier 统一入口

    P1.1 (Code quarantine): Before option extraction, reconstruct broken code lines
    (e.g. Push(st,\\n a) -> Push(st, a)) and quarantine code regions to prevent
    code content like "a)" or "b)" from being extracted as options.
    """
    # Step 0a: Reconstruct broken code lines first (Case 4 from BUGS)
    text = _reconstruct_code_lines(text)

    # Step 0b: Quarantine code regions before option extraction
    cleaned_text, code_regions = _quarantine_code_regions(text)

    options: dict[str, str] = {}
    last_key: str | None = None
    for line in cleaned_text.split("\n"):
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
            and not _is_ocr_garbage_line(stripped)
        ):
            options[last_key] = f"{options[last_key]} {stripped}"

    # FALLBACK: 委托至 question_type_classifier SSOT 进行宽模式提取
    # 覆盖代码片段、断裂 OCR 等导致行首匹配失败的情况
    if len(options) < 2:
        from app.features.question_type_classifier import extract_options_from_text as _ssot_extract
        fallback_opts = _ssot_extract(cleaned_text)
        if len(fallback_opts) >= len(options):
            options = fallback_opts
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


def _get_span_blocks(
    start_pos: int,
    end_pos: int,
    page_map: list[tuple[int, int, int]],
) -> set[tuple[int, int]]:
    """Get set of (page, block_idx) that overlap with the given text span.

    Used to match a question's text span to specific normalized blocks,
    so frozen options can be bound at block granularity instead of page
    granularity (preventing cross-contamination between blocks on the same page).
    """
    blocks: set[tuple[int, int]] = set()
    for i, (pos, page, block_idx) in enumerate(page_map):
        block_end = page_map[i + 1][0] if i + 1 < len(page_map) else float("inf")
        if pos < end_pos and block_end > start_pos:
            blocks.add((page, block_idx))
    return blocks


def split_questions(
    normalized_blocks: list[dict],
    structure: dict | None = None,
    gap_tolerance: int = 10,
    import_mode: str | None = None,
    layout_result: dict | None = None,
    split_mode: str = "standard",
    frozen_option_registry: dict | None = None,
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
        layout_result: layout_reconstruction 的输出（可选）。
            当 text-only option extraction 找不到选项时，
            使用 layout 的 spatial option_groups 作为补充。
        split_mode: 路由模式。
            "standard"        — 标准模式，layout 仅当 text 找不到选项时注入。
            "layout_enhanced" — Layout 增强模式，主动融合 layout+text 选项，
                                使用 reading_order 优化边界检测。
            "vl_rebuild"      — VL 重建模式，layout_result 可能为空。
        frozen_option_registry: Structure Freeze Stage 的输出。
            非 None 时表示结构冻结层已运行，选项将由下游 `_apply_frozen_options`
            统一注入，此处跳过所有 regex 选项提取，确保冻结结构为唯一事实源。

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

    # ── Structure Freeze: precompute which pages have frozen option data ──
    frozen_pages: set[int] = set()
    if frozen_option_registry:
        for key in frozen_option_registry:
            try:
                frozen_pages.add(int(key.split(":")[0]))
            except (ValueError, IndexError):
                pass

    for i, (num, start_pos) in enumerate(filtered_boundaries):
        end_pos = filtered_boundaries[i + 1][1] if i + 1 < len(filtered_boundaries) else len(full_text)
        raw_text = full_text[start_pos:end_pos].strip()

        page_start = _pos_to_page(start_pos, page_map)
        page_end = _pos_to_page(max(start_pos, end_pos - 1), page_map)

        grouped_options = _extract_grouped_options(raw_text)
        has_grouped_options = _has_numbered_blank_markers(raw_text, grouped_options)
        if not has_grouped_options:
            degraded_groups = _extract_degraded_blank_groups(raw_text)
            if degraded_groups:
                grouped_options = degraded_groups
                has_grouped_options = True

        # ── Structure Freeze: skip all regex option extraction when frozen data exists ──
        # frozen_option_registry is the SINGLE SOURCE OF TRUTH. When the freeze stage
        # has produced entries for any page in this question's range, skip ALL regex
        # option extraction (including _extract_options and layout injection).
        # Options will be injected by _apply_frozen_options downstream.
        freeze_has_page_data = bool(
            frozen_pages and (page_start in frozen_pages or page_end in frozen_pages)
        )

        # P0 (Problem C): Strip frozen option text from raw_text when freeze data exists.
        # This prevents option text from appearing in the stem after _extract_stem().
        # P0 (Cross-contamination): Collect frozen options at BLOCK granularity,
        # not page granularity, so questions on the same page don't cross-contaminate.
        q_frozen_opts: dict[str, str] = {}
        original_raw: str | None = None
        if freeze_has_page_data and frozen_option_registry:
            span_blocks = _get_span_blocks(start_pos, end_pos, page_map)
            for fkey, fopts in frozen_option_registry.items():
                try:
                    fparts = fkey.split(":")
                    fk_page = int(fparts[0])
                    fk_block = int(fparts[1]) if len(fparts) > 1 else -1
                    if len(fparts) == 1:
                        logger.debug(
                            "[FREEZE] key %r has no block index (old format), "
                            "falling back to page-level matching",
                            fkey,
                        )
                except (ValueError, IndexError):
                    continue
                if (fk_page, fk_block) in span_blocks:
                    q_frozen_opts.update(dict(fopts))
            if q_frozen_opts:
                # Save original text before stripping so match_answers can
                # extract explicit answers from it downstream.
                original_raw = raw_text
                stripped_raw = strip_frozen_options_from_stem(raw_text, q_frozen_opts)
                if stripped_raw and len(stripped_raw) < len(raw_text):
                    logger.info(
                        "split: stripped frozen options from stem for q%d "
                        "(removed %d chars, frozen_opts=%s)",
                        num, len(raw_text) - len(stripped_raw),
                        sorted(q_frozen_opts.keys()),
                    )
                    raw_text = stripped_raw

        if freeze_has_page_data:
            if q_frozen_opts:
                # Directly assign frozen options instead of leaving them empty
                # for _apply_frozen_options downstream. That function's text-substring
                # matching (block_text in q_text) FAILS because split_questions
                # stripped frozen option lines from raw_question_text above —
                # the full block text (with options) is no longer a substring of
                # the question text (without options).
                options = dict(q_frozen_opts)
            else:
                # Frozen data exists on this page but no block-level match for
                # this question — fall back to regex to avoid missing options.
                options = _extract_options(raw_text)
        elif has_grouped_options:
            options = {}
        else:
            options = _extract_options(raw_text)

        # Layout-aware option injection: use layout's spatial option_groups
        # when text-only extraction is insufficient.
        # NOTE: skipped entirely when frozen data exists (freeze is the sole source of truth).
        if not freeze_has_page_data and not has_grouped_options and layout_result:
            page_key = str(page_start)
            layout_page_opts = layout_result.get("option_groups", {}).get(page_key, {})

            if split_mode == "layout_enhanced" and layout_page_opts:
                # LAYOUT_ENHANCED: 主动融合 layout + text 选项。
                # 用 layout 选项填充 text 未找到的 gap，保留 text 已找到的选项。
                merged = dict(options)
                for k, v in layout_page_opts.items():
                    if k not in merged:
                        merged[k] = v
                if len(merged) > len(options):
                    logger.info(
                        "split: layout_enhanced merged options for q%d "
                        "(page=%s, text=%d, layout=%d, merged=%d)",
                        num, page_key, len(options), len(layout_page_opts), len(merged),
                    )
                    options = merged
            elif len(options) < 2:
                # STANDARD / VL_REBUILD: 仅当 text 找不到选项时注入
                if layout_page_opts and len(layout_page_opts) >= 2:
                    options = dict(layout_page_opts)
                    logger.info(
                        "split: injected layout options for q%d "
                        "(page=%s, text_found=%d, layout_found=%d)",
                        num, page_key, len(options), len(layout_page_opts),
                    )

        # 置信度：基于题号格式清晰度 + 选项完整度
        conf = 0.9
        if raw_text.count("\n") <= 1:
            conf -= 0.1  # 极短文本
        if options and len(options) >= 3:
            conf = min(1.0, conf + 0.05)
        if num <= 0:
            conf -= 0.3
        # LAYOUT_ENHANCED: 结构不稳定时适度降权
        if split_mode == "layout_enhanced":
            conf -= 0.05
        elif split_mode == "vl_rebuild":
            conf -= 0.1  # VL 重建的 blocks 无 bbox，置信度更低

        # Determine section_type from the most recent question_type_* marker
        section_type = None
        if section_type_markers:
            for marker_page, marker_type in reversed(section_type_markers):
                if page_start >= marker_page:
                    section_type = marker_type
                    break

        # ── 风险标记 ──
        risk_flags: list[str] = []
        if freeze_has_page_data and frozen_option_registry and not q_frozen_opts:
            risk_flags.append("frozen_options_unmatched")

        # ── 提取原题号信息（用于审核定位） ──
        source_question_no = str(num) if num and num > 0 else None
        source_question_label = _extract_first_line_label(raw_text)

        questions.append({
            "number": num,
            "raw_question_text": raw_text,
            # Preserve original text (before frozen-option stripping) so
            # match_answers can extract explicit answers from it.
            "_original_raw_text": original_raw if freeze_has_page_data and q_frozen_opts else None,
            "page_start": page_start,
            "page_end": page_end,
            "has_options": len(options) > 0,
            "option_lines": options,
            "blank_option_groups": grouped_options if has_grouped_options else [],
            "has_grouped_options": has_grouped_options,
            "is_frozen": freeze_has_page_data,
            "confidence": round(max(0.0, min(1.0, conf)), 2),
            "section_type": section_type,
            "risk_flags": risk_flags,
            # ── 原题定位信息 ──
            "source_question_no": source_question_no,
            "source_question_label": source_question_label,
        })

    questions = _recover_cross_page_options(questions)

    # Detect and split questions that were merged due to two-column OCR layout
    # (see docs/BUGS.md 案例二)
    questions = _split_merged_two_column_questions(questions)

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
        if not has_grouped_options:
            degraded_groups = _extract_degraded_blank_groups(raw_text)
            if degraded_groups:
                grouped_options = degraded_groups
                has_grouped_options = True
        options = {} if has_grouped_options else _extract_options(raw_text)

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
# Two-column merge detection — split questions merged by OCR two-column layout
# (see docs/BUGS.md 案例二)
# ---------------------------------------------------------------------------

# Pattern: option text that contains a second question stem (ends with （） or ())
_RE_EMBEDDED_QUESTION = re.compile(
    r"[；;]\s*.{2,30}?[（(]\s*[）)]\s*$"
)

# Pattern to find the second group's first option marker in raw text
_RE_SECOND_GROUP_A = re.compile(
    r"\n\s*A\s*[.、:：)）]"
)


def _split_merged_two_column_questions(questions: list[dict]) -> list[dict]:
    """Detect and split questions that were merged due to two-column OCR layout.

    Detection signals:
    - has_grouped_options is True with exactly 2 blank_option_groups
    - Each group has 4 options (A/B/C/D)
    - Group 1 options are shuffled (not in A/B/C/D order)
    - Group 1's last option text contains an embedded question stem pattern
    """
    result: list[dict] = []
    for q in questions:
        groups = q.get("blank_option_groups") or []
        if len(groups) != 2:
            result.append(q)
            continue

        g1, g2 = groups
        g1_opts = dict(g1.get("options", {}))
        g2_opts = dict(g2.get("options", {}))

        # Both groups must have 4 options each
        if len(g1_opts) < 4 or len(g2_opts) < 4:
            result.append(q)
            continue

        # Group 1 options must be shuffled (not A/B/C/D order)
        g1_keys = list(g1_opts.keys())
        if g1_keys == sorted(g1_keys):
            result.append(q)
            continue

        # Group 1's last option must contain embedded question pattern
        last_key = g1_keys[-1]
        last_text = g1_opts.get(last_key, "")
        embed_match = _RE_EMBEDDED_QUESTION.search(last_text)
        if not embed_match:
            result.append(q)
            continue

        # Found a merged question — split it
        raw_text = q.get("raw_question_text", "")

        # Extract Q2 stem from Q1's last option
        split_pos = embed_match.start()
        q2_stem_suffix = last_text[split_pos:].lstrip("；;；; ")

        # Truncate Q1's last option to remove the embedded Q2 content
        g1_opts[last_key] = last_text[:split_pos].rstrip("；;；; ")

        # Find where Q2's options start in raw_text
        # Look for the second A option marker (group 2's first option)
        a_matches = list(_RE_SECOND_GROUP_A.finditer(raw_text))
        if len(a_matches) >= 2:
            q2_start = a_matches[1].start() + 1  # skip leading \n
            q1_raw = raw_text[:q2_start].strip()
            q2_opts_raw = raw_text[q2_start:].strip()
        else:
            # Fallback: reconstruct from groups
            q1_raw = raw_text
            q2_opts_raw = "\n".join(
                f"{k}. {v}" for k, v in sorted(g2_opts.items())
            )

        # Create Q1 (with cleaned-up options)
        q1_options = {
            k: v for k, v in sorted(g1_opts.items())
        }
        q1_new = dict(q)
        q1_new["raw_question_text"] = q1_raw
        q1_new["option_lines"] = q1_options
        q1_new["blank_option_groups"] = []
        q1_new["has_grouped_options"] = False
        q1_new["has_options"] = len(q1_options) > 0
        q1_new["risk_flags"] = list(dict.fromkeys(
            (q.get("risk_flags") or []) + ["two_column_merge_split"]
        ))
        q1_new["confidence"] = min(q.get("confidence", 0.5), 0.5)
        result.append(q1_new)

        # Create Q2 (new question from the split-off content)
        q2_stem = q2_stem_suffix.strip()
        q2_raw = f"{q2_stem}\n{q2_opts_raw}"
        q2_options = {
            k: v for k, v in sorted(g2_opts.items())
        }
        result.append({
            "number": q.get("number", 0) + 0.5,  # fractional → signals auto-split
            "raw_question_text": q2_raw,
            "page_start": q.get("page_start", 1),
            "page_end": q.get("page_end", q.get("page_start", 1)),
            "has_options": True,
            "option_lines": q2_options,
            "blank_option_groups": [],
            "has_grouped_options": False,
            "confidence": 0.4,
            "section_type": q.get("section_type"),
            "risk_flags": ["two_column_merge_split"],
        })

    return result


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
