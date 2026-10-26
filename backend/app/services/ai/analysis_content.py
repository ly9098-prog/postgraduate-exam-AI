"""Robust parsing and validation for AI error-analysis content."""

from __future__ import annotations

import ast  # noqa: F401 - historical parser patch port
import json  # noqa: F401 - historical parser patch port
import re  # noqa: F401 - historical parser patch port

from app.services.ai import analysis_answer_check as _answer_check
from app.services.ai import analysis_text_syntax as _text_syntax

_ANALYSIS_WRAPPER_KEYS = (
    "content",
    "data",
    "result",
    "analysis",
    "ai_analysis",
    "payload",
)
_ANALYSIS_TEXT_KEYS = ("text", "content", "value", "description")
_DIAGNOSIS_KEYS = (
    "mistake_diagnosis",
    "error_analysis",
    "diagnosis",
    "mistakeDiagnosis",
    "mistakediagnosis",
    "错因诊断",
)
_KNOWLEDGE_KEYS = (
    "knowledge_patch",
    "knowledge_weakness",
    "knowledge",
    "knowledgePatch",
    "knowledgepatch",
    "补漏重点",
)
_TASK_KEYS = (
    "review_task",
    "suggestion",
    "task",
    "reviewTask",
    "reviewtask",
    "reviewask",
    "复练任务",
)
_EMPTY_ANALYSIS = {"mistake_diagnosis": "", "knowledge_patch": "", "review_task": ""}

_ANSWER_CHECK_KEYS = ("answer_check", "answerCheck", "作答核对")
_ROMAN_ECHO_TRANSLATION = str.maketrans(
    {
        "Ⅰ": "I",
        "Ⅱ": "II",
        "Ⅲ": "III",
        "Ⅳ": "IV",
        "Ⅴ": "V",
        "Ⅵ": "VI",
        "Ⅶ": "VII",
        "Ⅷ": "VIII",
        "Ⅸ": "IX",
        "Ⅹ": "X",
    }
)


def _content_port(name: str):
    """Resolve historical globals at use time, including missing-name errors."""
    try:
        return globals()[name]
    except KeyError:
        raise NameError(f"name '{name}' is not defined", name=name) from None


def _pick_field(d: dict, candidates: list[str]) -> str:
    """Return the first non-empty normalized value from candidate keys."""
    for key in candidates:
        if key not in d:
            continue
        val = _coerce_analysis_text(d.get(key))
        if val:
            return val
    return ""


def _coerce_analysis_text(value, depth: int = 0) -> str:
    """Normalize common model field shapes to text."""
    if value is None or depth > 6:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _coerce_analysis_text(item, depth + 1)
            if text and text not in parts:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(value, dict):
        for key in _ANALYSIS_TEXT_KEYS:
            if key in value:
                text = _coerce_analysis_text(value.get(key), depth + 1)
                if text:
                    return text
        if len(value) == 1:
            return _coerce_analysis_text(next(iter(value.values())), depth + 1)
    return ""


def _extract_analysis_fields(value, depth: int = 0) -> dict:
    """Dispatch model shapes while counting only recursive content edges."""
    if depth > 6 or value is None:
        return dict(_EMPTY_ANALYSIS)

    if isinstance(value, str):
        decoded = _decode_structured_content(value)
        if decoded is not None and not (
            isinstance(decoded, str) and decoded.strip() == value.strip()
        ):
            return _extract_analysis_fields(decoded, depth + 1)
        return _parse_titled_analysis_text(value)

    if isinstance(value, list):
        return _extract_analysis_list(value, depth)

    if not isinstance(value, dict):
        text = _coerce_analysis_text(value, depth + 1)
        return {"mistake_diagnosis": text, "knowledge_patch": "", "review_task": ""}
    return _extract_analysis_mapping(value, depth)


def _extract_analysis_list(value: list, depth: int) -> dict:
    """Visit every item, keeping the first candidate with the highest score."""
    best = dict(_EMPTY_ANALYSIS)
    best_score = -1
    for item in value:
        candidate = _extract_analysis_fields(item, depth + 1)
        score = sum(bool(candidate.get(k)) for k in _EMPTY_ANALYSIS)
        if score > best_score:
            best = candidate
            best_score = score
    if best_score > 0:
        return best
    text = _coerce_analysis_text(value, depth + 1)
    return {"mistake_diagnosis": text, "knowledge_patch": "", "review_task": ""}


def _extract_embedded_analysis(value: dict, depth: int) -> dict | None:
    """Rank structured strings inside field aliases before accepting direct text."""
    embedded_best = None
    embedded_score = 0
    for key in _DIAGNOSIS_KEYS + _KNOWLEDGE_KEYS + _TASK_KEYS:
        nested = value.get(key)
        if not isinstance(nested, str) or not _looks_like_structured_analysis_text(
            _strip_code_fence(nested)
        ):
            continue
        decoded = _decode_structured_content(nested)
        if decoded is None or (
            isinstance(decoded, str) and decoded.strip() == nested.strip()
        ):
            continue
        candidate = _extract_analysis_fields(decoded, depth + 1)
        score = sum(bool(candidate.get(k)) for k in _EMPTY_ANALYSIS)
        if score > embedded_score:
            embedded_best = candidate
            embedded_score = score
    return embedded_best


def _extract_analysis_mapping(value: dict, depth: int) -> dict:
    """Resolve direct fields, embedded structures, then ordered nested candidates."""
    direct = {
        "mistake_diagnosis": _pick_field(value, list(_DIAGNOSIS_KEYS)),
        "knowledge_patch": _pick_field(value, list(_KNOWLEDGE_KEYS)),
        "review_task": _pick_field(value, list(_TASK_KEYS)),
    }

    embedded_best = _extract_embedded_analysis(value, depth)
    if embedded_best:
        return embedded_best

    if is_valid_ai_analysis(direct):
        if any(
            _looks_like_structured_analysis_text(text)
            for text in direct.values()
            if text
        ):
            direct = dict(_EMPTY_ANALYSIS)
        else:
            return direct

    # Snapshot all candidates before recursion, including non-wrapper insertion order.
    nested_values = [value[key] for key in _ANALYSIS_WRAPPER_KEYS if key in value]
    nested_values.extend(
        v
        for k, v in value.items()
        if k not in _ANALYSIS_WRAPPER_KEYS and isinstance(v, (dict, list, str))
    )
    best = direct
    best_score = 0
    for nested in nested_values:
        candidate = _extract_analysis_fields(nested, depth + 1)
        score = sum(bool(candidate.get(k)) for k in _EMPTY_ANALYSIS)
        if score > best_score:
            best = candidate
            best_score = score
            if score == 3:
                break
    return best


def _strip_code_fence(text: str) -> str:
    """Strip complete or truncated Markdown code fences from model output."""
    return _text_syntax.strip_code_fence(text, ports=_content_port)


def _looks_like_structured_analysis_text(text: str) -> bool:
    return _text_syntax.looks_like_structured_analysis_text(text, ports=_content_port)


def _decode_structured_content(raw: str):
    """Decode JSON/Python-literal model output, including text around the object."""
    return _text_syntax.decode_structured_content(raw, ports=_content_port)


def _parse_titled_analysis_text(text: str) -> dict:
    return _text_syntax.parse_titled_analysis_text(text, ports=_content_port)


def parse_error_analysis_content(raw: str) -> dict:
    """Parse standard JSON, fenced JSON, aliases, wrappers, or titled text."""
    text = (raw or "").strip()
    if not text:
        return dict(_EMPTY_ANALYSIS)
    decoded = _decode_structured_content(text)
    return _extract_analysis_fields(decoded if decoded is not None else text)


def _extract_answer_check(value, depth: int = 0) -> dict | None:
    """Find the machine-verifiable ``answer_check`` object in model output."""
    return _answer_check.extract_answer_check(value, depth, ports=_content_port)


def _canonical_answer_echo(value, expected: str) -> str:
    return _answer_check.canonical_answer_echo(value, expected, ports=_content_port)


def _canonical_answer_check_list(value) -> list[str]:
    return _answer_check.canonical_answer_check_list(value, ports=_content_port)


def _validate_answer_check(
    raw_content: str, expected: dict
) -> tuple[bool, str, dict | None]:
    return _answer_check.validate_answer_check(
        raw_content, expected, ports=_content_port
    )


def is_valid_ai_analysis(content: dict) -> bool:
    return any(
        str(content.get(k, "")).strip()
        for k in ["mistake_diagnosis", "knowledge_patch", "review_task"]
    )


def _normalize_ai_analysis(cached: dict) -> dict:
    """Convert any field-name format to canonical snake_case."""
    return _extract_analysis_fields(cached) if cached else dict(_EMPTY_ANALYSIS)
