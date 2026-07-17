"""Unified Question Numbering Parser — SSOT for all question number detection.

Provides a single ``parse_numbering()`` entry point that replaces:

- ``question_splitter._detect_question_number()``
- ``question_splitter._is_false_question_number()``
- ``cross_page_linking._has_new_question_number()``

All question-number related patterns, normalization, and false-positive rejection
live here. No other module maintains its own question-number regex.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

logger = logging.getLogger(__name__)


# ===================================================================
# Numbering type enum
# ===================================================================


class NumberingType(str, Enum):
    """Classification of a detected numbering marker."""

    MAIN_QUESTION = "main_question"
    """Top-level question number: 1., 2., 一、, 二、, 第1题, 第一题"""

    SUB_QUESTION = "sub_question"
    """Sub-question within a compound: (1), (2), ①, ②, (一), (二)"""

    SUB_SUB_QUESTION = "sub_sub_question"
    """Sub-sub-question: (a), (b)"""

    OPTION = "option"
    """Option letter: A., B., C., D."""

    OPTION_ROMAN = "option_roman"
    """Roman numeral option: I., II., III., IV."""

    OPTION_CIRCLED = "option_circled"
    """Circled option: ①, ②, ③"""

    ANSWER = "answer"
    """Answer marker: 答案：A, 正确答案：B"""

    SECTION = "section"
    """Section header: 一、选择题, 第一章, Part I"""

    ORDINAL = "ordinal"
    """Ordinal in prose: 第一步, 第一个, 第一种"""

    FALSE_POSITIVE = "false_positive"
    """Detected but rejected as not a real numbering."""


# ===================================================================
# ParsedNumbering dataclass
# ===================================================================


@dataclass
class ParsedNumbering:
    """Result of parsing a numbering marker from text.

    ``raw``: the original matched text fragment (e.g. ``"1."``, ``"一、"``).
    ``normalized_value``: integer representation for comparison (1 for both ``"1"`` and ``"一"``).
    ``numbering_type``: classification (see ``NumberingType``).
    ``hierarchy_level``: 0=main, 1=sub, 2=sub-sub, -1=non-question (section/ordinal/false).
    ``confidence``: 0.0 – 1.0 how confident this is a real question number.
    ``start``: character offset of match start in source string.
    ``end``: character offset of match end in source string.
    """

    raw: str
    normalized_value: int
    numbering_type: NumberingType
    hierarchy_level: int
    confidence: float
    start: int
    end: int

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "normalized_value": self.normalized_value,
            "numbering_type": self.numbering_type.value,
            "hierarchy_level": self.hierarchy_level,
            "confidence": round(self.confidence, 4),
            "start": self.start,
            "end": self.end,
        }


# ===================================================================
# Constants — Chinese/Roman numeral maps
# ===================================================================

_CN_NUM_MAP: dict[str, int] = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

_CN_UPPER_MAP: dict[str, int] = {
    "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5,
    "陆": 6, "柒": 7, "捌": 8, "玖": 9, "拾": 10,
}

_HEAVENLY_STEMS_MAP: dict[str, int] = {
    "甲": 1, "乙": 2, "丙": 3, "丁": 4, "戊": 5,
    "己": 6, "庚": 7, "辛": 8, "壬": 9, "癸": 10,
}

_ROMAN_MAP: dict[str, int] = {
    "Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5,
    "Ⅵ": 6, "Ⅶ": 7, "Ⅷ": 8, "Ⅸ": 9, "Ⅹ": 10,
}
_ROMAN_LOWER_MAP: dict[str, int] = {
    "ⅰ": 1, "ⅱ": 2, "ⅲ": 3, "ⅳ": 4, "ⅴ": 5,
    "ⅵ": 6, "ⅶ": 7, "ⅷ": 8, "ⅸ": 9, "ⅹ": 10,
}

_ROMAN_ASCII_MAP: dict[str, int] = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
}

_CIRCLED_MAP: dict[str, int] = {
    "①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5,
    "⑥": 6, "⑦": 7, "⑧": 8, "⑨": 9, "⑩": 10,
}

_HEAVENLY_STEM_CHARS = "".join(_HEAVENLY_STEMS_MAP.keys())
_ROMAN_CHARS = "".join(_ROMAN_MAP.keys())
_CIRCLED_CHARS = "".join(_CIRCLED_MAP.keys())

# The complete set of chars that can serve as "A" in a section like "一、选择题"
_CN_TIANTOU_PAT = "".join(_CN_NUM_MAP.keys())


# ===================================================================
# False-positive patterns — prose ordinals to reject
# ===================================================================

# These patterns match ordinary prose that looks superficially like numbering
# but are not question numbers.
_FALSE_POSITIVE_PATTERNS: list[re.Pattern] = [
    # 第一步 / 第二个 / 第三种
    re.compile(r"^第\s*[" + _CN_TIANTOU_PAT + r"\d]+\s*[步个种类阶项级条]"),
    # 一种 / 一类 / 一项
    re.compile(r"^[" + _CN_TIANTOU_PAT + r"]+\s*[种类项条个套例组派系]"),
    # 甲公司 / 乙公司 / 丙公司
    re.compile(r"^[" + _HEAVENLY_STEM_CHARS + r"]{1,2}\s*公司"),
    # 甲与乙 / 甲和乙
    re.compile(r"^[" + _HEAVENLY_STEM_CHARS + r"]\s*[与和及或]"),
    # 有三个 / 存在两个 / 包含三种
    re.compile(r"^[有存含包用]\s*[" + _CN_TIANTOU_PAT + r"\d]+\s*[个种项条]"),
    # 下列选项中
    re.compile(r"^下列选项"),
    # 以下说法 / 以下关于
    re.compile(r"^以下"),
    # 则 / 若 / 设 — 这些是数学/逻辑条件语，不是题号
    re.compile(r"^[则若设]"),
    # 故 / 因此 / 由此
    re.compile(r"^(?:故|因此|由此|综上|综上所述|所以)"),
    # Page header/footer text
    re.compile(r"^(?:第\s*\d+\s*页|\d+\s*/+\s*\d+|-\s*\d+\s*-)"),
]

# Patterns for section headers that should not be treated as question numbers
_SECTION_HEADER_PATTERNS: list[re.Pattern] = [
    # 一、选择题 / 二、填空题 / 三、解答题 (known section keywords)
    re.compile(
        r"^[" + _CN_TIANTOU_PAT + r"]+\s*[、.．]\s*"
        r"(?:单项选择|多项选择|选择|单选|多选|判断|填空|简答|"
        r"计算|证明|综合应用|综合|解答|论述|分析|程序设计|应用|"
        r"名词解释|画图|改错|编程|问答|列举|简述)"
        r"(?:题|部分)?"
    ),
    # Part I / Part II / Part III
    re.compile(r"^Part\s+(I|II|III|IV|V)\b"),
    # 第一章 / 第二章 / 第一节
    re.compile(r"^第\s*[" + _CN_TIANTOU_PAT + r"\d]+\s*[章节篇]"),
    # Section number patterns: 1.1 / 1.1.1 / 10.2.3
    re.compile(r"^\d+\.\d+(\.\d+)?\s*\S"),
    # Review/exercise markers
    re.compile(r"^(?:习题精选|练习题|巩固练习|真题精选|模拟题)"),
]

# +4 or more digits as a question number → unlikely
_LONG_NUMBER_RE = re.compile(r"^\d{4,}\s*[.、)）]")


# ===================================================================
# Compiled pattern definitions
# ===================================================================


def _build_patterns() -> list[tuple[re.Pattern, NumberingType, int, float]]:
    """Build ordered list of (pattern, type, hierarchy_level, base_confidence).

    Ordered most-specific first. The first match wins.
    """
    patterns: list[tuple[re.Pattern, NumberingType, int, float]] = []

    # ── Main question: Arabic digits ──
    # "1." "1．" "1、" "1) " "1）"
    patterns.append((re.compile(r"^(\d+)\s*[.．、]"), NumberingType.MAIN_QUESTION, 0, 0.95))
    patterns.append((re.compile(r"^(\d+)\s*[)）]"), NumberingType.MAIN_QUESTION, 0, 0.90))
    # "(1)" → ambiguous (could be sub-question), detect by context
    patterns.append((re.compile(r"^\((\d+)\)"), NumberingType.SUB_QUESTION, 1, 0.85))
    patterns.append((re.compile(r"^（(\d+)）"), NumberingType.SUB_QUESTION, 1, 0.85))
    # "【1】"
    patterns.append((re.compile(r"^【(\d+)】"), NumberingType.MAIN_QUESTION, 0, 0.85))
    # "第1题" "第01题"
    patterns.append((re.compile(r"^第\s*(\d+)\s*题"), NumberingType.MAIN_QUESTION, 0, 0.90))

    # ── Main question: Chinese numerals ──
    # "第一题" "第二题"
    cn_chars = "".join(_CN_NUM_MAP.keys())
    patterns.append((
        re.compile(r"^第\s*([" + cn_chars + r"]+)\s*题"),
        NumberingType.MAIN_QUESTION, 0, 0.90,
    ))
    # "一、" "二、" "三、" at line start (main question in exam papers)
    patterns.append((
        re.compile(r"^([" + cn_chars + r"])\s*[、.．]"),
        NumberingType.MAIN_QUESTION, 0, 0.85,
    ))
    # "（一）" "（二）" (sub-question)
    patterns.append((
        re.compile(r"^（([" + cn_chars + r"])）"),
        NumberingType.SUB_QUESTION, 1, 0.80,
    ))
    # "(一)" "(二)" (sub-question)
    patterns.append((
        re.compile(r"^\(([" + cn_chars + r"])\)"),
        NumberingType.SUB_QUESTION, 1, 0.80,
    ))

    # ── Heavenly stems: 甲、乙、丙 (option-like) ──
    patterns.append((
        re.compile(r"^([" + _HEAVENLY_STEM_CHARS + r"])\s*[.、)）]"),
        NumberingType.OPTION, 1, 0.75,
    ))

    # ── Roman numerals ──
    # Unicode Roman: Ⅰ、Ⅱ、Ⅲ
    patterns.append((
        re.compile(r"^([" + _ROMAN_CHARS + r"])\s*[.、)）]"),
        NumberingType.OPTION_ROMAN, 0, 0.80,
    ))
    # ASCII Roman: I. II. III. (be careful: single "I" alone is common)
    # Match only multi-char Roman or I followed by .、::
    patterns.append((
        re.compile(r"^(I{2,3}|IV|VI{0,3})\s*[.、)）:]"),
        NumberingType.OPTION_ROMAN, 0, 0.75,
    ))
    # (I) (II) (III) in parens
    patterns.append((
        re.compile(r"^\(((?:[IVX]+|[" + _ROMAN_CHARS + r"]+))\)"),
        NumberingType.OPTION_ROMAN, 1, 0.70,
    ))

    # ── Circled numbers ──
    # ① ② ③ (typically sub-question markers)
    patterns.append((
        re.compile(r"^([" + _CIRCLED_CHARS + r"])"),
        NumberingType.OPTION_CIRCLED, 1, 0.85,
    ))

    # ── OCR fallback: l/I → 1 ──
    patterns.append((
        re.compile(r"^([lI])\s*[.、)）]"),
        NumberingType.MAIN_QUESTION, 0, 0.50,
    ))

    # ── Answer markers (not numbering, but useful to identify) ──
    patterns.append((
        re.compile(r"^(?:答案|正确答案|参考答案)\s*[：:]"),
        NumberingType.ANSWER, -1, 1.0,
    ))

    return patterns


_PATTERNS = _build_patterns()


# ===================================================================
# Characteristic detection helpers
# ===================================================================


_HAS_QUESTION_CHARACTERISTICS_RE = re.compile(
    r"[（(][^）)]{0,20}[）)]|下列|以下|正确|错误|问|求|计算|证明|已知|若|设|则|哪|？|\?"
)

_OPTION_LETTER_RE = re.compile(r"^[A-Da-d]\s*[.．、:：)）]")


def _looks_like_question_marker(text: str) -> bool:
    """Check if text looks like it could follow a question number."""
    if not text:
        return False
    # Has explicit question marker
    if re.match(r"(?:第\s*)?\S+题", text):
        return True
    # Has technical/symbol content (short answers, etc.)
    if re.match(r"[A-Za-z0-9+\-*/=<>^_{}()\[\]]", text):
        return True
    return False


# ===================================================================
# Public API
# ===================================================================


def parse_numbering(
    text: str,
    *,
    at_line_start: bool = True,
    allow_continuation_markers: bool = False,
) -> ParsedNumbering | None:
    """Parse a numbering marker from ``text``.

    Args:
        text: The text to parse (typically one line or the first line of a block).
        at_line_start: If True, only match at the very beginning of the text.
        allow_continuation_markers: If True, also detect explicit continuation
            markers like ``（接上页）``.

    Returns:
        A ``ParsedNumbering`` if a valid numbering is detected, or ``None``.
    """
    if not text or not text.strip():
        return None

    stripped = text.lstrip()
    stripped_offset = len(text) - len(stripped)

    # ── Step 1: Check section headers first ──
    for sec_pat in _SECTION_HEADER_PATTERNS:
        m = sec_pat.match(stripped)
        if m:
            raw = m.group(0)
            return ParsedNumbering(
                raw=raw,
                normalized_value=0,
                numbering_type=NumberingType.SECTION,
                hierarchy_level=-1,
                confidence=0.95,
                start=stripped_offset,
                end=stripped_offset + m.end(),
            )

    # ── Step 1b: Reject year annotations like (2020), （2021） ──
    # A 4-digit number in parens is almost certainly a year, not a sub-question
    _year_match = re.match(r"^[（(](\d{4})[）)]", stripped)
    if _year_match:
        return None

    # ── Step 2: Check false-positive prose patterns ──
    for fp_pat in _FALSE_POSITIVE_PATTERNS:
        if fp_pat.match(stripped):
            return None

    # ── Step 3: Check long number (4+ digits) ──
    if _LONG_NUMBER_RE.match(stripped):
        return None

    # ── Step 4: Match against numbering patterns ──
    for pat, ntype, hlevel, base_conf in _PATTERNS:
        m = pat.match(stripped)
        if not m:
            continue
        raw = m.group(0)
        # Handle patterns without capture groups (e.g. ANSWER)
        try:
            num_str = m.group(1)
        except IndexError:
            return ParsedNumbering(
                raw=raw,
                normalized_value=0,
                numbering_type=ntype,
                hierarchy_level=hlevel,
                confidence=base_conf,
                start=stripped_offset,
                end=stripped_offset + m.end(),
            )
        normalized = _normalize_number(num_str, ntype)
        if normalized is None:
            continue

        start = stripped_offset + m.start()
        end = stripped_offset + m.end()

        # ── Step 5: Apply false-positive filters specific to each type ──
        confidence = base_conf

        if ntype is NumberingType.MAIN_QUESTION:
            # Check for false question numbers (OCR errors, edge cases)
            if _is_false_question_number(normalized, stripped):
                return None

            # "1." followed by another digit and dot → section number "1.1"
            if pat.pattern.startswith(r"^(\d+)\s*[.．、]"):
                after = stripped[m.end():].lstrip()
                if after and (after[0].isdigit() or after[0] in ".．"):
                    return None

            # "1)..." pattern: reject if text after doesn't look like a question
            # (e.g., "1)假如" has short num_text, no "题" marker)
            if raw.rstrip().endswith((")", "）")):
                after_text = stripped[m.end():].strip()
                num_text = raw.rstrip(" )）")
                if not (len(num_text) >= 2 and after_text) and not _looks_like_question_marker(after_text):
                    return None

            # Boost for lines with question characteristics
            if not _is_false_question_number(normalized, stripped):
                # Boost for lines with question characteristics
                after_text = stripped[m.end():]
                if _HAS_QUESTION_CHARACTERISTICS_RE.search(after_text):
                    confidence = min(1.0, confidence + 0.05)

        elif ntype is NumberingType.SUB_QUESTION:
            # Adjust confidence based on context
            pass

        elif ntype is NumberingType.OPTION_ROMAN:
            # Check that it's not part of a section heading
            # e.g. "Part I" already caught by section patterns
            pass

        return ParsedNumbering(
            raw=raw,
            normalized_value=normalized,
            numbering_type=ntype,
            hierarchy_level=hlevel,
            confidence=round(confidence, 4),
            start=start,
            end=end,
        )

    return None


def _normalize_number(num_str: str, ntype: NumberingType) -> int | None:
    """Convert a number string to its integer representation."""
    if ntype is NumberingType.ANSWER:
        return 0

    # Circled numbers can pass str.isdigit() but fail int()
    if num_str and num_str[0] in _CIRCLED_MAP:
        return _CIRCLED_MAP[num_str[0]]

    # Pure Arabic digits
    if num_str.isdigit():
        try:
            return int(num_str)
        except ValueError:
            pass

    # Chinese numerals
    if num_str and num_str[0] in _CN_NUM_MAP:
        return _cn_string_to_int(num_str)

    # Heavenly stems
    if num_str and num_str[0] in _HEAVENLY_STEMS_MAP:
        return _HEAVENLY_STEMS_MAP.get(num_str[0])

    # Roman (Unicode)
    if num_str and num_str[0] in _ROMAN_MAP:
        return _ROMAN_MAP.get(num_str[0])
    if num_str and all(c in _ROMAN_LOWER_MAP for c in num_str):
        return _ROMAN_LOWER_MAP.get(num_str[0])

    # ASCII Roman
    if num_str in _ROMAN_ASCII_MAP:
        return _ROMAN_ASCII_MAP[num_str]

    # OCR fallback: l/I → 1
    if num_str in ("l", "I"):
        return 1

    return None


def _cn_string_to_int(s: str) -> int:
    """Convert Chinese numeral string to integer (e.g. 十二 → 12)."""
    total = 0
    for ch in s:
        if ch in _CN_NUM_MAP:
            total = total * 10 + _CN_NUM_MAP[ch]
        # Skip non-numeral chars
    return total if total > 0 else 1


def _is_false_question_number(num: int, line: str) -> bool:
    """Check if detected number looks like a false positive.

    Similar logic to original question_splitter._is_false_question_number.
    """
    if num == 0:
        return True
    # 6/8 may be OCR errors for B; only reject when line matches option pattern
    if num in (6, 8):
        if _OPTION_LETTER_RE.match(line):
            return True
    # OCR fallback: 6→B, 8→B, 0→D: check if number followed by content
    # that doesn't look like a question (has only option-like text)
    if num in (0, 6, 8):
        _ocr_opt_re = re.compile(r"^[068]\s*[.、:：)）]\s*(.+)")
        m = _ocr_opt_re.match(line)
        if m:
            rest = m.group(1)
            if rest and not _HAS_QUESTION_CHARACTERISTICS_RE.search(rest):
                return True
    return False


# ===================================================================
# Convenience wrappers for specific use cases
# ===================================================================


def has_new_question_number(text: str) -> bool:
    """Check if text starts with a new question number (lightweight).

    Replaces ``cross_page_linking._has_new_question_number()``.
    Uses a lightweight check matching the original simple regex behavior:
    Arabic digits + separator (cross-page use case only).
    """
    if not text:
        return False
    first_line = text.strip().split("\n")[0]
    if re.match(r"\d+\s*[.、)）]", first_line):
        return True
    return False


def is_section_header(text: str) -> bool:
    """Check if text is a section header (not a question)."""
    result = parse_numbering(text)
    if result is None:
        return False
    return result.numbering_type is NumberingType.SECTION


def extract_first_question_label(text: str) -> str | None:
    """Extract the full question number label from the first line.

    Replaces ``question_splitter._extract_first_line_label()``.
    Only returns labels for actual question numbers, not section headers.
    """
    first_line = text.split("\n")[0] if text else ""
    result = parse_numbering(first_line)
    if result is not None and result.numbering_type not in (
        NumberingType.SECTION,
        NumberingType.FALSE_POSITIVE,
        NumberingType.ORDINAL,
        NumberingType.ANSWER,
    ):
        return result.raw.strip()
    return None


# ===================================================================
# Continuity validation
# ===================================================================


def validate_question_sequence(
    numbers: list[int],
    *,
    expected_start: int = 1,
    max_gap: int = 1,
) -> list[dict]:
    """Validate a sequence of question numbers for continuity.

    Args:
        numbers: List of detected question numbers in order.
        expected_start: Expected first question number.
        max_gap: Maximum allowed gap between consecutive numbers.

    Returns:
        List of diagnostics for anomalies found.
    """
    diagnostics: list[dict] = []
    if not numbers:
        return diagnostics

    prev = numbers[0]
    if prev != expected_start:
        diagnostics.append({
            "type": "unexpected_start",
            "expected": expected_start,
            "actual": prev,
        })

    for i in range(1, len(numbers)):
        gap = numbers[i] - numbers[i - 1]
        if gap > max_gap + 1:
            diagnostics.append({
                "type": "jump",
                "from_idx": i - 1,
                "from_num": numbers[i - 1],
                "to_num": numbers[i],
                "gap": gap,
            })
        elif gap <= 0:
            diagnostics.append({
                "type": "duplicate_or_decrease",
                "from_idx": i - 1,
                "from_num": numbers[i - 1],
                "to_num": numbers[i],
            })
        prev = numbers[i]

    return diagnostics
