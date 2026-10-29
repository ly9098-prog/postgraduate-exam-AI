"""Student-facing wrong-book text, code and option sanitization."""

from __future__ import annotations


def _contains_code(text, *, ports):
    if not ports("isinstance")(text, ports("str")) or not text:
        return False
    score = ports("sum")((1 for sig in ports("_CODE_SIGNALS") if sig in text))
    score += ports("sum")((2 for kw in ports("_DS_KW") if kw in text))
    score += ports("sum")(
        (
            1
            for kw in ports("_CONTROL_KW")
            if ports("re").search("\\b" + ports("re").escape(kw) + "\\b", text)
        )
    )
    return score >= 3


def _fix_code_operator_splits(text, *, ports):
    """Merge lines where a trailing operator was split across newlines by OCR."""
    if not ports("isinstance")(text, ports("str")) or "\n" not in text:
        return text
    lines = text.split("\n")
    merged = [lines[0]]
    for line in lines[1:]:
        if ports("_CODE_OP_SPLIT_RE").search(merged[-1]):
            merged[-1] += line.lstrip()
        else:
            merged.append(line)
    return "\n".join(merged)


def _sanitize_text_field(value, *, ports):
    if not ports("isinstance")(value, ports("str")):
        return value
    value = ports("re").sub("\\r\\n?", "\n", value)
    # Ordinary OCR deduplication/roman splitting must not rewrite code.
    if ports("_contains_code")(value):
        return ports("_fix_code_operator_splits")(value)
    value = ports("deduplicate_repeated_text")(value)
    value = ports("_split_inline_roman_subitems")(value)
    return ports("_fix_code_operator_splits")(value)


def _sanitize_content(content, *, ports):
    if ports("isinstance")(content, ports("str")):
        content = {"text": content}
    if not ports("isinstance")(content, ports("dict")):
        return None
    sanitized = ports("dict")(content)
    for field in ("text", "stem"):
        if field in sanitized:
            sanitized[field] = ports("_sanitize_text_field")(sanitized[field])
    sanitized = ports("reconcile_student_stem_fields")(sanitized)
    sanitized.pop("source_snapshot_url", None)
    sanitized.pop("source_snapshot_full_page", None)
    sanitized.pop("visual_regions", None)
    sanitized.pop("visual_region_ids", None)
    return ports("strip_student_segment_metadata")(sanitized)


def _sanitize_option_value(value, *, ports):
    """Sanitize an option without roman-subitem splitting or deduplication."""
    if not ports("isinstance")(value, ports("str")):
        return value
    value = ports("re").sub("\\r\\n?", "\n", value)
    value = ports("_fix_code_operator_splits")(value)
    return ports("re").sub("\\n+", " ", value).strip()


def _sanitize_options(options, *, ports):
    if not ports("isinstance")(options, ports("dict")):
        return options
    sanitized = ports("dict")(options)
    for key, value in sanitized.items():
        if ports("isinstance")(value, ports("dict")):
            rich = ports("dict")(value)
            text = rich.get("text")
            if text in (None, ""):
                text = rich.get("value")
            if ports("isinstance")(text, ports("str")):
                rich["text"] = ports("_sanitize_option_value")(text)
            sanitized[key] = rich
        else:
            sanitized[key] = ports("_sanitize_option_value")(value)
    return sanitized
