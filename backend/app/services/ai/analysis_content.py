"""Robust parsing and validation for AI error-analysis content."""

from __future__ import annotations

import ast
import json
import re

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

    if not isinstance(value, dict):
        text = _coerce_analysis_text(value, depth + 1)
        return {"mistake_diagnosis": text, "knowledge_patch": "", "review_task": ""}

    direct = {
        "mistake_diagnosis": _pick_field(value, list(_DIAGNOSIS_KEYS)),
        "knowledge_patch": _pick_field(value, list(_KNOWLEDGE_KEYS)),
        "review_task": _pick_field(value, list(_TASK_KEYS)),
    }

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
    if embedded_best and embedded_score > 0:
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
    value = str(text or "").strip()
    match = re.search(
        r"```(?:json|javascript|js)?\s*([\s\S]*?)\s*```", value, re.IGNORECASE
    )
    if match:
        return match.group(1).strip()
    value = re.sub(r"^```(?:json|javascript|js)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def _looks_like_structured_analysis_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if value[:1] in {"{", "["}:
        return True
    keys = _DIAGNOSIS_KEYS + _KNOWLEDGE_KEYS + _TASK_KEYS
    return any(
        re.search(rf'(["\']){re.escape(key)}\1\s*:', value, re.IGNORECASE)
        for key in keys
    )


def _decode_structured_content(raw: str):
    """Decode JSON/Python-literal model output, including text around the object."""
    original = (raw or "").strip()
    decoder = json.JSONDecoder()

    def decode_candidates(value: str):
        starts = [0]
        starts.extend(i for i, char in enumerate(value) if i > 0 and char in "{[")
        for start in starts:
            candidate = value[start:].lstrip()
            if not candidate:
                continue
            try:
                decoded, _ = decoder.raw_decode(candidate)
                return decoded
            except (json.JSONDecodeError, ValueError):
                pass
            try:
                decoded = ast.literal_eval(candidate)
                if isinstance(decoded, (dict, list, str)):
                    return decoded
            except (SyntaxError, ValueError):
                pass
        return None

    # Parse the original value first so a valid outer JSON object can carry a
    # fenced JSON string in one field without losing its embedded fields.
    decoded = decode_candidates(original)
    if decoded is not None:
        return decoded

    stripped = _strip_code_fence(original)
    if stripped != original:
        return decode_candidates(stripped)
    return None


def _parse_titled_analysis_text(text: str) -> dict:
    stripped = _strip_code_fence(text)
    heading_re = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:\d+[.、)]\s*)?(?:[-*]\s*)?"
        r"(?:\*\*)?\s*(错因诊断|补漏重点|复练任务)\s*(?:\*\*)?\s*[：:]\s*(?:\*\*)?\s*"
    )
    matches = list(heading_re.finditer(stripped))
    if not matches:
        if _looks_like_structured_analysis_text(stripped):
            return dict(_EMPTY_ANALYSIS)
        return {"mistake_diagnosis": stripped, "knowledge_patch": "", "review_task": ""}

    result = dict(_EMPTY_ANALYSIS)
    key_map = {
        "错因诊断": "mistake_diagnosis",
        "补漏重点": "knowledge_patch",
        "复练任务": "review_task",
    }
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(stripped)
        result[key_map[match.group(1)]] = stripped[match.end() : end].strip()
    return result


def parse_error_analysis_content(raw: str) -> dict:
    """Parse standard JSON, fenced JSON, aliases, wrappers, or titled text."""
    text = (raw or "").strip()
    if not text:
        return dict(_EMPTY_ANALYSIS)
    decoded = _decode_structured_content(text)
    return _extract_analysis_fields(decoded if decoded is not None else text)


def _extract_answer_check(value, depth: int = 0) -> dict | None:
    """Find the machine-verifiable ``answer_check`` object in model output."""
    if depth > 6 or value is None:
        return None
    if isinstance(value, str):
        decoded = _decode_structured_content(value)
        if decoded is None or decoded == value:
            return None
        return _extract_answer_check(decoded, depth + 1)
    if isinstance(value, list):
        for item in value:
            found = _extract_answer_check(item, depth + 1)
            if found is not None:
                return found
        return None
    if not isinstance(value, dict):
        return None
    for key in _ANSWER_CHECK_KEYS:
        candidate = value.get(key)
        if isinstance(candidate, dict):
            return candidate
    for key in _ANALYSIS_WRAPPER_KEYS:
        if key in value:
            found = _extract_answer_check(value.get(key), depth + 1)
            if found is not None:
                return found
    for nested in value.values():
        if isinstance(nested, (dict, list, str)):
            found = _extract_answer_check(nested, depth + 1)
            if found is not None:
                return found
    return None


def _canonical_answer_echo(value, expected: str) -> str:
    raw = str(value or "").strip().upper()
    expected = str(expected or "").strip().upper()
    if expected and re.fullmatch(r"[A-Z](?:,[A-Z])*", expected):
        letters = sorted(set(re.findall(r"[A-Z]", raw)))
        return ",".join(letters)
    return raw.replace("，", ",").replace("；", ",").replace("、", ",")


def _canonical_answer_check_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [item for item in re.split(r"[,，、;；\s]+", value) if item]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    result: list[str] = []
    for item in items:
        if isinstance(item, dict):
            item = item.get("label") or item.get("key") or item.get("id") or ""
        text = str(item or "").strip().translate(_ROMAN_ECHO_TRANSLATION).upper()
        if text and text not in result:
            result.append(text)
    return result


def _validate_answer_check(
    raw_content: str, expected: dict
) -> tuple[bool, str, dict | None]:
    decoded = _decode_structured_content(raw_content)
    actual = _extract_answer_check(decoded if decoded is not None else raw_content)
    if actual is None:
        return False, "answer_check_missing", None

    correct_actual = _canonical_answer_echo(
        actual.get("correct_answer", actual.get("correctAnswer", "")),
        str(expected.get("correct_answer") or ""),
    )
    user_actual = _canonical_answer_echo(
        actual.get("user_answer", actual.get("userAnswer", "")),
        str(expected.get("user_answer") or ""),
    )
    correct_expected = _canonical_answer_echo(
        expected.get("correct_answer", ""), str(expected.get("correct_answer") or "")
    )
    user_expected = _canonical_answer_echo(
        expected.get("user_answer", ""), str(expected.get("user_answer") or "")
    )
    if correct_actual != correct_expected:
        return False, "answer_check_correct_mismatch", actual
    if user_actual != user_expected:
        return False, "answer_check_user_mismatch", actual

    missing_actual = _canonical_answer_check_list(
        actual.get("missing", actual.get("missing_items", []))
    )
    extra_actual = _canonical_answer_check_list(
        actual.get("extra", actual.get("extra_items", []))
    )
    missing_expected = _canonical_answer_check_list(expected.get("missing", []))
    extra_expected = _canonical_answer_check_list(expected.get("extra", []))
    if sorted(missing_actual) != sorted(missing_expected):
        return False, "answer_check_missing_mismatch", actual
    if sorted(extra_actual) != sorted(extra_expected):
        return False, "answer_check_extra_mismatch", actual
    return True, "", actual


def is_valid_ai_analysis(content: dict) -> bool:
    return any(
        str(content.get(k, "")).strip()
        for k in ["mistake_diagnosis", "knowledge_patch", "review_task"]
    )


def _normalize_ai_analysis(cached: dict) -> dict:
    """Convert any field-name format to canonical snake_case."""
    return _extract_analysis_fields(cached) if cached else dict(_EMPTY_ANALYSIS)
