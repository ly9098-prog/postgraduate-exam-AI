"""Pure text sanitization helpers for review scheduler.

Extracted from review_scheduler.py to keep the main service focused on
DB orchestration and SM-2 scheduling logic.
"""

from __future__ import annotations

import re

from app.features.text_normalizer import _split_inline_roman_subitems
from app.services.pdf_text_normalizer import deduplicate_repeated_text
from app.utils.question_content import strip_student_segment_metadata

_CODE_OP_SPLIT_RE = re.compile(r"(?:<=|>=|==|!=|&&|\|\||<<|>>|[<>=!+\-*/%&|^])\s*$")
_CODE_SIGNALS = [
    "return",
    "printf",
    "scanf",
    "malloc",
    "free",
    "NULL",
    "struct",
    "typedef",
    "enum",
    "union",
    "int ",
    "void ",
    "char ",
    "float ",
    "double ",
    "bool",
    "const",
    "static",
    "sizeof",
    "->",
    "::",
    "{",
    "}",
    ";",
    "++",
    "--",
    "+=",
    "-=",
    "*=",
    "/=",
    "#include",
    "#define",
]
_CONTROL_KW = [
    "for",
    "while",
    "if",
    "else if",
    "else",
    "switch",
    "return",
    "break",
    "continue",
    "case",
    "do",
]
_DS_KW = [
    "LNode",
    "TNode",
    "BiTNode",
    "BiTree",
    "BSTNode",
    "LinkList",
    "SqList",
    "Stack",
    "Queue",
    "SqStack",
    "ElemType",
    "Status",
]


def contains_code(text: str) -> bool:
    """Detect whether text contains enough signals to be treated as code."""
    if not isinstance(text, str) or not text:
        return False
    score = sum(1 for sig in _CODE_SIGNALS if sig in text)
    score += sum(2 for kw in _DS_KW if kw in text)
    score += sum(
        1 for kw in _CONTROL_KW if re.search(r"\b" + re.escape(kw) + r"\b", text)
    )
    return score >= 3


def fix_code_operator_splits(text: str) -> str:
    """Merge lines split at code operators (e.g. a +\n b → a + b)."""
    if not isinstance(text, str) or "\n" not in text:
        return text
    lines = text.split("\n")
    merged = [lines[0]]
    for line in lines[1:]:
        if _CODE_OP_SPLIT_RE.search(merged[-1]):
            merged[-1] += line.lstrip()
        else:
            merged.append(line)
    return "\n".join(merged)


def sanitize_review_text(value: str | None) -> str | None:
    """Normalize review text: CRLF, code splits, dedup, roman sub-items."""
    if not isinstance(value, str):
        return value
    value = re.sub(r"\r\n?", "\n", value)
    if contains_code(value):
        return fix_code_operator_splits(value)
    value = deduplicate_repeated_text(value)
    value = _split_inline_roman_subitems(value)
    return fix_code_operator_splits(value)


def sanitize_review_content(content: dict | str | None) -> dict:
    """Normalize review content dict, stripping visual region fields."""
    if isinstance(content, str):
        content = {"text": content}
    elif not isinstance(content, dict):
        content = {}
    sanitized = dict(content)
    for field in ("text", "stem"):
        if field in sanitized:
            sanitized[field] = sanitize_review_text(sanitized[field])
    if sanitized.get("stem"):
        sanitized["text"] = sanitized["stem"]
    for field in (
        "source_snapshot_url",
        "source_snapshot_full_page",
        "visual_regions",
        "visual_region_ids",
    ):
        sanitized.pop(field, None)
    return strip_student_segment_metadata(sanitized)


def sanitize_review_option_value(value):
    """Normalize a single option value (string or dict)."""
    if isinstance(value, str):
        value = re.sub(r"\r\n?", "\n", value)
        value = fix_code_operator_splits(value)
        return re.sub(r"\n+", " ", value).strip()
    if isinstance(value, dict):
        result = dict(value)
        text = result.get("text")
        if text in (None, ""):
            text = result.get("value")
        if isinstance(text, str):
            result["text"] = sanitize_review_option_value(text)
        return result
    return value


def sanitize_review_options(options) -> dict:
    """Normalize all option values in a dict."""
    if not isinstance(options, dict):
        return {}
    return {key: sanitize_review_option_value(value) for key, value in options.items()}
