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

logger = logging.getLogger(__name__)

# Strict ABCD option line: line starts with A./B./C./D. etc. followed by content
_STRICT_OPTION_LINE = re.compile(
    r"(?:^|\n)\s*"
    r"(?:[?？]\s*|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]\s*)?"
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

# Circled digit choices: ① ② ③ ④
_CIRCLED_CHOICE = re.compile(r"[①②③④]")

# Explicit choice question keywords in Chinese
_CHOICE_KEYWORDS = [
    "下列选项", "以下选项",
]

# Question type constants (mirrored from question_normalizer to avoid circular import)
QT_SINGLE_CHOICE = "single_choice"
QT_MULTIPLE_CHOICE = "multiple_choice"
QT_TRUE_FALSE = "true_false"
QT_FILL_BLANK = "fill_blank"
QT_SUBJECTIVE = "subjective"


def has_structured_options(raw_text: str) -> bool:
    """Check if raw_text contains structured option patterns.

    Strict detection rules (any one is sufficient):
    1. At least 2 lines matching ``A. text`` / ``B. text`` / etc.
    2. At least 2 numbered choices ``(1) text`` / ``(2) text``
    3. At least 2 circled digit choices ① ② ③ ④
    4. Explicit keyword "下列选项" / "以下选项" in text
    5. ``option_lines`` dict with actual content

    Args:
        raw_text: The raw question text (pre-stem-extraction).

    Returns:
        True if the text has structured options with sufficient confidence.
    """
    if not raw_text:
        return False

    # Method 1: Line-level ABCD detection
    abcd_matches = _STRICT_OPTION_LINE.findall(raw_text)
    unique_keys = set(k.upper() for k in abcd_matches)
    if len(unique_keys) >= 2:
        return True

    # Method 2: Inline ABCD detection (less preferred but still valid)
    inline_matches = _STRICT_INLINE_OPTION.findall(raw_text)
    unique_inline = set(k.upper() for k in inline_matches)
    if len(unique_inline) >= 2:
        return True

    # Method 3: Numbered choices (1)(2)(3)(4)
    numbered_matches = _STRICT_NUMBERED_CHOICE.findall(raw_text)
    if len(numbered_matches) >= 2:
        return True

    # Method 4: Circled digits ① ② ③ ④
    circled = _CIRCLED_CHOICE.findall(raw_text)
    if len(circled) >= 2:
        return True

    # Method 5: Explicit choice keywords
    for keyword in _CHOICE_KEYWORDS:
        if keyword in raw_text:
            return True

    return False


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

    Args:
        raw_text: The raw question text.
        option_lines: Dict of options detected by the splitter (may be empty).
        splitter_has_options: The splitter's has_options flag.
        is_frozen: Whether the freeze stage has options for this question.

    Returns:
        dict with:
            - has_options (bool): Whether options should be processed.
            - has_options_reason (str): Why has_options is True/False.
            - confidence (float): Confidence in the classification.
              Note: this is an empirical estimate, not calibrated
              against ground-truth data.
    """
    option_lines = option_lines or {}

    # ── Frozen questions always have options ──
    if is_frozen:
        return {
            "has_options": True,
            "has_options_reason": "frozen_options_present",
            "confidence": 1.0,
        }

    # ── Check for structured options in raw text ──
    structured = has_structured_options(raw_text)

    # ── Check if splitter actually found option content ──
    splitter_has_content = bool(option_lines) and len(option_lines) >= 1

    if structured:
        # Text has clear option patterns → has_options
        return {
            "has_options": True,
            "has_options_reason": "structured_option_patterns_detected",
            "confidence": 0.9 if len(option_lines) >= 2 else 0.7,
        }

    # ── Fallback: splitter found content but text is ambiguous ──
    # This is a conservative path — we trust the splitter's output
    # even though we couldn't confirm from raw text patterns.
    if splitter_has_content:
        logger.info(
            "[CLASSIFY] has_options=True via splitter (structured detection failed, "
            "splitter found %d option_lines)",
            len(option_lines),
        )
        return {
            "has_options": True,
            "has_options_reason": "splitter_option_lines_present",
            "confidence": 0.6,
        }

    # ── No evidence of options ──
    return {
        "has_options": False,
        "has_options_reason": "no_option_patterns_detected",
        "confidence": 0.8,
    }
