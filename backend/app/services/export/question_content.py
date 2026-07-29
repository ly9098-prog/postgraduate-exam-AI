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
        if seg_type in _IMAGE_SEGMENT_TYPES or seg_type == "table_markdown":
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
                if seg_type in _IMAGE_SEGMENT_TYPES or seg_type == "table_markdown":
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
