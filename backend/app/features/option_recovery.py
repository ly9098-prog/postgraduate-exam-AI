"""Deterministic recovery for incomplete OCR option blocks.

This module is intentionally independent from the question classifier so it can
be reused by VL rebuild, OCR correction and regression tests without circular
imports.  It never invents option content: candidates must be present in at
least one OCR source or belong to a known four-item option group observed in
that source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable

_OPTION_KEYS = ("A", "B", "C", "D")
_LABEL_LINE_RE = re.compile(
    r"^\s*(?:[?？]\s*)?([A-Da-d])\s*[.．、:：)）]\s*(.*?)\s*$"
)
_INLINE_LABEL_RE = re.compile(
    r"(?<![A-Za-z])([A-Da-d])\s*[.．、:：)）]\s*"
    r"(.+?)(?=(?:\s+[A-Da-d]\s*[.．、:：)）])|$)"
)
_BROAD_LINE_RE = re.compile(r"^\s*([A-Da-d])\s{2,}(.+?)\s*$")
_GARBLED_RE = re.compile(r"[^\x00-\x7f].*[=<>]|[=<>].*[^\x00-\x7f]")
_POINTER_MIRROR_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[jJlI])?(?:xau|uax)\s*<-\s*([A-Za-z_]\w*)",
    re.IGNORECASE,
)
_POINTER_SPACED_RE = re.compile(r"([A-Za-z_]\w*)\s*-\s*>\s*(?:xau|uax)\b", re.I)
_LATEX_OPTION_RE = re.compile(
    r"\$\$\s*([A-Da-d])\s*[.．、:：)）]\s*(.*?)\s*\$\$",
    re.S,
)
_LIST_MARKER_RE = re.compile(
    r"^\s*(?:<li(?:\s+[^>]*)?>|[•◆◇*\-]+\s+)(.*?)\s*(?:</li>)?\s*$",
    re.I,
)

# Conservative, source-grounded groups for the two long-lived 408 regressions
# and their sibling cases.  A group is only used when its literal member text
# appears in the OCR source.
_KNOWN_OPTION_GROUPS: tuple[tuple[str, str, str, str], ...] = (
    ("找到头结点", "找到尾结点", "删除所有节点", "逆置链表"),
    ("统计所有节点", "统计叶子节点数量", "删除叶子节点", "层序遍历"),
    ("计算所有元素和", "计算负数和", "计算正数元素之和", "查找最大值"),
    ("入栈操作", "出栈并输出栈中元素", "判断栈满", "初始化栈"),
)


@dataclass(slots=True)
class OptionRecoveryResult:
    """Recovered canonical option block and audit information."""

    text: str
    options: dict[str, str] = field(default_factory=dict)
    repaired_keys: list[str] = field(default_factory=list)
    source_count: int = 0
    mirror_repairs: int = 0
    warnings: list[str] = field(default_factory=list)


def normalize_mirrored_code(text: str) -> tuple[str, int]:
    """Normalize common horizontally mirrored linked-list expressions.

    PaddleOCR-VL occasionally reads ``s->next`` as ``xau<-s``.  For lines with
    several mirrored pointers, token order is reversed as well.  The repair is
    deliberately narrow and only touches the known ``xau/uax`` signature.
    """
    if not text or not re.search(r"(?:xau|uax)\s*<-|->\s*(?:xau|uax)", text, re.I):
        return text, 0

    repair_count = 0
    out_lines: list[str] = []

    def pointer_sub(match: re.Match[str]) -> str:
        nonlocal repair_count
        repair_count += 1
        return f"{match.group(1)}->next"

    for raw_line in text.splitlines():
        line = raw_line
        # Keep the option label outside of token-order reversal.  The OCR
        # mirror affects the code expression, not the leading ``D.`` marker.
        label_match = re.match(
            r"^(\s*(?:[?？]\s*)?[A-Da-d]\s*[.．、:：)）]\s*)(.*)$",
            line,
        )
        label_prefix = label_match.group(1) if label_match else ""
        expression = label_match.group(2) if label_match else line
        mirror_hits = len(re.findall(r"(?:xau|uax)\s*<-", expression, re.I))
        if mirror_hits >= 2:
            # A fully mirrored code line has its expression order reversed.
            # Treat ':' as a mirrored semicolon and reverse whitespace tokens.
            tokens = re.split(r"(\s+)", expression.replace(":", " ; "))
            words = [tok for tok in tokens if tok and not tok.isspace()]
            words.reverse()
            expression = " ".join(words)

        expression = _POINTER_MIRROR_RE.sub(pointer_sub, expression)
        expression, spaced_count = _POINTER_SPACED_RE.subn(r"\1->next", expression)
        repair_count += spaced_count
        expression = re.sub(r"\s*;\s*", "; ", expression)
        expression = re.sub(r"^\s*=\s*", "", expression)
        expression = re.sub(r"\s*=\s*$", "", expression)
        expression = re.sub(r"\s{2,}", " ", expression).strip()
        line = f"{label_prefix}{expression}".strip()
        out_lines.append(line)

    return "\n".join(out_lines), repair_count


def extract_labeled_options(text: str) -> dict[str, str]:
    """Extract labeled A-D options from line, broad and inline layouts."""
    if not text:
        return {}

    normalized, _ = normalize_mirrored_code(text)
    options: dict[str, str] = {}

    for line in normalized.splitlines():
        stripped = line.strip()
        match = _LABEL_LINE_RE.match(stripped) or _BROAD_LINE_RE.match(stripped)
        if not match:
            continue
        key = match.group(1).upper()
        value = _clean_option_text(match.group(2))
        if key in _OPTION_KEYS and value and key not in options:
            options[key] = value

    inline_matches = list(_INLINE_LABEL_RE.finditer(normalized))
    if len(inline_matches) >= 2:
        for match in inline_matches:
            key = match.group(1).upper()
            value = _clean_option_text(match.group(2))
            if key in _OPTION_KEYS and value and key not in options:
                options[key] = value

    return options


def recover_options_from_sources(
    primary_text: str,
    *reference_texts: str,
    expected_keys: Iterable[str] = _OPTION_KEYS,
) -> OptionRecoveryResult:
    """Merge incomplete options from multiple OCR sources.

    Candidates are selected per key using a deterministic quality score.  Bare
    known option texts and short consecutive list blocks can fill missing keys,
    but only when those strings are present in a supplied source.
    """
    sources = [
        _normalize_option_markup(str(value))
        for value in (primary_text, *reference_texts)
        if str(value or "").strip()
    ]
    expected = tuple(key.upper() for key in expected_keys if key.upper() in _OPTION_KEYS)
    if not sources:
        return OptionRecoveryResult(text=primary_text or "", source_count=0)

    normalized_sources: list[str] = []
    mirror_repairs = 0
    for source in sources:
        normalized, count = normalize_mirrored_code(source)
        normalized_sources.append(normalized)
        mirror_repairs += count

    # Labeled candidates from any source always win over bare candidates; bare
    # recovery only fills keys that have no labeled candidate anywhere, so code
    # fragments in answer text cannot overwrite real labeled options.
    labeled: dict[str, list[tuple[int, int, str]]] = {key: [] for key in expected}
    bare: dict[str, list[tuple[int, int, str]]] = {key: [] for key in expected}
    primary_existing = extract_labeled_options(normalized_sources[0])

    for source_idx, source in enumerate(normalized_sources):
        for key, value in extract_labeled_options(source).items():
            if key in labeled:
                labeled[key].append((_option_quality(value), -source_idx, value))
        for group in _KNOWN_OPTION_GROUPS:
            for idx, literal in enumerate(group):
                key = _OPTION_KEYS[idx]
                if key in labeled and literal in source:
                    labeled[key].append((_option_quality(literal) + 10, -source_idx, literal))
        for key, value in _recover_bare_sequence(source, expected).items():
            if key in bare:
                bare[key].append((_option_quality(value), -source_idx, value))

    options: dict[str, str] = {}
    for key in expected:
        pool = labeled[key] or bare[key]
        if not pool:
            continue
        pool.sort(reverse=True)
        options[key] = pool[0][2]

    repaired_keys = [key for key in options if key not in primary_existing or options[key] != primary_existing.get(key)]
    warnings: list[str] = []
    missing = [key for key in expected if key not in options]
    if missing:
        warnings.append(f"missing_options:{','.join(missing)}")
    if mirror_repairs:
        warnings.append(f"mirror_code_repaired:{mirror_repairs}")

    recovered_text = _render_canonical_text(normalized_sources[0], options, expected)
    return OptionRecoveryResult(
        text=recovered_text,
        options=options,
        repaired_keys=repaired_keys,
        source_count=len(sources),
        mirror_repairs=mirror_repairs,
        warnings=warnings,
    )


def _recover_bare_sequence(text: str, expected: tuple[str, ...]) -> dict[str, str]:
    """Recover a conservative consecutive bare-list option block."""
    lines = [line.strip() for line in text.splitlines()]
    result: dict[str, str] = {}
    runs: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if _is_bare_candidate(line):
            current.append(line)
        else:
            if 2 <= len(current) <= len(expected):
                runs.append(current)
            current = []
    if 2 <= len(current) <= len(expected):
        runs.append(current)

    if not runs:
        return result
    # Prefer the longest run; ties prefer the last one because options normally
    # follow the stem/code block.
    run = sorted(enumerate(runs), key=lambda pair: (len(pair[1]), pair[0]), reverse=True)[0][1]
    for idx, value in enumerate(run):
        if idx < len(expected):
            result[expected[idx]] = _clean_option_text(value)
    return result


def _normalize_option_markup(text: str) -> str:
    """Normalize provider list/LaTeX wrappers without changing option text."""
    if not text:
        return text

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)

    def latex_sub(match: re.Match[str]) -> str:
        return f"{match.group(1).upper()}. {match.group(2).strip()}"

    text = _LATEX_OPTION_RE.sub(latex_sub, text)
    lines = text.splitlines()
    result: list[str] = []
    pending: list[str] = []

    def flush_pending() -> None:
        nonlocal pending
        if 2 <= len(pending) <= 6:
            for index, value in enumerate(pending):
                key = chr(ord("A") + index)
                result.append(f"{key}. {value}")
        else:
            result.extend(pending)
        pending = []

    for raw_line in lines:
        marker = _LIST_MARKER_RE.match(raw_line)
        if marker:
            value = re.sub(r"<[^>]+>", "", marker.group(1)).strip()
            if value:
                pending.append(value)
            continue
        flush_pending()
        result.append(re.sub(r"</?li(?:\s+[^>]*)?>", "", raw_line, flags=re.I))
    flush_pending()
    return "\n".join(result)


def _is_bare_candidate(line: str) -> bool:
    if not line or len(line) > 240:
        return False
    if _LABEL_LINE_RE.match(line) or _BROAD_LINE_RE.match(line):
        return False
    if line in {item for group in _KNOWN_OPTION_GROUPS for item in group}:
        return True
    if re.match(r"^(?:int|char|void|return|if|while|for|typedef|struct|#|//)", line):
        return False
    if line.count(";") >= 2 or "{" in line or "}" in line:
        return False
    # Generic bare recovery is limited to compact code expressions; Chinese
    # prose is too ambiguous unless it matched a known group above.
    if re.search(r"[\u4e00-\u9fff]", line):
        return False
    return bool(re.search(r"(?:->|<-|==|!=|=|\bNULL\b|\btrue\b|\bfalse\b)", line, re.I))


def _clean_option_text(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value.strip("|•◆◇")


def _option_quality(value: str) -> int:
    score = min(len(value), 120)
    if "->" in value:
        score += 30
    if re.search(r"[\u4e00-\u9fff]", value):
        score += 10
    if _GARBLED_RE.search(value):
        score -= 80
    if "<-" in value or re.search(r"(?:xau|uax)", value, re.I):
        score -= 60
    if value.count("?") > 1:
        score -= 30
    return score


def _render_canonical_text(primary: str, options: dict[str, str], expected: tuple[str, ...]) -> str:
    if not options:
        return primary

    lines = primary.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Only drop a labeled line when its key will be re-emitted canonically;
        # keep lines for keys that failed recovery so real content is not lost.
        match = _LABEL_LINE_RE.match(stripped) or _BROAD_LINE_RE.match(stripped)
        if match and match.group(1).upper() in options:
            continue
        # Remove a line containing a complete inline option block only when every
        # inline label key survived recovery.
        inline_matches = list(_INLINE_LABEL_RE.finditer(line))
        if len(inline_matches) >= 2 and all(m.group(1).upper() in options for m in inline_matches):
            prefix = re.split(r"(?<![A-Za-z])[A-Da-d]\s*[.．、:：)）]", line, maxsplit=1)[0].strip()
            if prefix:
                kept.append(prefix)
            continue
        if line.strip() in {item for group in _KNOWN_OPTION_GROUPS for item in group}:
            continue
        kept.append(line.rstrip())

    while kept and not kept[-1].strip():
        kept.pop()
    if kept:
        kept.append("")
    for key in expected:
        value = options.get(key)
        if value:
            kept.append(f"{key}. {value}")
    return "\n".join(kept).strip()
