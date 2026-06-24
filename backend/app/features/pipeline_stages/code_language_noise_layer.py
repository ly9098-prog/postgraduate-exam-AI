"""Code Language Noise Aware Cleaning Layer — OCR code language identifier noise removal.

Sits between ``normalize_schema`` and ``code_structure_reconstruct``. Removes
OCR-generated language identifier noise (e.g. ``(1>``, ``(>C``, ``C>``) that
appears at the transition from natural-language descriptions into code blocks.

Three phases:
    1. Code Transition Detection — find TRANSITION_ZONE boundaries
    2. Language Noise Classification — classify noise tokens within the zone
    3. Safe Removal Policy — delete only qualifying noise, never real code

Design principles:
    - Rule-based, no LLM dependency
    - Operates at line level, not character level
    - Context-aware: only removes within detected transition zone
    - Built-in protection for real code constructs
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 1: Code Transition Detection
# ---------------------------------------------------------------------------

# Keywords that signal a transition from natural language into code.
_TRANSITION_PATTERNS = re.compile(
    r"(?:"
    r"执行如下\w*代码|"       # 执行如下Java代码 / 执行如下C代码
    r"下列\w*程序|"           # 下列C程序 / 下列Java程序
    r"代码如下|"
    r"如下\w*代码|"           # 如下Java代码 / 如下HTML代码
    r"以下\w*程序|"           # 以下C程序 / 以下Java程序
    r"以下\w*代码|"           # 以下C代码 / 以下HTML代码
    r"程序如下|"
    r"阅读以下\w*程序|"       # 阅读以下C程序 / 阅读以下Java程序
    r"阅读以下\w*代码|"       # 阅读以下HTML代码
    r"阅读下列\w*程序|"       # 阅读下列C程序 / 阅读下列Java程序
    r"C语言程序|"
    r"C\+\+程序|"
    r"C\+\+代码|"
    r"代码段|"
    r"程序段|"
    r"源程序|"
    r"程序代码|"
    r"编写如下|"
    r"编程如下"
    r")",
    re.IGNORECASE,
)

# Lines that immediately precede code (opening braces, function signatures).
# Note: overlaps intentionally with _ABSOLUTE_KEEP_RE (both cover preprocessor
# directives). _CODE_PRECURSOR_PATTERNS detects transition-zone *boundaries*;
# _ABSOLUTE_KEEP_RE is the last-chance *safety guard* that prevents deletion.
_CODE_PRECURSOR_PATTERNS = re.compile(
    r"^\s*(?:"
    r"#\s*(?:include|define|pragma|import|typedef)|"  # preprocessor
    r"using\s+(?:namespace|System)|"  # C# / C++ using
    r"public|private|protected|static|class|struct|void|int\s+\w+\s*\(|"  # declarations
    r"int\s+main|"
    r"for\s*\(|while\s*\(|if\s*\(|switch\s*\(|"
    r"\{"
    r")",
)

_MAX_TRANSITION_LINES = 3  # scan at most N lines after transition signal


def detect_transition_zones(text: str) -> list[tuple[int, int]]:
    """Find TRANSITION_ZONE line ranges in ``text``.

    A transition zone is a span of up to ``_MAX_TRANSITION_LINES`` lines
    starting from a line that matches a code-transition keyword or a code
    precursor pattern.

    Returns:
        list of (start_line, end_line) 1-based tuples.
    """
    lines = text.split("\n")
    zones: list[tuple[int, int]] = []

    for i, line in enumerate(lines):
        line_num = i + 1  # 1-based
        is_transition = bool(_TRANSITION_PATTERNS.search(line))
        is_precursor = bool(_CODE_PRECURSOR_PATTERNS.match(line))

        if is_transition or is_precursor:
            start = line_num
            end = min(line_num + _MAX_TRANSITION_LINES, len(lines))
            zones.append((start, end))

    # Merge overlapping/adjacent zones
    if not zones:
        return []
    merged = [zones[0]]
    for zone in zones[1:]:
        last = merged[-1]
        if zone[0] <= last[1] + 1:  # adjacent or overlapping
            merged[-1] = (last[0], max(last[1], zone[1]))
        else:
            merged.append(zone)
    return merged


# ---------------------------------------------------------------------------
# Phase 2: Language Noise Classification
# ---------------------------------------------------------------------------

# C / C++ noise patterns (high priority)
_C_CPP_NOISE_RE = re.compile(
    r"^\s*(?:"
    r"\(1\s*>\s*"  # (1>
    r"|\(>\s*C\s*"  # (>C
    r"|C\s*>\s*"  # C>
    r"|（1\s*>\s*"  # （1> (fullwidth paren)
    r"|（>\s*C\s*"  # （>C
    r"|\(\s*>\s*"  # (> standalone
    r"|（\s*>\s*"  # （> standalone
    r")\s*$",
)

# Python interactive noise
_PYTHON_NOISE_RE = re.compile(r"^\s*>{3,}\s*(?:python|py)?\s*$")

# Markup / tag noise — only obviously-malformed tags that cannot be valid HTML.
# Never match valid HTML tags (<html>, <body>, <div>, etc.) since they appear
# in real code and must be preserved.
_TAG_NOISE_RE = re.compile(r"^\s*</?[^a-zA-Z\d]+>\s*$")

# Language label noise (e.g. "java:", "node:", "c++:")
_LANG_LABEL_RE = re.compile(
    r"^\s*(?:"
    r"(?:c|c\+\+|java|python|node|js|ts|go|rust|ruby|php|swift|kotlin|sql|bash|sh)\s*[：:]"
    r")\s*$",
    re.IGNORECASE,
)

# Generic OCR noise (isolated brackets/angle brackets)
_GENERIC_OCR_NOISE_RE = re.compile(r"^\s*[（(\)）]+\s*$")
_GENERIC_ANGLE_NOISE_RE = re.compile(r"^\s*[<>]+\s*$")


def _is_code_keyword_line(line: str) -> bool:
    """Check if a line contains keywords that mark it as real code."""
    stripped = line.strip()
    if not stripped:
        return False
    # Check for common code keywords and constructs
    if re.search(r"\b(for|if|while|switch|case|return|break|continue|else|do)\b\s*", stripped):
        return True
    if "{" in stripped or "}" in stripped:
        return True
    if ";" in stripped:
        return True
    if re.search(r"\b(int|float|double|char|void|bool|string|var|let|const|def|function)\b", stripped):
        return True
    if re.search(r"[!=]=|->|\+=|-=|\*=|/=|%=|&=|\|=", stripped):
        return True
    if re.match(r"^\s*\w+\s*=", stripped):  # assignment
        return True
    # High operator/symbol density → real code (3+ of =+-*/%&|^~)
    # Exclude < and > since they appear in prompt markers (>>>) and comparisons.
    operator_count = sum(1 for ch in stripped if ch in "=+-*/%&|^~")
    if operator_count >= 3:
        return True
    return False


def classify_noise(line: str) -> tuple[str, float]:
    """Classify a single line as noise or clean.

    Returns:
        (noise_type, confidence) tuple:
            noise_type: ``"c_cpp_noise"``, ``"python_noise"``, ``"tag_noise"``,
                       ``"lang_label"``, ``"generic_ocr_noise"``, or ``""`` (clean).
            confidence: 0.0–1.0
    """
    stripped = line.strip()
    if not stripped:
        return ("", 0.0)

    # Real code guard: if the line looks like valid code, never classify as noise
    if _is_code_keyword_line(line):
        return ("", 0.0)

    if _C_CPP_NOISE_RE.match(line):
        return ("c_cpp_noise", 0.95)
    if _PYTHON_NOISE_RE.match(line):
        return ("python_noise", 0.90)
    if _TAG_NOISE_RE.match(line):
        return ("tag_noise", 0.85)
    if _LANG_LABEL_RE.match(line):
        return ("lang_label", 0.80)
    if _GENERIC_OCR_NOISE_RE.match(line):
        return ("generic_ocr_noise", 0.70)
    if _GENERIC_ANGLE_NOISE_RE.match(line):
        return ("generic_ocr_noise", 0.60)

    return ("", 0.0)


# ---------------------------------------------------------------------------
# Phase 3: Safe Removal Policy
# ---------------------------------------------------------------------------

# Noise types eligible for removal.
_REMOVABLE_NOISE = frozenset({
    "c_cpp_noise",
    "python_noise",
    "tag_noise",
    "lang_label",
    "generic_ocr_noise",
})

# Minimum confidence threshold for removal.
_CONFIDENCE_THRESHOLD = 0.6

# Safe-mode confidence threshold (more conservative).
_SAFE_MODE_CONFIDENCE_THRESHOLD = 0.9

# Additional guard: lines matching these patterns are ALWAYS kept.
_ABSOLUTE_KEEP_RE = re.compile(
    r"^\s*(?:"
    r"\w+\s*\(.*\)\s*\{?"  # function call
    r"|#\s*\w+"  # preprocessor
    r"|//|/\*|\*"  # comments
    r"|import\s|from\s|package\s"  # module imports
    r")\s*",
)

# Lines mentioning "C++" in prose context — never noise.
_CXX_PROSE_RE = re.compile(r"C\+\+", re.IGNORECASE)


def _should_remove(
    line: str,
    noise_type: str,
    confidence: float,
    safe_mode: bool = False,
) -> bool:
    """Determine whether a noise-classified line should be removed.

    Applies absolute-kill guards before allowing removal.

    Args:
        line: The line to evaluate.
        noise_type: Classified noise type (empty string = clean).
        confidence: Classifier confidence (0.0–1.0).
        safe_mode: When True, use higher confidence threshold
                   and stricter guards.
    """
    if noise_type not in _REMOVABLE_NOISE:
        return False

    # Safe mode: only remove high-confidence noise
    threshold = _SAFE_MODE_CONFIDENCE_THRESHOLD if safe_mode else _CONFIDENCE_THRESHOLD
    if confidence < threshold:
        return False

    # C++ prose guard: lines containing "C++" in prose are never noise
    if _CXX_PROSE_RE.search(line):
        return False

    # Absolute keep: never remove lines matching these patterns
    if _ABSOLUTE_KEEP_RE.match(line):
        return False

    # Re-check code keyword guard (belt-and-suspenders)
    if _is_code_keyword_line(line):
        return False

    return True


# ---------------------------------------------------------------------------
# Main cleaning function
# ---------------------------------------------------------------------------

def clean_code_language_noise(text: str, safe_mode: bool = False) -> str:
    """Remove OCR code language identifier noise from ``text``.

    Three-phase pipeline:
        1. Detect transition zones
        2. Classify noise lines within zones
        3. Remove qualifying noise lines

    Args:
        text: Input text (potentially containing code blocks).
        safe_mode: When True, use stricter guards and higher
                   confidence threshold.

    Returns:
        Cleaned text with noise lines removed.
    """
    if not text:
        return text

    lines = text.split("\n")
    zones = detect_transition_zones(text)

    # Build a set of line numbers (1-based) that are in transition zones
    zone_lines: set[int] = set()
    for start, end in zones:
        for ln in range(start, end + 1):
            zone_lines.add(ln)

    removed_lines: list[int] = []
    result_lines: list[str] = []

    for i, line in enumerate(lines):
        line_num = i + 1

        # Only evaluate lines inside transition zones
        if line_num in zone_lines:
            noise_type, confidence = classify_noise(line)
            if _should_remove(line, noise_type, confidence, safe_mode=safe_mode):
                removed_lines.append(line_num)
                logger.debug(
                    "Removed noise line %d: type=%s conf=%.2f line=%r",
                    line_num, noise_type, confidence, line,
                )
                continue  # skip this line entirely

        result_lines.append(line)

    if removed_lines:
        logger.info(
            "Code language noise clean: removed %d line(s) across %d zone(s): %s",
            len(removed_lines), len(zones), removed_lines,
        )

    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Clean questions (pipeline stage entry)
# ---------------------------------------------------------------------------

def _scan_stems_for_noise(questions: list[dict],
                          safe_mode: bool = False,
                          ) -> list[tuple[int, dict, str, str]]:
    """Return (index, question, stem, cleaned_stem) pairs where noise was found.

    Only processes questions that contain code (detected via ``contains_code``).
    """
    from app.features.code_integrity import contains_code

    candidates: list[tuple[int, dict, str, str]] = []
    for i, q in enumerate(questions):
        stem = q.get("stem", "")
        if not stem:
            continue
        if not contains_code(stem):
            continue

        cleaned = clean_code_language_noise(stem, safe_mode=safe_mode)
        if cleaned != stem:
            candidates.append((i, q, stem, cleaned))

    return candidates


def run_code_language_noise_clean_stage(
    questions: list[dict],
    options: dict | None = None,
    **kwargs: Any,
) -> dict:
    """Pipeline stage: clean code language identifier noise from question stems.

    Designed to sit between ``normalize_schema`` and ``code_structure_reconstruct``.
    Lightweight rule-based cleanup — no LLM calls, no AI.

    Args:
        questions: Questions from normalize_schema stage.
        options: Pipeline options dict.

    Returns:
        dict with ``questions``, ``cleaned_count``, ``warnings``, ``fix_actions``.
    """
    opts = options or {}
    if not opts.get("enable_code_language_noise_clean", True) or not questions:
        return {
            "questions": questions,
            "cleaned_count": 0,
            "warnings": [],
            "fix_actions": [],
        }

    safe_mode = opts.get("noise_clean_safe_mode", False)

    candidates = _scan_stems_for_noise(questions, safe_mode=safe_mode)
    if not candidates:
        return {
            "questions": questions,
            "cleaned_count": 0,
            "warnings": [],
            "fix_actions": [],
        }

    cleaned_count = 0
    fix_actions: list[dict] = []
    total_removed_lines = 0

    for idx, q, stem_before, stem_after in candidates:
        q["stem"] = stem_after

        # Count removed lines
        before_lines = stem_before.split("\n")
        after_lines = stem_after.split("\n")
        removed = len(before_lines) - len(after_lines)
        total_removed_lines += removed

        # Add decision trace
        dt = list(q.get("decision_trace") or [])
        dt.append({
            "stage": "code_language_noise_clean",
            "result": "cleaned",
            "reason": f"removed_{removed}_noise_lines",
        })
        q["decision_trace"] = dt

        cleaned_count += 1
        fix_actions.append({
            "question_index": idx,
            "success": True,
            "removed_lines": removed,
        })

        logger.info(
            "Code language noise clean: q%s removed %d noise line(s)",
            q.get("number", idx), removed,
        )

    warnings: list[str] = []
    if cleaned_count:
        warnings.append(
            f"code_language_noise: cleaned {cleaned_count} question(s), "
            f"removed {total_removed_lines} line(s)"
        )

    return {
        "questions": questions,
        "cleaned_count": cleaned_count,
        "warnings": warnings,
        "code_language_noise_fix_actions": fix_actions,
        "total_removed_lines": total_removed_lines,
    }
