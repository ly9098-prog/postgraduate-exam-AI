"""Code Structure Reconstruction Engine — rule-based, no LLM dependency.

A pure rule-based engine that fixes OCR-damaged code text by:
1. Repairing broken operators (``* =`` → ``*=``, ``= =`` → ``==``, etc.)
2. Recovering line breaks from compressed code
3. Applying brace-depth-based indentation
4. Handling code-fence boundaries correctly

Designed as a fast pre-processor for ``code_structure_stage.py``, reducing
LLM cost by handling common simple cases with rules alone.

Usage::

    from app.features.code_structure_reconstructor import reconstruct_code

    fixed = reconstruct_code("for(int i=0;i<n;i++)sum++;")

"""

from __future__ import annotations

import logging
import re
from typing import Final

logger = logging.getLogger(__name__)

# ============================================================================
# Phase 1: OCR operator repair
# ============================================================================

# Ordered list of (pattern, replacement) pairs for operator fixes.
# Applied in sequence to avoid partial-match cascading.
_OPERATOR_FIXES: Final[list[tuple[str, str]]] = [
    # Multi-char operators: longest patterns first to avoid partial matches
    (r"(?<!\*)\*\s*=(?!\s*=)", "*="),      # * = (but not **=)
    (r"\+\s*\+", "++"),                     # + +
    (r"-\s*>(?!\s*>)", "->"),              # - > (but not -->)
    (r"(?<![<>])=\s*=(?!\s*=)", "=="),     # = = (but not ===)
    (r"!\s*=", "!="),                       # ! =
    (r"(?<!\*)\*\*(?!\s*[/*])", "**"),      # * * (power op)
    r"(?<![+\-*/%&|^<>!])([<>=])"
    r"\s*=\s*(?!=)",                        # <= >= (but not <<= >>=)
    # Single fixed-form: < = → <=, > = → >=
    # Note: the above regex handles the general case
]

# Simpler: just apply direct replacements for known broken patterns
# These survive the context-sensitive checks above and are safe
_BROKEN_OP_PATTERNS: Final[list[tuple[re.Pattern, str]]] = [
    (re.compile(r"(?<!\*) \* \s* = (?!\s*=)"), " *= "),
    (re.compile(r"(?<!\w) \+ \+ (?!\w)"), " ++ "),
    (re.compile(r" - > (?!\s*>)"), " -> "),
    (re.compile(r"(?<![<>=!]) = = (?!\s*=)"), " == "),
    (re.compile(r" ! = "), " != "),
    (re.compile(r" < = "), " <= "),
    (re.compile(r" > = "), " >= "),
    (re.compile(r" \| \| "), " || "),
    (re.compile(r" & & "), " && "),
    (re.compile(r" \? \? "), " ?? "),
    (re.compile(r" / / "), " // "),
    (re.compile(r" \* / "), " */ "),
    (re.compile(r" / \* "), " /* "),
]


def _fix_ocr_operators(code: str) -> str:
    """Fix common OCR operator damage patterns.

    Handles:
    - ``* =`` → ``*=`` (assignment-combined ops)
    - ``= =`` → ``==``
    - ``- >`` → ``->``
    - ``+ +`` → ``++``
    - ``< =`` → ``<=``, ``> =`` → ``>=``
    - ``! =`` → ``!=``
    - ``| |`` → ``||``, ``& &`` → ``&&``
    """
    if not code:
        return code

    text = code
    for pattern, replacement in _BROKEN_OP_PATTERNS:
        text = pattern.sub(replacement, text)

    return text


# ============================================================================
# Phase 2: Code structure reconstruction
# ============================================================================

# Semicolon is NOT always a line-break signal. Things like ``for(;;)``
# should not be split. We detect loop/control-flow header context.
_RE_FOR_WHILE_HEADER = re.compile(
    r"\b(for|while|if|else\s+if|switch|catch)\s*\("
)
_RE_FUNC_SIGNATURE = re.compile(
    r"\b(?:int|void|char|float|double|long|short|unsigned|signed|const|"
    r"static|bool|ElemType|Status|LinkList|BiTree|SqList|Stack|Queue|"
    r"TreeNode|ListNode)\s+\*?\w+\s*\("
)
_RE_STRUCT_ENUM_CLASS = re.compile(
    r"\b(?:typedef\s+)?(?:struct|class|enum|union)\s+\w+\s*"
)
_RE_CONTROL_KEYWORD = re.compile(r"\b(else|do)\b")
_RE_ELSE_BRANCH = re.compile(r"^\s*else\s*")
_RE_OCRLANG_CONFUSED = re.compile(
    r"(?<!\w)(c\+\+|java|python|ruby|go|rust|kotin|swift|php)\b",
    re.IGNORECASE,
)


def _is_part_of_control_header(line: str, position: int) -> bool:
    """Check if the character at ``position`` in ``line`` is inside a
    ``for/while/if (...)`` header (i.e., between the parens)."""
    # Count open parens from start to position vs. total
    before = line[:position]
    open_parens = before.count("(") - before.count(")")
    return open_parens > 0


def _split_semicolons(text: str) -> str:
    """Split statements at semicolons, respecting control-flow headers.

    ``for (;;)`` must not be split.  Algorithm:
    1. Walk char-by-char
    2. Track paren depth to detect control-header context
    3. ``;`` at depth > 0 (inside parens) → keep inline
    4. ``;`` at depth == 0 → insert newline
    5. ``{`` → insert newline after
    6. ``}`` → insert newline before and after
    """
    if not text:
        return text

    lines: list[str] = []
    current = ""
    paren_depth = 0
    brace_depth = 0
    in_string = False
    string_char = ""

    i = 0
    while i < len(text):
        ch = text[i]
        next_ch = text[i + 1] if i + 1 < len(text) else ""

        # Toggle string context (simple heuristic)
        if ch in ("\"", "'", "`") and not _is_escaped(text, i):
            if in_string and ch == string_char:
                in_string = False
            elif not in_string:
                in_string = True
                string_char = ch

        if not in_string:
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth -= 1
            elif ch == "{":
                brace_depth += 1
                current += ch
                # Newline after opening brace if not followed by newline
                if next_ch and next_ch != "\n":
                    lines.append(current)
                    current = ""
                else:
                    current += ch
                if next_ch == "\n":
                    lines.append(current)
                    current = ""
                    i += 1  # skip \n
                i += 1
                continue
            elif ch == "}":
                brace_depth -= 1
                # Flush current line before closing brace
                if current.strip():
                    lines.append(current)
                current = "}" if ch == "}" else ""
                # Newline after closing brace
                if next_ch and next_ch not in ("}", "\n"):
                    lines.append(current)
                    current = ""
                i += 1
                continue

            # Semicolon handling: split if at depth 0 (not inside for/if parens)
            # and not in a ``for (;;)`` header
            if ch == ";" and paren_depth == 0:
                current += ch
                lines.append(current)
                current = ""
                i += 1
                continue

        current += ch
        i += 1

    if current.strip():
        lines.append(current)

    return "\n".join(lines)


def _is_escaped(text: str, pos: int) -> bool:
    """Check if character at ``pos`` is escaped (preceded by odd number of
    backslashes)."""
    if pos <= 0:
        return False
    backslashes = 0
    p = pos - 1
    while p >= 0 and text[p] == "\\":
        backslashes += 1
        p -= 1
    return backslashes % 2 == 1


def _indent_code(text: str, indent_size: int = 4) -> str:
    """Apply brace-depth-based indentation.

    Rules:
    - ``{`` → next lines get +1 indent
    - ``}`` → closing brace gets -1 indent (before itself), then -1 for subsequent
    - ``for/while/if/else`` blocks get an additional indent for their body
    """
    if not text.strip():
        return text

    lines = text.split("\n")
    result: list[str] = []
    depth = 0
    indent = " " * indent_size

    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append("")
            continue

        # Track brace changes in this line
        net_open = stripped.count("{")
        net_close = stripped.count("}")

        # Closing braces: dedent before the brace
        if net_close > 0:
            # If line starts with } (or only contains }), dedent
            if stripped[0] == "}":
                actual_depth = max(0, depth - net_close)
            else:
                actual_depth = max(0, depth)

            result.append(indent * actual_depth + stripped)
            depth = max(0, depth - net_close + net_open)
        else:
            result.append(indent * depth + stripped)
            depth += net_open

        # Ensure depth doesn't go negative
        depth = max(0, depth)

    return "\n".join(result)


def _reconstruct_compressed_code(text: str) -> str:
    """Reconstruct compressed code — split merged control-flow structures.

    Detects patterns like::

        for(...)for(...)if(...)stmt;
        struct X { int a; int b; };

    And splits them into multi-line indented structures.

    This is a simplified heuristic — complex cases still go to LLM.
    """
    if not text.strip():
        return text

    # Phase 2a: Insert newlines before control-flow keywords when they're
    # not already at line start.
    text = re.sub(
        r"(?<=\S)\s*(?=\b(for|while|if|else if|else|switch|case |"
        r"return|break|continue|struct|class|typedef|enum)\b)",
        r"\n",
        text,
    )

    # Phase 2b: Ensure closing brace followed by a keyword gets a newline
    text = re.sub(r"\}(\s*)(?=\b(else|catch|finally|while)\b)", r"}\n\1", text)

    # Phase 2c: Split after ; when followed by a keyword with no newline
    text = re.sub(
        r";\s*(?=\b(for|while|if|struct|class|typedef|return)\b)",
        r";\n",
        text,
    )

    return text


def _trim_line(line: str) -> str:
    """Trim a single line while preserving leading whitespace structure
    that might indicate indentation intent."""
    stripped = line.strip()
    if not stripped:
        return stripped
    return stripped


def _has_ocr_lang_confusion(text: str) -> bool:
    """Detect if text contains OCR-generated language labels like
    ``c++`` in unexpected places."""
    return bool(_RE_OCRLANG_CONFUSED.search(text))


# ============================================================================
# Phase 3: Code-fence handling
# ============================================================================

_FENCE_RE = re.compile(r"(```(?:\w*))")

_FENCE_DETECT_RE = re.compile(r"```")


def _reconstruct_fenced_code(text: str) -> str:
    """Apply reconstruction to code INSIDE fences, leave text outside alone.

    Only processes content between ``` markers.
    """
    if not text or "```" not in text:
        return text

    parts = _FENCE_RE.split(text)
    result: list[str] = []
    in_fence = False
    for i, part in enumerate(parts):
        if _FENCE_DETECT_RE.match(part):
            # fence marker
            result.append(part)
            in_fence = not in_fence
            continue
        if in_fence:
            # code content inside fence — apply reconstruction
            fixed = _reconstruct_compressed_code(part)
            fixed = _fix_ocr_operators(fixed)
            fixed = _split_semicolons(fixed)
            fixed = _indent_code(fixed)
            result.append(fixed)
        else:
            result.append(part)

    return "".join(result)


# ============================================================================
# Public API
# ============================================================================


def reconstruct_code(
    text: str,
    *,
    fix_operators: bool = True,
    fix_newlines: bool = True,
    fix_indentation: bool = True,
    fence_aware: bool = True,
) -> str:
    """Reconstruct code structure in the given text.

    A pure rule-based engine that fixes OCR-damaged code text without
    any LLM dependency.  Designed for fast common-case fixes.

    The reconstruction pipeline (when all options enabled):

    1. **Operators**: ``* = → *=``, ``= = → ==``, ``- > → ->``, etc.
    2. **Compression recovery**: split ``for(...)for(...)`` into structure
    3. **Semicolon splitting**: ``stmt;stmt;`` → new lines
    4. **Indentation**: brace-depth-based with 4-space indent
    5. **Fence awareness**: only modifies content inside ``` markers
       (if ``fence_aware=True``)

    Args:
        text: The damaged code text (may include text + code mixed).
        fix_operators: Whether to fix OCR operator damage.
        fix_newlines: Whether to recover line breaks from compressed code.
        fix_indentation: Whether to apply brace-depth indentation.
        fence_aware: If True, only reconstruct content inside `` ``` ``
                     fences; leave non-fenced text unchanged.  If False,
                     treat the entire text as code.

    Returns:
        Reconstructed code string.
    """
    if not text:
        return text

    if fence_aware and "```" in text:
        return _reconstruct_fenced_code(text)

    # Non-fenced mode: treat as raw code
    result = text

    # Step 1: Fix OCR operator damage
    if fix_operators:
        result = _fix_ocr_operators(result)

    # Step 2: Recover structure from compressed code
    if fix_newlines:
        result = _reconstruct_compressed_code(result)

    # Step 3: Split semicolons into lines
    if fix_newlines:
        result = _split_semicolons(result)

    # Step 4: Apply indentation
    if fix_indentation:
        result = _indent_code(result)

    return result


def reconstruct_and_validate(text: str) -> dict:
    """Reconstruct code and return a validation report.

    For use in pipeline stages that need to decide whether reconstruction
    improved the code.

    Returns:
        {
            "original": str,
            "reconstructed": str,
            "changed": bool,
            "operators_fixed": int,
            "brace_diff_before": int,
            "brace_diff_after": int,
        }
    """
    original_count_open = text.count("{")
    original_count_close = text.count("}")
    original_brace_diff = original_count_open - original_count_close

    fixed = reconstruct_code(text)

    # Count operator fixes by comparing before/after
    operator_fix_count = 0
    for pattern, _replacement in _BROKEN_OP_PATTERNS:
        before = len(pattern.findall(text))
        after = len(pattern.findall(fixed))
        if before > after:
            operator_fix_count += before - after

    fixed_count_open = fixed.count("{")
    fixed_count_close = fixed.count("}")
    fixed_brace_diff = fixed_count_open - fixed_count_close

    return {
        "original": text,
        "reconstructed": fixed,
        "changed": text != fixed,
        "operators_fixed": operator_fix_count,
        "brace_diff_before": original_brace_diff,
        "brace_diff_after": fixed_brace_diff,
        "braces_balanced": fixed_count_open == fixed_count_close,
    }
