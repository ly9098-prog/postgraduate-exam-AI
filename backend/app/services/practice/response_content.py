"""Pure projection of revision content for student practice responses."""

import re

from app.features.text_normalizer import _split_inline_roman_subitems
from app.services.pdf_text_normalizer import deduplicate_repeated_text
from app.utils.question_content import (
    reconcile_student_stem_fields,
    strip_student_segment_metadata,
)

# Regex: lines ending with a trailing operator (OCR-split code expressions)
_CODE_OP_SPLIT_RE = re.compile(r"(?:<=|>=|==|!=|&&|\|\||<<|>>|[<>=!+\-*/%&|^])\s*$")

# Code detection signals (mirrors frontend containsCode logic)
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
    """Heuristic: does text contain enough signals to be code?"""
    if not isinstance(text, str) or not text:
        return False
    score = 0
    for sig in _CODE_SIGNALS:
        if sig in text:
            score += 1
    for kw in _DS_KW:
        if kw in text:
            score += 2
    for kw in _CONTROL_KW:
        if re.search(r"\b" + re.escape(kw) + r"\b", text):
            score += 1
    return score >= 3


_TRUE_FALSE_OPTIONS = {"A": "正确", "B": "错误"}


def ensure_true_false_options(question_type: str, options: dict | None) -> dict | None:
    if question_type == "true_false" and not options:
        return _TRUE_FALSE_OPTIONS
    return options


def _fix_code_operator_splits(text: str) -> str:
    """Merge lines where a trailing operator was split across newlines by OCR.

    Handles common OCR artifacts like:
      ``i*=\n2)`` → ``i*=2)``   (operator then integer)
      ``n==\n1)`` → ``n==1)``
      ``k +=\n2)`` → ``k +=2)``
    """
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


def sanitize_text_field(value: str | None) -> str | None:
    if not isinstance(value, str):
        return value

    # Normalize line endings before any processing
    value = re.sub(r"\r\n", "\n", value)
    value = re.sub(r"\r", "\n", value)

    # Code content must bypass dedup and roman-split to preserve
    # indentation, repeated lines, and control-statement structure.
    # Only apply normalize operators across newlines (OCR artifact fix).
    if contains_code(value):
        value = _fix_code_operator_splits(value)
        return value

    value = deduplicate_repeated_text(value)
    value = _split_inline_roman_subitems(value)
    value = _fix_code_operator_splits(value)
    return value


def sanitize_question_content(content: dict | None) -> dict | None:
    if not isinstance(content, dict):
        return content

    sanitized = dict(content)
    for field in ("text", "stem"):
        if field in sanitized:
            sanitized[field] = sanitize_text_field(sanitized[field])

    # Historical revisions can contain a freshly edited ``text`` alongside a
    # stale ``stem``. Reconcile them before the payload reaches renderers so the
    # newest revision cannot look like an older question version.
    sanitized = reconcile_student_stem_fields(sanitized)

    # Strip admin-only fields that should never reach student clients
    sanitized.pop("source_snapshot_url", None)
    sanitized.pop("source_snapshot_full_page", None)
    sanitized.pop("visual_regions", None)
    sanitized.pop("visual_region_ids", None)

    return strip_student_segment_metadata(sanitized)


def _sanitize_option_value(value: str | None) -> str | None:
    """Sanitize a single option value — skip roman-subitem splitting.

    Option values are short display text (e.g. \"I、II、III\", \"O(n)\").
    Applying _split_inline_roman_subitems here corrupts enumeration values
    by inserting newlines inside short option text. Only apply code-operator
    split (for code options) and collapse embedded newlines (OCR artifacts).
    """
    if not isinstance(value, str):
        return value
    # Normalize line endings (PDF/OCR can produce \r\n)
    value = re.sub(r"\r\n", "\n", value)
    value = re.sub(r"\r", "\n", value)
    value = _fix_code_operator_splits(value)
    # Collapse remaining newlines to space — prevents option content from
    # rendering as two lines (newline in option → mp-html <br> → visual doubling)
    value = re.sub(r"\n+", " ", value).strip()
    return value


def sanitize_question_options(options: dict | None) -> dict | None:
    if not isinstance(options, dict):
        return options

    sanitized = dict(options)
    for key, value in sanitized.items():
        if isinstance(value, dict):
            # Rich format: {"A": {"text": "...", "segments": [...]}}
            text_val = value.get("text") or value.get("value") or ""
            sanitized[key] = {
                **value,
                "text": _sanitize_option_value(text_val),
            }
        else:
            sanitized[key] = _sanitize_option_value(value)
    return sanitized
