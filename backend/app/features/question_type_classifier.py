"""Layer 1: Question Type Classifier — Strict has_options gatekeeper.

Determines whether a question has structured options based on strict
rule-based detection only. No AI, no heuristics, no fallback.

If ``has_options`` is False, the entire option pipeline is skipped:
- options are set to empty
- no option normalization occurs
- ``frozen_options_restored`` is False

This module is the SINGLE authoritative decision point for option detection.
Downstream stages (normalizer, repair) must respect its output.
"""

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

# Circled digit characters (used by multiple patterns)
_CIRCLED_CHARS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_CIRCLED_MAP = {"①": "A", "②": "B", "③": "C", "④": "D"}

# Strict ABCD option line: line starts with A./B./C./D. etc. followed by content
_STRICT_OPTION_LINE = re.compile(
    r"(?:^|\n)\s*"
    r"(?:[?？]\s*|[" + _CIRCLED_CHARS + r"]\s*)?"
    r"([A-Da-d])\s*[.．、:：)）]\s*\S"
)

# Inline ABCD pattern (not at line start, but clearly option-like)
_STRICT_INLINE_OPTION = re.compile(
    r"(?<!\w)([A-Da-d])\s*[.．、:：)）]\s*\S"
)

# Numbered choice pattern: (1) text  (2) text  etc.
_STRICT_NUMBERED_CHOICE = re.compile(
    r"(?:^|\n)\s*[（(]\s*[1-4]\s*[）)]\s*\S"
)

# Circled digit choices: ① ② ③ ④ (only mapped entries, others are not option markers)
_CIRCLED_CHOICE = re.compile(r"[①②③④]")

# Explicit choice question keywords in Chinese
_CHOICE_KEYWORDS = [
    "下列选项", "以下选项",
]

# Fragmented OCR option pattern: handles OCR artifacts like "A ." / "A．\nxxx"
_STRICT_FRAGMENTED_OPTION = re.compile(
    r"(?:^|\n)\s*"
    r"([A-Da-d])\s*[.\s、:：)）]{2,}\s*"
    r"(?:\n\s*)?"
    r"\S"
)

# Broad option-like pattern: "Atext" or "A text" without delimiter (fragmented OCR)
_STRICT_BROAD_OPTION = re.compile(
    r"(?:^|\n)\s*"
    r"([A-Da-d])\s+(?=[^\sa-dA-D\n])"
)

# Question type constants (from unified definition)
from app.features.question_type import (
    QT_SINGLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_TRUE_FALSE,
    QT_FILL_BLANK,
    QT_SUBJECTIVE,
)


@lru_cache(maxsize=128)
def detect_options_from_text(raw_text: str) -> bool:
    """独立检测文本中是否存在选项结构（独立于 question_type）。

    即使 question_type=subjective，只要文本包含选项格式，就返回 True。

    检测范围：
    - A./B./C./D. 行首格式
    - (A)(B)(C)(D) 括号格式
    - ①②③④ 圈号格式
    - 断裂 OCR：A . xxx / A．\\nxxx
    - 宽格式：A  xxx（无点号但字母后跟空格+内容）
    - 代码块相邻：代码行后的 A. xxx 不会被阻断

    此函数是纯规则检测，不依赖 AI、不依赖 question_type，
    不依赖 upstream 的 has_options 标志。
    """
    if not raw_text:
        return False

    # 方法 1: 标准行首选项 A. xxx \\n B. xxx
    abcd_matches = _STRICT_OPTION_LINE.findall(raw_text)
    unique_keys = set(k.upper() for k in abcd_matches)
    if len(unique_keys) >= 2:
        return True

    # 方法 2: 行内选项 A.xxx B.xxx
    inline_matches = _STRICT_INLINE_OPTION.findall(raw_text)
    unique_inline = set(k.upper() for k in inline_matches)
    if len(unique_inline) >= 2:
        return True

    # 方法 3: 编号选项 (1)(2)(3)(4)
    numbered_matches = _STRICT_NUMBERED_CHOICE.findall(raw_text)
    if len(numbered_matches) >= 2:
        return True

    # 方法 4: 圈号选项 ①②③④
    circled = _CIRCLED_CHOICE.findall(raw_text)
    if len(circled) >= 2:
        return True

    # 方法 5: 显式关键词
    for keyword in _CHOICE_KEYWORDS:
        if keyword in raw_text:
            return True

    # 方法 6: 断裂 OCR — "A  ." / "A．" + 换行 + 内容
    frag_matches = _STRICT_FRAGMENTED_OPTION.findall(raw_text)
    unique_frag = set(k.upper() for k in frag_matches)
    if len(unique_frag) >= 2:
        return True

    # 方法 7: 宽格式 — "A xxx"（字母 + 空格 + 非字母内容）
    broad_matches = _STRICT_BROAD_OPTION.findall(raw_text)
    unique_broad = set(k.upper() for k in broad_matches)
    if len(unique_broad) >= 2:
        return True

    return False


def force_options_probe(raw_text: str) -> dict:
    """Debug‑only: brute‑force scan ALL known option patterns and report why
    detection passed or failed.

    Independent of ``classify()`` / ``detect_options_from_text()`` — runs
    every pattern directly and returns detailed diagnostics so you can
    pinpoint exactly which gate is blocking option detection at runtime.

    Returns:
        dict with:
        - ``detected`` (bool): whether any pattern found ≥2 unique keys
        - ``patterns`` (dict): per‑pattern match results
        - ``extracted`` (dict): result of ``extract_options_from_text()``
        - ``summary`` (str): human‑readable explanation
    """
    if not raw_text:
        return {"detected": False, "patterns": {}, "extracted": {}, "summary": "empty_text"}

    patterns: dict[str, dict] = {}

    # Pattern 1: strict line‑start A./B./C./D.
    abcd_matches = _STRICT_OPTION_LINE.findall(raw_text)
    abcd_keys = set(k.upper() for k in abcd_matches)
    patterns["strict_line_abcd"] = {
        "matched": len(abcd_keys) >= 2,
        "unique_keys": sorted(abcd_keys),
        "match_count": len(abcd_matches),
        "detail": f"{chr(10).join(abcd_matches)}" if abcd_matches else "",
    }

    # Pattern 2: inline A.xxx B.xxx
    inline_matches = _STRICT_INLINE_OPTION.findall(raw_text)
    inline_keys = set(k.upper() for k in inline_matches)
    patterns["inline_abcd"] = {
        "matched": len(inline_keys) >= 2,
        "unique_keys": sorted(inline_keys),
        "match_count": len(inline_matches),
    }

    # Pattern 3: numbered (1)(2)(3)(4)
    numbered_matches = _STRICT_NUMBERED_CHOICE.findall(raw_text)
    patterns["numbered_choice"] = {
        "matched": len(numbered_matches) >= 2,
        "match_count": len(numbered_matches),
    }

    # Pattern 4: circled ①②③④
    circled_matches = _CIRCLED_CHOICE.findall(raw_text)
    patterns["circled"] = {
        "matched": len(circled_matches) >= 2,
        "match_count": len(circled_matches),
        "unique_keys": sorted(set(circled_matches)),
    }

    # Pattern 5: keywords
    keyword_matches = [kw for kw in _CHOICE_KEYWORDS if kw in raw_text]
    patterns["choice_keywords"] = {
        "matched": len(keyword_matches) > 0,
        "keywords_found": keyword_matches,
    }

    # Pattern 6: fragmented OCR
    frag_matches = _STRICT_FRAGMENTED_OPTION.findall(raw_text)
    frag_keys = set(k.upper() for k in frag_matches)
    patterns["fragmented_ocr"] = {
        "matched": len(frag_keys) >= 2,
        "unique_keys": sorted(frag_keys),
        "match_count": len(frag_matches),
    }

    # Pattern 7: broad format "A  xxx"
    broad_matches = _STRICT_BROAD_OPTION.findall(raw_text)
    broad_keys = set(k.upper() for k in broad_matches)
    patterns["broad_format"] = {
        "matched": len(broad_keys) >= 2,
        "unique_keys": sorted(broad_keys),
        "match_count": len(broad_matches),
    }

    # Overall detection
    any_pattern_matched = any(p["matched"] for p in patterns.values())
    total_unique_keys: set[str] = set()
    total_unique_keys.update(abcd_keys, inline_keys, frag_keys, broad_keys)

    # Extraction probe
    extracted = extract_options_from_text(raw_text)

    # Build summary
    matched_patterns = [k for k, v in patterns.items() if v["matched"]]
    failed_patterns = [k for k, v in patterns.items() if not v["matched"]]
    summary_parts: list[str] = []
    if any_pattern_matched:
        summary_parts.append(f"matched:{','.join(matched_patterns)}")
    else:
        summary_parts.append("ALL_PATTERNS_FAILED")
    if failed_patterns:
        summary_parts.append(f"failed:{','.join(failed_patterns)}")
    summary_parts.append(f"unique_ABCD_keys={sorted(total_unique_keys)}")
    summary_parts.append(f"extracted_count={len(extracted)}")
    summary_parts.append(f"extracted_keys={sorted(extracted.keys()) if extracted else 'none'}")

    return {
        "detected": any_pattern_matched,
        "extract_ok": len(extracted) >= 2,
        "patterns": patterns,
        "extracted": extracted,
        "total_unique_abcd_keys": sorted(total_unique_keys),
        "summary": " | ".join(summary_parts),
        "raw_text_preview": raw_text[:200],
        "raw_text_len": len(raw_text),
    }


def has_structured_options(raw_text: str) -> bool:
    """Check if raw_text contains structured option patterns.

    Delegates to ``detect_options_from_text`` for all detection logic.
    """
    return detect_options_from_text(raw_text)


# ── Option extraction patterns (single SSOT for all fallback extraction) ──
# These capture the text after the option marker, unlike the boolean detection
# patterns above which only verify the marker's existence.
# Supports: A. / B) / C． / ①. / A  xxx（宽格式/断裂OCR）
_EXTRACT_OPTION_LINE = re.compile(
    r"^\s*(?:[?？]\s*|[" + _CIRCLED_CHARS + r"]\s*)?"
    r"([A-Da-d])\s*[.．、:：)）\s]\s*(.+)"
)
_EXTRACT_CIRCLED_LINE = re.compile(
    r"^\s*([" + _CIRCLED_CHARS + r"])\s*[.．、:：\s]\s*(.+)"
)
_EXTRACT_INLINE_OPTIONS = re.compile(
    r"(?<![A-Za-z])([A-Da-d])\s*[.．、:：)）]\s*"
    r"([^A-Da-d\n]+?)"
    r"(?=\s*[A-Da-d]\s*[.．、:：)）]|\s*$)"
)
_EXTRACT_BROAD_OPTION = re.compile(
    r"(?:^|\n)\s*([A-Da-d])\s{2,}([^\n]+)"
)


def extract_options_from_text(raw_text: str) -> dict[str, str]:
    """从 raw_text 中直接提取选项（key→text），作为 fallback 唯一入口。

    这是 pipeline 中**唯一**的选项提取回退函数。
    - splitter 的宽模式回退委托到此函数
    - normalizer 的 fallback 委托到此函数
    - 任何新 fallback 必须调用此函数

    返回 {key: text} 字典。返回空字典表示未提取到有效选项。
    当 detect_options_from_text(raw_text)==True 但此函数返回空时，
    表示提取层有 bug（应触发 enforce 告警）。
    """
    if not raw_text:
        return {}

    options: dict[str, str] = {}

    # Method 1: 逐行提取 A. xxx / B. xxx 等
    for line in raw_text.split("\n"):
        m = _EXTRACT_OPTION_LINE.match(line.strip())
        if m:
            key = m.group(1).upper()
            text = m.group(2).strip()
            if key in {"A", "B", "C", "D"} and text and key not in options:
                options[key] = text

    # 逐行找到 2+ 选项即返回（行级匹配最可靠）
    if len(options) >= 2:
        return options

    # Method 2: 逐行提取圈号选项 ①. xxx / ②. xxx
    for line in raw_text.split("\n"):
        m = _EXTRACT_CIRCLED_LINE.match(line.strip())
        if m:
            raw_key = m.group(1)
            mapped = _CIRCLED_MAP.get(raw_key)
            if mapped:
                text = m.group(2).strip()
                if text and mapped not in options:
                    options[mapped] = text

    if len(options) >= 2:
        return options

    # Method 3: 逐行宽格式提取 "A  xxx"（字母 + 多空格 + 内容）
    broad_matches = list(_EXTRACT_BROAD_OPTION.finditer(raw_text))
    if len(broad_matches) >= 2:
        options.clear()
        for m in broad_matches:
            key = m.group(1).upper()
            text = m.group(2).strip()
            if key in {"A", "B", "C", "D"} and text and key not in options:
                options[key] = text
        if len(options) >= 2:
            return options

    # Method 4: 行内提取 "A.xxx B.xxx C.xxx D.xxx"（同一行串联）
    inline_matches = list(_EXTRACT_INLINE_OPTIONS.finditer(raw_text))
    if len(inline_matches) >= 2:
        options.clear()
        for m in inline_matches:
            key = m.group(1).upper()
            text = m.group(2).strip()
            if key in {"A", "B", "C", "D"} and text and key not in options:
                options[key] = text
        if len(options) >= 2:
            return options

    return {}


def classify(
    raw_text: str,
    option_lines: dict | None = None,
    splitter_has_options: bool = False,
    is_frozen: bool = False,
) -> dict:
    """Classify question type and determine if options should be processed.

    This is the SINGLE authoritative gate for the option pipeline.
    If ``has_options`` is False, no downstream stage should create or
    modify options.

    Priority order (first match wins):
    1. ``is_frozen`` → has_options=True
    2. ``detect_options_from_text(raw_text)`` → has_options=True, type=single_choice
    3. Splitter found option content → has_options=True (conservative)
    4. Default → has_options=False

    Args:
        raw_text: The raw question text.
        option_lines: Dict of options detected by the splitter (may be empty).
        splitter_has_options: The splitter's has_options flag.
        is_frozen: Whether the freeze stage has options for this question.

    Returns:
        dict with:
            - has_options (bool): Whether options should be processed.
            - has_options_reason (str): Why has_options is True/False.
            - question_type (str | None): Override question_type when detected.
              Only set when options are detected via text patterns.
            - confidence (float): Confidence in the classification.
              Note: this is an empirical estimate, not calibrated
              against ground-truth data.
    """
    option_lines = option_lines or {}

    # ── Priority 1: Frozen questions always have options ──
    if is_frozen:
        logger.info(
            "[TRACE] stage=classify_decision is_frozen=True → has_options=True "
            "raw_text_len=%d option_lines=%s",
            len(raw_text), sorted(option_lines.keys()) if option_lines else "none",
        )
        return {
            "has_options": True,
            "has_options_reason": "frozen_options_present",
            "confidence": 1.0,
        }

    # ── Priority 2: Independent text-based option detection ──
    # This check is INDEPENDENT of question_type, splitter result, or any
    # upstream classification. If the raw text contains A/B/C/D patterns,
    # we force has_options=True regardless of other signals.
    text_has_options = detect_options_from_text(raw_text)
    logger.info(
        "[TRACE] stage=classify_text_detect "
        "detect_options_from_text=%s splitter_has_options=%s "
        "splitter_option_lines=%s raw_text_len=%d",
        text_has_options, splitter_has_options,
        sorted(option_lines.keys()) if option_lines else "none",
        len(raw_text),
    )

    if text_has_options:
        # ── Check if splitter actually found option content ──
        splitter_has_content = bool(option_lines) and len(option_lines) >= 1
        logger.info(
            "[TRACE] stage=classify_decision priority=2 "
            "detect_options_from_text=True → has_options=True "
            "splitter_has_content=%s",
            splitter_has_content,
        )
        return {
            "has_options": True,
            "has_options_reason": "structured_option_patterns_detected",
            "question_type": QT_SINGLE_CHOICE,
            "confidence": 0.9 if splitter_has_content else 0.7,
        }

    # ── Priority 3: Fallback — splitter found content but text is ambiguous ──
    # This is a conservative path — we trust the splitter's output
    # even though we couldn't confirm from raw text patterns.
    splitter_has_content = bool(option_lines) and len(option_lines) >= 1
    if splitter_has_content:
        logger.info(
            "[TRACE] stage=classify_decision priority=3 "
            "detect_options_from_text=False but splitter_has_content=%s "
            "→ has_options=True (option_lines=%s)",
            splitter_has_content, sorted(option_lines.keys()),
        )
        return {
            "has_options": True,
            "has_options_reason": "splitter_option_lines_present",
            "confidence": 0.6,
        }

    # ── No evidence of options ──
    logger.info(
        "[TRACE] stage=classify_decision priority=4 "
        "detect_options_from_text=False splitter_has_options=%s "
        "option_lines=%s → has_options=False",
        splitter_has_options, sorted(option_lines.keys()) if option_lines else "none",
    )
    return {
        "has_options": False,
        "has_options_reason": "no_option_patterns_detected",
        "confidence": 0.8,
    }
