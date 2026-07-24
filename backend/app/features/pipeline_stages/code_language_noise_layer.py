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

from app.features.code_integrity import contains_code
from app.features.pipeline_stages.code_language_noise_metrics import (
    NoiseMetrics,
    NoiseMetricsCollector,
    format_metrics_summary,
)
from app.features.pipeline_stages.noise_drift_detector import detect_drift
from app.features.pipeline_stages.noise_rule_governor import (
    evaluate_policy as evaluate_noise_policy,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 1: Code Transition Detection
# ---------------------------------------------------------------------------

# Keywords that signal a transition from natural language into code.
_TRANSITION_PATTERNS = re.compile(
    r"(?:"
    r"在\w+中执行[：:]|"      # 在单链表中执行：/在循环中执行:
    r"在\w+中进行如下\w*[：:]|"  # 在单链表中进行如下操作：
    r"执行如下\w*[：:]|"      # 执行如下操作：/执行如下计算：
    r"执行如下\w*代码|"       # 执行如下Java代码 / 执行如下C代码
    r"进行如下\w*[：:]|"      # 进行如下操作：/进行如下计算：
    r"已知\s+\w+\s*指向|"     # 已知 p 指向某节点/已知指针指向
    r"对\w+执行\w+操作|"      # 对链表执行插入操作/对栈执行删除操作
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
    r"typedef\s|"                      # typedef without # prefix
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
    r"|<\s*\d+\s*>"  # <1> <12> etc (OCR page/order markers)
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

# OCR hallucination in option areas — non-ASCII garbage that looks like code.
# Lines like "S = μxau<-d :μxau<-d = μxau<-s'g" (OCR corruption of a code
# option) contain = and ; so _is_code_keyword_line would mark them as code.
# Checked before the code keyword guard to catch these false positives.
_OCR_HALLUCINATION_RE = re.compile(
    r"^\s*[A-Za-df-z]\s*=\s*\S*[^\x00-\x7f]"
)


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

    # Pre-check: OCR hallucination (non-ASCII garbage in option areas).
    # Must be checked before _is_code_keyword_line since garbage lines contain
    # = and ; characters that would bypass the code keyword guard.
    if _OCR_HALLUCINATION_RE.match(line):
        return ("ocr_hallucination", 0.85)

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
    "ocr_hallucination",
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

def clean_code_language_noise(
    text: str,
    safe_mode: bool = False,
    _collector: NoiseMetricsCollector | None = None,
) -> str:
    """Remove OCR code language identifier noise from ``text``.

    Three-phase pipeline:
        1. Detect transition zones
        2. Classify noise lines within zones
        3. Remove qualifying noise lines

    Args:
        text: Input text (potentially containing code blocks).
        safe_mode: When True, use stricter guards and higher
                   confidence threshold.
        _collector: Optional metrics collector for observability.

    Returns:
        Cleaned text with noise lines removed.
    """
    if not text:
        return text

    lines = text.split("\n")
    zones = detect_transition_zones(text)

    if _collector:
        _collector.record_total_lines(len(lines))
        _collector.record_zones(zones)

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

            if _collector:
                _collector.record_classification(noise_type, confidence)

            if _should_remove(line, noise_type, confidence, safe_mode=safe_mode):
                removed_lines.append(line_num)
                if _collector:
                    _collector.record_removal(line_num, noise_type)
                logger.debug(
                    "Removed noise line %d: type=%s conf=%.2f line=%r",
                    line_num, noise_type, confidence, line,
                )
                continue  # skip this line entirely
            elif noise_type and _collector:
                # Classified as noise but kept by a safety guard
                _collector.record_protected(noise_type)

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

def _scan_stems_for_noise(
    questions: list[dict],
    safe_mode: bool = False,
) -> tuple[list[tuple[int, dict, str, str]], list[NoiseMetrics]]:
    """Scan question stems for code language noise.

    Returns:
        (candidates, metrics_list):
            candidates: (index, question, stem, cleaned_stem) pairs where
                noise was found and removed.
            metrics_list: Per-question NoiseMetrics (same order as questions).
    """
    candidates: list[tuple[int, dict, str, str]] = []
    metrics_list: list[NoiseMetrics] = []

    for i, q in enumerate(questions):
        stem = q.get("stem", "")
        if not stem or not contains_code(stem):
            metrics_list.append(NoiseMetrics(doc_id=str(i)))
            continue

        collector = NoiseMetricsCollector(doc_id=str(i))
        cleaned = clean_code_language_noise(stem, safe_mode=safe_mode, _collector=collector)
        metrics_list.append(collector.metrics)

        if cleaned != stem:
            candidates.append((i, q, stem, cleaned))

    return candidates, metrics_list


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
            "code_language_noise_fix_actions": [],
        }

    safe_mode = opts.get("noise_clean_safe_mode", False)

    candidates, metrics_list = _scan_stems_for_noise(questions, safe_mode=safe_mode)
    if not candidates:
        return {
            "questions": questions,
            "cleaned_count": 0,
            "warnings": [],
            "code_language_noise_fix_actions": [],
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

    # ── v2 metrics observability ──
    metrics_summary = format_metrics_summary(metrics_list) if metrics_list else {}

    # ── v2 drift detection ──
    noise_type_counts = metrics_summary.get("noise_type_distribution", {})
    drift_result = detect_drift(noise_type_counts)

    if drift_result.get("drift_detected"):
        warnings.append(
            f"noise_drift: score={drift_result['drift_score']:.3f}, "
            f"top_change={drift_result['top_changed_noise']}"
        )

    # ── v2 adaptive governance ──
    governor_result = evaluate_noise_policy(
        false_positive_suspected_count=metrics_summary.get("total_false_positive_suspected", 0),
        total_protected_count=metrics_summary.get("total_protected_lines", 0),
        total_removed_count=total_removed_lines,
        current_policy={"safe_mode": safe_mode},
    )

    if governor_result.get("changes"):
        for change in governor_result["changes"]:
            if change != "no_change_needed":
                logger.info("Noise governor: %s", change)
                warnings.append(f"noise_governor: {change}")

    return {
        "questions": questions,
        "cleaned_count": cleaned_count,
        "warnings": warnings,
        "code_language_noise_fix_actions": fix_actions,
        "total_removed_lines": total_removed_lines,
        # v2 observability
        "noise_metrics_summary": metrics_summary,
        "noise_metrics_list": [m.to_dict() for m in metrics_list],
        "noise_drift": drift_result,
        "noise_governor": governor_result,
    }
