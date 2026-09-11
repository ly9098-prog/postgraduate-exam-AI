"""Normalize wrong-question analysis for export output.

The mini-program wrong-detail page accepts several historical AI-analysis shapes
and renders them as three human-readable cards.  Export files must apply the
same preference and normalization rules instead of printing JSON payloads.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

_MAX_DEPTH = 6
_WRAPPER_KEYS = ("content", "data", "result", "analysis", "ai_analysis", "payload")
_TEXT_KEYS = ("text", "content", "value", "description")
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
_LABELS = (
    ("mistake_diagnosis", "错因诊断"),
    ("knowledge_patch", "补漏重点"),
    ("review_task", "复练任务"),
)
_EMPTY = {"mistake_diagnosis": "", "knowledge_patch": "", "review_task": ""}
_INVALID_LITERAL_RE = re.compile(
    r"^(?:null|true|false|undefined|\[\]|\{\}|-?\d+(?:\.\d+)?)$", re.IGNORECASE
)
_PREFIX_RE = {
    "mistake_diagnosis": re.compile(r"^\s*错因诊断[：:]\s*"),
    "knowledge_patch": re.compile(r"^\s*补漏重点[：:]\s*"),
    "review_task": re.compile(r"^\s*复练任务[：:]\s*"),
}
_STRUCTURED_HINT_RE = re.compile(
    r"mistake_diagnosis|error_analysis|diagnosis|knowledge_patch|"
    r"knowledge_weakness|review_task|suggestion|错因诊断|补漏重点|复练任务",
    re.IGNORECASE,
)


def _strip_fence(text: str) -> str:
    match = re.search(
        r"```(?:json|javascript|js)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE
    )
    return match.group(1).strip() if match else text.strip()


def _decode_structured(raw: str) -> Any | None:
    text = _strip_fence(raw)
    if not text:
        return None

    starts = [0]
    starts.extend(i for i, ch in enumerate(text) if i > 0 and ch in "{[")
    decoder = json.JSONDecoder()
    for start in starts:
        candidate = text[start:].lstrip()
        if not candidate:
            continue
        try:
            value, _ = decoder.raw_decode(candidate)
            return value
        except (json.JSONDecodeError, ValueError):
            pass
        try:
            value = ast.literal_eval(candidate)
            if isinstance(value, (dict, list, str)):
                return value
        except (SyntaxError, ValueError):
            pass
    return None


def _coerce_text(value: Any, depth: int = 0) -> str:
    if value is None or depth > _MAX_DEPTH:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _coerce_text(item, depth + 1)
            if text and text not in parts:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(value, dict):
        for key in _TEXT_KEYS:
            if key in value:
                text = _coerce_text(value.get(key), depth + 1)
                if text:
                    return text
        if len(value) == 1:
            return _coerce_text(next(iter(value.values())), depth + 1)
    return ""


def _pick_field(mapping: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        if key not in mapping:
            continue
        value = _coerce_text(mapping.get(key))
        if value:
            return value
    return ""


def _parse_titled_text(text: str) -> dict[str, str]:
    stripped = _strip_fence(text)
    heading_re = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:\d+[.、)]\s*)?(?:[-*]\s*)?"
        r"(?:\*\*)?\s*(错因诊断|补漏重点|复练任务)\s*(?:\*\*)?\s*[：:]\s*(?:\*\*)?\s*"
    )
    matches = list(heading_re.finditer(stripped))
    if not matches:
        return {"mistake_diagnosis": stripped, "knowledge_patch": "", "review_task": ""}

    result = dict(_EMPTY)
    key_map = {
        "错因诊断": "mistake_diagnosis",
        "补漏重点": "knowledge_patch",
        "复练任务": "review_task",
    }
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(stripped)
        result[key_map[match.group(1)]] = stripped[match.end() : end].strip()
    return result


def normalize_analysis_payload(value: Any, depth: int = 0) -> dict[str, str]:
    """Normalize legacy/current analysis payloads to wrong-detail's three fields."""
    if value is None or depth > _MAX_DEPTH:
        return dict(_EMPTY)

    if isinstance(value, str):
        text = value.strip()
        if not text or _INVALID_LITERAL_RE.fullmatch(text):
            return dict(_EMPTY)
        decoded = _decode_structured(text)
        if decoded is not None and not (
            isinstance(decoded, str) and decoded.strip() == text
        ):
            return normalize_analysis_payload(decoded, depth + 1)
        return _parse_titled_text(text)

    if isinstance(value, list):
        if not value:
            return dict(_EMPTY)
        best = dict(_EMPTY)
        best_score = -1
        for item in value:
            candidate = normalize_analysis_payload(item, depth + 1)
            score = sum(bool(candidate.get(key)) for key, _ in _LABELS)
            if score > best_score:
                best = candidate
                best_score = score
        if best_score > 0:
            return best
        text = _coerce_text(value, depth + 1)
        return {"mistake_diagnosis": text, "knowledge_patch": "", "review_task": ""}

    if not isinstance(value, dict):
        text = _coerce_text(value, depth + 1)
        return {"mistake_diagnosis": text, "knowledge_patch": "", "review_task": ""}

    if not value:
        return dict(_EMPTY)

    direct = {
        "mistake_diagnosis": _pick_field(value, _DIAGNOSIS_KEYS),
        "knowledge_patch": _pick_field(value, _KNOWLEDGE_KEYS),
        "review_task": _pick_field(value, _TASK_KEYS),
    }
    if has_analysis_content(direct):
        return direct

    # wrong-detail only unwraps known response containers. Do not treat
    # unrelated fields such as {"error": "timeout"} as real analysis.
    for key in _WRAPPER_KEYS:
        if key not in value:
            continue
        nested = value.get(key)
        if isinstance(nested, str):
            decoded = _decode_structured(nested)
            if decoded is None:
                continue
            nested = decoded
        if isinstance(nested, (dict, list)):
            candidate = normalize_analysis_payload(nested, depth + 1)
            if has_analysis_content(candidate):
                return candidate
    return direct


def has_analysis_content(value: Any) -> bool:
    """Return True only when a payload contains printable analysis content."""
    if not isinstance(value, dict) or not value:
        return False
    return any(str(value.get(key, "") or "").strip() for key, _ in _LABELS)


def _looks_structured(raw: Any, normalized: dict[str, str]) -> bool:
    if isinstance(raw, (dict, list)):
        return True
    text = str(raw or "").strip()
    if not text:
        return False
    if text.startswith(("{", "[", "```")) or _STRUCTURED_HINT_RE.search(text):
        return True
    return (
        sum(bool(str(normalized.get(key, "") or "").strip()) for key, _ in _LABELS) > 1
    )


def format_analysis_for_export(raw: Any) -> str:
    """Convert a preferred raw analysis into printable human-readable text."""
    normalized = normalize_analysis_payload(raw)
    if not has_analysis_content(normalized):
        return ""

    structured = _looks_structured(raw, normalized)
    parts: list[str] = []
    for key, label in _LABELS:
        text = str(normalized.get(key, "") or "").strip()
        if not text:
            continue
        text = _PREFIX_RE[key].sub("", text).strip()
        if text:
            parts.append(f"{label}：{text}" if structured else text)
    return "\n".join(parts).strip()


def split_analysis_sections(text: Any) -> list[tuple[str, str]]:
    """Split printable analysis into semantic sections for rich exporters.

    ``format_analysis_for_export`` emits structured AI analysis as one line per
    wrong-detail section (错因诊断 / 补漏重点 / 复练任务).  PDF/DOCX renderers
    can use this helper to give those labels their own visual hierarchy without
    attempting to parse the original JSON payload again.  Ordinary unstructured
    analysis is returned as a single unlabeled section.
    """
    raw = str(text or "").strip()
    if not raw:
        return []

    heading_re = re.compile(r"^\s*(错因诊断|补漏重点|复练任务)\s*[：:]\s*(.*)$")
    sections: list[tuple[str, str]] = []
    current_label = ""
    current_lines: list[str] = []
    found_heading = False

    def flush() -> None:
        nonlocal current_lines
        body = "\n".join(current_lines).strip()
        if current_label or body:
            sections.append((current_label, body))
        current_lines = []

    for line in raw.splitlines():
        match = heading_re.match(line)
        if match:
            if current_label or current_lines:
                flush()
            current_label = match.group(1)
            first_body = match.group(2).strip()
            current_lines = [first_body] if first_body else []
            found_heading = True
        else:
            current_lines.append(line)

    if current_label or current_lines:
        flush()

    if not found_heading:
        return [("", raw)]
    return [(label, body) for label, body in sections if label or body]


def resolve_preferred_analysis(ai_analysis: Any, question_analysis: Any) -> str:
    """Match wrong-detail source priority: cached AI first, question analysis second."""
    ai_normalized = normalize_analysis_payload(ai_analysis)
    if has_analysis_content(ai_normalized):
        return format_analysis_for_export(ai_analysis)

    question_normalized = normalize_analysis_payload(question_analysis)
    if has_analysis_content(question_normalized):
        return format_analysis_for_export(question_analysis)
    return ""


_LIST_PREFIX_RE = re.compile(
    r"^\s*(?:(?:[-*•·▪◦])\s+|(?:\d{1,2}|[一二三四五六七八九十]+)[.、)]\s+)"
)
_SECTION_BODY_PREFIX_RE = {
    "错因诊断": re.compile(r"^\s*(?:错因诊断|错误诊断)\s*[：:]\s*"),
    "补漏重点": re.compile(r"^\s*(?:补漏重点|知识补漏|补漏)\s*[：:]\s*"),
    "复练任务": re.compile(
        r"^\s*(?:(?:复练|复盘|复习)任务|下一步练习|练习任务)\s*[：:]\s*"
    ),
}
_SENTENCE_RE = re.compile(r"[^。！？!?]+[。！？!?]?", re.UNICODE)


def clean_analysis_section_body(label: str, body: Any) -> str:
    """Remove duplicated historical labels before layout formatting."""
    text = re.sub(r"[ \t\u3000]+", " ", str(body or "")).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    prefix_re = _SECTION_BODY_PREFIX_RE.get(str(label or "").strip())
    if prefix_re:
        text = prefix_re.sub("", text, count=1).strip()
    return text


def _sentences(text: str) -> list[str]:
    """Split Chinese prose without dropping terminal punctuation."""
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    parts = [m.group(0).strip() for m in _SENTENCE_RE.finditer(normalized)]
    return [part for part in parts if part]


def split_analysis_paragraphs(body: Any, max_chars: int = 110) -> list[str]:
    """Turn diagnosis prose into short paragraphs suitable for A4 reading.

    Existing explicit paragraph breaks are preserved.  Otherwise sentences are
    grouped into roughly 2--4 lines instead of exporting one dense wall of text.
    """
    text = clean_analysis_section_body("错因诊断", body)
    if not text:
        return []

    explicit = [
        re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n|\n", text)
    ]
    explicit = [part for part in explicit if part]
    result: list[str] = []
    for block in explicit:
        sentences = _sentences(block) or [block]
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) > max_chars:
                result.append(current.strip())
                current = sentence
            else:
                current += sentence
        if current.strip():
            result.append(current.strip())
    return result or [text]


def _split_list_clause(text: str) -> list[str]:
    """Split a prose list into useful items while avoiding tiny fragments."""
    source = re.sub(r"\s+", " ", text or "").strip()
    if not source:
        return []

    # Full stops are strong boundaries; semicolons are useful secondary
    # boundaries for AI-generated knowledge patches and practice instructions.
    raw_parts = re.split(r"(?<=[。！？!?])\s*|[；;]\s*", source)
    items: list[str] = []
    pending = ""
    for raw in raw_parts:
        item = raw.strip().strip("；;")
        if not item:
            continue
        if pending:
            item = pending + item
            pending = ""
        # A very short lead-in such as “注意：” reads better joined to the next
        # clause than as its own bullet.
        plain_len = len(re.sub(r"[\s，。；：:、,.!?！？]", "", item))
        if plain_len < 7 and not item.endswith(("。", "！", "？", ".", "!", "?")):
            pending = item
            continue
        items.append(item)
    if pending:
        if items:
            items[-1] = f"{items[-1]} {pending}".strip()
        else:
            items.append(pending)
    return items


def split_analysis_list_items(label: str, body: Any) -> list[str]:
    """Convert knowledge patches / review tasks into scannable list items."""
    text = clean_analysis_section_body(label, body)
    if not text:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    explicit_items: list[str] = []
    saw_list_marker = False
    for line in lines:
        if _LIST_PREFIX_RE.match(line):
            saw_list_marker = True
            line = _LIST_PREFIX_RE.sub("", line, count=1).strip()
            if line:
                explicit_items.append(line)
        elif saw_list_marker and explicit_items:
            # Continuation line from an existing list item.
            explicit_items[-1] = f"{explicit_items[-1]} {line}".strip()
        else:
            explicit_items.extend(_split_list_clause(line))

    items = explicit_items if explicit_items else _split_list_clause(text)
    cleaned: list[str] = []
    for item in items:
        value = _LIST_PREFIX_RE.sub("", item, count=1).strip()
        value = (
            _SECTION_BODY_PREFIX_RE.get(label, re.compile(r"$^"))
            .sub("", value, count=1)
            .strip()
        )
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned or [text]
