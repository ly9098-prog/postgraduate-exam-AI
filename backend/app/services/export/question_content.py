"""Question-content extraction helpers shared by PDF/DOCX exporters.

The question bank contains records created by several import pipelines.  Newer
records normally expose ``content.text``/``content.stem`` while older records
may only contain text segments or a serialized ``raw_content`` snapshot.  This
module provides one conservative display-text fallback chain so export output
does not silently lose a stem.
"""

from __future__ import annotations

import ast
import json
import re
from html import unescape
from typing import Any

_SCRIPT_STYLE_RE = re.compile(
    r"<\s*(script|style)\b[^>]*>.*?</\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_BREAK_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_HTML_BLOCK_END_RE = re.compile(r"</\s*(?:p|div|li)\s*>", re.IGNORECASE)
_KNOWN_FORMAT_TAG_RE = re.compile(
    r"</?\s*(?:b|strong|i|em|sub|sup|p|div|span|ul|ol|li)"
    r"(?:\s+[^>]*)?\s*>",
    re.IGNORECASE,
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"[ \t\f\v]+")
_DICT_LIKE_RE = re.compile(r"^\s*[\[{].*[\]}]\s*$", re.S)

_PRIMARY_TEXT_KEYS = (
    "stem",
    "question_stem",
    "question_text",
    "prompt",
    "question",
    "question_content",
    "title",
    "text",
    "raw_text",
    "body",
    "description",
)
_CONTAINER_KEYS = (
    "content",
    "parsed_content",
    "data",
    "question_data",
    "raw_data",
)
_EXCLUDED_RAW_KEYS = {
    "answer",
    "analysis",
    "explanation",
    "options",
    "choices",
    "knowledge_points",
}
_IMAGE_SEGMENT_TYPES = {
    "image",
    "code_image",
    "math_image",
    "table_image",
    "formula_image",
}


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def clean_printable_text(value: Any) -> str:
    """Normalize text for PDF/DOCX output without destroying code operators.

    Exporters render plain text and therefore cannot execute HTML.  Only known
    formatting tags are removed; angle-bracket code such as ``#include
    <stdio.h>`` and comparisons such as ``x < y`` remain printable.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = _SCRIPT_STYLE_RE.sub("", text)
    text = _HTML_BREAK_RE.sub("\n", text)
    text = _HTML_BLOCK_END_RE.sub("\n", text)
    text = _KNOWN_FORMAT_TAG_RE.sub("", text)
    text = _CONTROL_RE.sub("", unescape(text))
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    # Preserve meaningful paragraph/newline structure but discard empty edges.
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def _clean_text(value: Any) -> str:
    """Backward-compatible internal alias."""
    return clean_printable_text(value)


def extract_segment_text(segments: Any) -> str:
    """Collect visible text from a rich-content segment list."""
    if not isinstance(segments, list):
        return ""

    parts: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        seg_type = str(segment.get("type") or "text").lower()
        if seg_type == "newline":
            if parts and parts[-1] != "\n":
                parts.append("\n")
            continue
        if seg_type in _IMAGE_SEGMENT_TYPES or seg_type in {"table", "table_markdown"}:
            continue
        for key in ("text", "content", "value"):
            text = _clean_text(segment.get(key))
            if text:
                parts.append(text)
                break

    text = "".join("\n" if part == "\n" else part for part in parts)
    return _clean_text(text)


def _parse_serialized(value: str) -> Any | None:
    raw = value.strip()
    if not raw or not _DICT_LIKE_RE.match(raw):
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        return ast.literal_eval(raw)
    except Exception:
        return None


def _extract_from_mapping(mapping: dict[str, Any], depth: int = 0) -> str:
    if depth > 5:
        return ""

    for key in _PRIMARY_TEXT_KEYS:
        value = mapping.get(key)
        text = _clean_text(value)
        if text:
            return text
        if isinstance(value, dict):
            nested = _extract_from_mapping(value, depth + 1)
            if nested:
                return nested

    segment_text = extract_segment_text(mapping.get("segments"))
    if segment_text:
        return segment_text

    for key in _CONTAINER_KEYS:
        value = mapping.get(key)
        if isinstance(value, dict):
            nested = _extract_from_mapping(value, depth + 1)
            if nested:
                return nested
        elif isinstance(value, list):
            nested = _extract_from_sequence(value, depth + 1)
            if nested:
                return nested
        else:
            text = _clean_text(value)
            if text:
                return text

    # Last conservative pass for uncommon import keys.  Never use answer,
    # analysis or options as a question stem.
    for key, value in mapping.items():
        if str(key).lower() in _EXCLUDED_RAW_KEYS:
            continue
        if isinstance(value, dict):
            nested = _extract_from_mapping(value, depth + 1)
            if nested:
                return nested
    return ""


def _extract_from_sequence(values: list[Any], depth: int = 0) -> str:
    if depth > 5:
        return ""
    texts: list[str] = []
    for value in values:
        if isinstance(value, dict):
            text = _extract_from_mapping(value, depth + 1)
        elif isinstance(value, list):
            text = _extract_from_sequence(value, depth + 1)
        else:
            text = _clean_text(value)
        if text:
            texts.append(text)
    return "\n".join(texts).strip()


def extract_raw_content_text(raw_content: Any) -> str:
    """Extract a stem from an old serialized raw-content snapshot."""
    if raw_content is None:
        return ""
    if isinstance(raw_content, dict):
        return _extract_from_mapping(raw_content)
    if isinstance(raw_content, list):
        return _extract_from_sequence(raw_content)

    raw = _clean_text(raw_content)
    if not raw:
        return ""
    parsed = _parse_serialized(raw)
    if isinstance(parsed, dict):
        return _extract_from_mapping(parsed)
    if isinstance(parsed, list):
        return _extract_from_sequence(parsed)
    # Plain legacy text is a legitimate stem.  Dict-like strings that failed
    # parsing are intentionally not printed verbatim into the exam paper.
    return "" if _DICT_LIKE_RE.match(raw) else raw


def extract_question_text(question: Any) -> str:
    """Return the best available display stem for an ORM object or dict.

    Fallback order:
      1. precomputed ``display_stem``
      2. ``content.stem`` / ``content.text``
      3. visible text from ``content.segments``
      4. serialized ``raw_content``
    """
    display_stem = _clean_text(_value(question, "display_stem"))
    if display_stem:
        return display_stem

    content = _value(question, "content") or {}
    if isinstance(content, dict):
        for key in ("stem", "text"):
            text = _clean_text(content.get(key))
            if text:
                return text
        text = extract_segment_text(content.get("segments"))
        if text:
            return text
    else:
        text = _clean_text(content)
        if text:
            return text

    return extract_raw_content_text(_value(question, "raw_content"))


def iter_question_image_urls(question: Any) -> list[str]:
    """Return de-duplicated top-level and segment image URLs."""
    urls: list[str] = []

    for key in ("image_urls", "image_url"):
        value = _value(question, key)
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    urls.append(item.strip())

    content = _value(question, "content") or {}
    segments = content.get("segments") if isinstance(content, dict) else None
    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            if str(segment.get("type") or "").lower() not in _IMAGE_SEGMENT_TYPES:
                continue
            url = segment.get("url") or segment.get("src")
            if isinstance(url, str) and url.strip():
                urls.append(url.strip())

    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


def has_visual_question_content(question: Any) -> bool:
    content = _value(question, "content") or {}
    if isinstance(content, dict):
        segments = content.get("segments")
        if isinstance(segments, list):
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                seg_type = str(segment.get("type") or "").lower()
                if seg_type in _IMAGE_SEGMENT_TYPES or seg_type in {"table", "table_markdown"}:
                    return True
    return bool(iter_question_image_urls(question))


def extract_option_text(value: Any) -> str:
    """Normalize plain or rich option values to printable text."""
    if isinstance(value, dict):
        for key in ("text", "content", "value"):
            text = _clean_text(value.get(key))
            if text:
                return text
        return extract_segment_text(value.get("segments"))
    return _clean_text(value)


def _normalize_option_collection(options: Any) -> dict[str, str]:
    """Normalize legacy/rich option payloads to an ordered printable mapping.

    Multi-blank questions have existed in several storage shapes.  Export only
    needs the visible option key/text pair, so this helper intentionally accepts
    both the canonical list form and older dict/list variants while dropping
    empty or non-printable entries.
    """
    normalized: dict[str, str] = {}

    if isinstance(options, dict):
        # A wrapped collection occasionally appears as {"options": ...}.
        if set(options).intersection({"options", "choices", "items"}) and not any(
            re.fullmatch(r"[A-Za-z]", str(key).strip()) for key in options
        ):
            for key in ("options", "choices", "items"):
                nested = options.get(key)
                if nested is not None:
                    nested_normalized = _normalize_option_collection(nested)
                    if nested_normalized:
                        return nested_normalized

        for raw_key, raw_value in options.items():
            key = str(raw_key or "").strip().upper()
            if not key or not re.fullmatch(r"[A-Z]", key):
                continue
            text = extract_option_text(raw_value)
            if text:
                normalized[key] = text
        return dict(sorted(normalized.items()))

    if not isinstance(options, list):
        return {}

    next_index = 0
    for item in options:
        key = ""
        text = ""
        if isinstance(item, dict):
            # Canonical: {key: "A", text: "..."}.  Some old imports used
            # label/id/option for the key and content/value for the text.
            key = str(
                item.get("key")
                or item.get("label")
                or item.get("option")
                or item.get("id")
                or ""
            ).strip().upper()
            text = extract_option_text(item)
            if not text and len(item) == 1:
                only_key, only_value = next(iter(item.items()))
                candidate_key = str(only_key or "").strip().upper()
                if re.fullmatch(r"[A-Z]", candidate_key):
                    key = candidate_key
                    text = extract_option_text(only_value)
        else:
            text = _clean_text(item)

        if not text:
            continue
        if not re.fullmatch(r"[A-Z]", key):
            while chr(65 + next_index) in normalized and next_index < 26:
                next_index += 1
            if next_index >= 26:
                continue
            key = chr(65 + next_index)
        next_index = max(next_index, ord(key) - 64)
        if key not in normalized:
            normalized[key] = text

    return dict(sorted(normalized.items()))


def _normalize_blank_groups(groups: Any) -> list[dict[str, Any]]:
    """Normalize known blank-group shapes without guessing slot semantics."""
    if isinstance(groups, dict):
        nested = groups.get("blank_option_groups") or groups.get("blank_groups") or groups.get("groups")
        if nested is not None:
            return _normalize_blank_groups(nested)

        # Legacy id-keyed shape: {"①": {"A": "..."}, "②": {...}}.
        converted: list[dict[str, Any]] = []
        for raw_id, raw_options in groups.items():
            slot_id = str(raw_id or "").strip()
            if not slot_id or re.fullmatch(r"[A-Za-z]", slot_id):
                continue
            options = _normalize_option_collection(raw_options)
            if options:
                converted.append({"id": slot_id, "options": options})
        return converted

    if not isinstance(groups, list):
        return []

    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        slot_id = str(
            group.get("id")
            or group.get("marker")
            or group.get("slot_id")
            or group.get("blank_id")
            or ""
        ).strip()
        if not slot_id:
            # A few historical snapshots omitted ids but retained a clearly
            # grouped list.  Stable positional ids are safer than losing all
            # options during export.
            slot_id = str(index + 1)
        options = _normalize_option_collection(
            group.get("options") or group.get("choices") or group.get("items")
        )
        if not options or slot_id in seen_ids:
            continue
        seen_ids.add(slot_id)
        result.append({"id": slot_id, "options": options})
    return result


def extract_blank_option_groups(question: Any) -> list[dict[str, Any]]:
    """Return printable option groups for a multi-blank choice question.

    Canonical questions store groups in ``content.blank_option_groups`` and
    leave top-level ``options`` empty.  Older data may use ``blank_groups``, a
    nested ``parsed_content`` payload, grouped top-level options, or flat shared
    options.  This function accepts those compatible shapes so exports remain
    stable across historical question revisions.
    """
    content = _value(question, "content")
    mappings: list[dict[str, Any]] = []
    if isinstance(content, dict):
        mappings.append(content)
        parsed_content = content.get("parsed_content")
        if isinstance(parsed_content, dict):
            mappings.append(parsed_content)

    if isinstance(question, dict):
        mappings.append(question)

    raw_content = _value(question, "raw_content")
    if isinstance(raw_content, dict):
        mappings.append(raw_content)
    elif isinstance(raw_content, str):
        parsed = _parse_serialized(raw_content)
        if isinstance(parsed, dict):
            mappings.append(parsed)

    for mapping in mappings:
        for key in ("blank_option_groups", "blank_groups", "groups"):
            groups = _normalize_blank_groups(mapping.get(key))
            if groups:
                return groups

    raw_options = _value(question, "options")
    groups = _normalize_blank_groups(raw_options)
    if groups:
        return groups

    # Final compatibility path: some old multi-blank revisions kept one flat
    # shared A/B/C/D option map instead of materializing blank groups.
    question_type = str(_value(question, "question_type") or "")
    if question_type != "multi_blank_choice":
        return []
    shared_options = _normalize_option_collection(raw_options)
    if len(shared_options) < 2:
        return []

    slot_ids: list[str] = []
    if isinstance(content, dict):
        for key in ("blank_ids", "blank_markers"):
            values = content.get(key)
            if isinstance(values, list):
                slot_ids = [str(value or "").strip() for value in values if str(value or "").strip()]
                if slot_ids:
                    break

    # Answer ids are more explicit than anonymous ``（ ）`` stem blanks.
    try:
        from app.features.multi_blank_choice import extract_blank_slots, parse_multi_blank_answer

        parsed_answer, _ = parse_multi_blank_answer(_value(question, "answer"), allow_positional=False)
        if len(parsed_answer) >= 2:
            slot_ids = list(parsed_answer.keys())
        if not slot_ids:
            slot_ids = extract_blank_slots(extract_question_text(question))
    except Exception:
        slot_ids = slot_ids or []

    if len(slot_ids) < 2:
        return []
    return [
        {"id": slot_id, "options": dict(shared_options)}
        for slot_id in slot_ids
    ]


def get_shared_blank_options(groups: Any) -> dict[str, str] | None:
    """Return one option map when every blank uses the same choices."""
    normalized = _normalize_blank_groups(groups)
    if not normalized:
        return None
    first = normalized[0]["options"]
    signature = tuple(first.items())
    if all(tuple(group["options"].items()) == signature for group in normalized[1:]):
        return dict(first)
    return None


def format_question_answer(question: Any) -> str:
    """Format a stored answer for human-facing PDF/DOCX output.

    Multi-blank answers are stored canonically as ``①:A;②:D`` for grading.
    Export uses the more compact exam-paper form ``①A；②D`` so the answer grid
    stays on one line and does not expose storage punctuation.
    """
    raw_answer = _value(question, "answer")
    fallback = _clean_text(raw_answer)
    if str(_value(question, "question_type") or "") != "multi_blank_choice":
        return fallback

    groups = extract_blank_option_groups(question)
    slot_ids = [str(group.get("id") or "").strip() for group in groups]
    slot_ids = [slot_id for slot_id in slot_ids if slot_id]

    try:
        from app.features.multi_blank_choice import parse_multi_blank_answer

        parsed, _ = parse_multi_blank_answer(
            raw_answer,
            slot_ids=slot_ids or None,
            allow_positional=bool(slot_ids),
        )
    except Exception:
        parsed = {}

    if not parsed:
        # At least collapse accidental line breaks/ASCII separators from legacy
        # snapshots, even when the answer cannot be parsed confidently.
        return re.sub(r"\s*[;；]\s*", "；", fallback.replace("\n", " ")).strip()

    ordered_ids = [slot_id for slot_id in slot_ids if slot_id in parsed]
    ordered_ids.extend(slot_id for slot_id in parsed if slot_id not in ordered_ids)

    def display_slot(slot_id: str) -> str:
        slot_id = str(slot_id).strip()
        if re.fullmatch(r"\d+", slot_id):
            return f"({slot_id})"
        return slot_id

    return "；".join(f"{display_slot(slot_id)}{parsed[slot_id]}" for slot_id in ordered_ids)
