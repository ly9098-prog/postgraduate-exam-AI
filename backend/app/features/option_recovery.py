"""Deterministic recovery for incomplete OCR option blocks.

This module is intentionally independent from the question classifier so it can
be reused by VL rebuild, OCR correction and regression tests without circular
imports.  It never invents option content: candidates must be present in at
least one OCR source or belong to a known four-item option group observed in
that source.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable

logger = logging.getLogger(__name__)

_OPTION_KEYS = ("A", "B", "C", "D")
_LABEL_LINE_RE = re.compile(r"^\s*(?:[?？]\s*)?([A-Da-d])\s*[.．、:：)）]\s*(.*?)\s*$")
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


# ── Conservative fuzzy known-group recovery ────────────────────────────────
#
# A known option group may arrive OCR-degraded: the leading label is dropped,
# a prefix/suffix is lost, or a char is misread (链→连).  Recovery only fires
# when the whole group scores high enough that the fragments cannot be random
# prose — at least one member must already be recognized in full, every missing
# key must map to a concrete OCR line, and the winning group must beat every
# other known group by a clear margin.  These thresholds were chosen so that a
# lone fragment floating in unrelated text can never synthesize a group.

_OCR_CHAR_EQUIV = str.maketrans("连练", "链链")  # 链/连/练 homophone misreads
_FRAGMENT_SUBSTRING_BASE = 0.6  # substring containment starts at this
_FRAGMENT_SUBSTRING_WEIGHT = 0.4  # …plus coverage * this (max 1.0)
_FRAGMENT_MIN_COVERAGE = 0.4  # a 1-char fragment must never count alone
_FRAGMENT_MIN_SCORE = 0.62  # floor below which a fragment is ignored
_GROUP_FULL_MEMBER_SCORE = 1.0  # a fully-recognized member contributes 1.0
_GROUP_MIN_ANCHORS = 1  # need ≥1 already-recognized member
_GROUP_COMPLETE_SCORE = 1.9  # sum over members; weaker groups are untrusted
_GROUP_MIN_GAP = 0.45  # winner must beat runner-up by this much


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


def _normalize_for_match(text: str) -> str:
    """Collapse OCR noise for matching only — never emitted as option text."""
    t = str(text or "").translate(_OCR_CHAR_EQUIV)
    t = re.sub(r"[\s　]+", "", t)
    t = re.sub(r"[.,;:!?。，；：！？、'\"‘’“”`<>()\[\]{}]", "", t)
    return t.casefold()


def _match_known_option_fragment(fragment: str, canonical: str) -> float:
    """Confidence (0..1) that an OCR line is a degraded form of a canonical.

    Exact match is 1.0; a contiguous substring of the canonical (or vice
    versa) scores by coverage; anything else falls back to SequenceMatcher.
    A 1-char overlap never counts on its own — short fragments must ride on
    stronger group evidence.
    """
    a, b = _normalize_for_match(fragment), _normalize_for_match(canonical)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) >= 2 and a in b:
        coverage = len(a) / len(b)
        if coverage >= _FRAGMENT_MIN_COVERAGE:
            return _FRAGMENT_SUBSTRING_BASE + _FRAGMENT_SUBSTRING_WEIGHT * coverage
    if len(b) >= 2 and b in a:
        coverage = len(b) / len(a)
        if coverage >= _FRAGMENT_MIN_COVERAGE:
            return _FRAGMENT_SUBSTRING_BASE + _FRAGMENT_SUBSTRING_WEIGHT * coverage
    return SequenceMatcher(None, a, b).ratio()


def _collect_fragment_lines(sources: list[str]) -> list[str]:
    """Non-labeled OCR lines that could be degraded option fragments.

    Kept deliberately permissive — safety comes from whole-group scoring, not
    from pre-filtering every line.  Labeled lines are excluded because labeled
    extraction already owns them.
    """
    fragments: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped or len(stripped) > 240:
                continue
            if _LABEL_LINE_RE.match(stripped) or _BROAD_LINE_RE.match(stripped):
                continue
            if stripped in seen:
                continue
            seen.add(stripped)
            fragments.append(stripped)
    return fragments


def _score_known_group(
    group: tuple[str, str, str, str],
    options: dict[str, str],
    expected: tuple[str, ...],
    fragments: list[str],
) -> tuple[float, dict[str, str], dict[str, str]]:
    """Score one known group against the recovered options + OCR fragments.

    Returns (score, recovered, sources) where ``recovered`` maps every *missing*
    key to the group's canonical literal, and ``sources`` maps that key to the
    concrete OCR line that justified it (each recovered value must have one).
    """
    group_keys = _OPTION_KEYS[: len(group)]
    if len(group_keys) < len(expected):
        return 0.0, {}, {}
    score = 0.0
    anchors = 0
    recovered: dict[str, str] = {}
    sources: dict[str, str] = {}
    for key, literal in zip(group_keys, group):
        if key not in expected:
            continue
        existing = options.get(key)
        if existing is not None:
            if _normalize_for_match(existing) == _normalize_for_match(literal):
                score += _GROUP_FULL_MEMBER_SCORE
                anchors += 1
            continue
        best = 0.0
        best_line = ""
        for line in fragments:
            candidate = _match_known_option_fragment(line, literal)
            if candidate > best:
                best, best_line = candidate, line
        if best >= _FRAGMENT_MIN_SCORE:
            score += best
            recovered[key] = literal
            sources[key] = best_line
    if anchors < _GROUP_MIN_ANCHORS or not recovered:
        return 0.0, {}, {}
    return score, recovered, sources


def _recover_known_group_fragments(
    sources: list[str],
    options: dict[str, str],
    expected: tuple[str, ...],
) -> tuple[dict[str, str], set[str]]:
    """Fill missing option keys from a known option group using conservative
    fuzzy evidence (see the module comment for the safety model).

    Returns (recovered, consumed_lines): consumed_lines are the OCR source
    lines that justified the recovery, so they can be dropped from the rendered
    option block instead of being duplicated next to the canonical options.
    """
    missing = [key for key in expected if key not in options]
    if not missing:
        return {}, set()
    fragments = _collect_fragment_lines(sources)
    if not fragments:
        return {}, set()
    missing_set = set(missing)

    scored: list[tuple[float, dict[str, str], dict[str, str]]] = []
    for group in _KNOWN_OPTION_GROUPS:
        score, recovered, sources_map = _score_known_group(
            group, options, expected, fragments
        )
        if score > 0 and set(recovered) == missing_set:
            scored.append((score, recovered, sources_map))

    if not scored:
        return {}, set()
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best_recovered, best_sources = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if best_score < _GROUP_COMPLETE_SCORE or (best_score - runner_up) < _GROUP_MIN_GAP:
        return {}, set()
    logger.debug(
        "known-group fragment recovery: %s (score=%.2f, gap=%.2f)",
        best_recovered,
        best_score,
        best_score - runner_up,
    )
    return best_recovered, set(best_sources.values())


def _leading_bare_in_source(
    source: str,
    options: dict[str, str],
    expected: tuple[str, ...],
) -> tuple[dict[str, str], set[str]]:
    """Recover ``A`` from a single code line sitting immediately before ``B.``.

    Guards are intentionally strict — only fires when B is the first labeled
    option, the following labels are an ordered contiguous run, the predecessor
    line is a code-shaped bare line (no Chinese prose), and A is actually
    missing — so stems, headers, page footers and code blocks cannot be
    swallowed into the option block.

    Returns (recovered, consumed_lines); the bare line is consumed so it is
    dropped from the rendered block instead of duplicating the canonical ``A.``.
    """
    lines = [ln.strip() for ln in source.splitlines()]
    first_idx: int | None = None
    first_key: str | None = None
    for i, line in enumerate(lines):
        if not line:
            continue
        m = _LABEL_LINE_RE.match(line) or _BROAD_LINE_RE.match(line)
        if m and m.group(1).upper() in expected:
            first_idx, first_key = i, m.group(1).upper()
            break
    if first_key != "B":
        return {}, set()
    if "A" not in expected or "A" in options:
        return {}, set()

    keys_after: list[str] = []
    for line in lines[first_idx + 1 :]:
        if not line.strip():
            continue
        m = _LABEL_LINE_RE.match(line.strip()) or _BROAD_LINE_RE.match(line.strip())
        if m and m.group(1).upper() in expected:
            keys_after.append(m.group(1).upper())
    if keys_after != [chr(ord("B") + n) for n in range(1, len(keys_after) + 1)]:
        return {}, set()

    prev_idx = first_idx - 1
    while prev_idx >= 0 and (
        not lines[prev_idx]
        or re.fullmatch(r"[\s<>*·◇\d'\"`‘’“”|:;,.\-—]+", lines[prev_idx])
    ):
        prev_idx -= 1
    if prev_idx < 0:
        return {}, set()
    bare = lines[prev_idx]
    if not _is_bare_candidate(bare):
        return {}, set()
    cleaned = re.sub(r"^[\s'\"`‘’“”]+", "", bare).strip()
    cleaned = _clean_option_text(cleaned)
    if not cleaned:
        return {}, set()
    logger.debug("leading bare option recovered as A: %r", cleaned)
    return {"A": cleaned}, {bare}


def _recover_single_leading_bare_option(
    sources: list[str],
    options: dict[str, str],
    expected: tuple[str, ...],
) -> tuple[dict[str, str], set[str]]:
    """Recover the missing leading option from a lone bare code line.

    Handles images where OCR drops the leading label (typically ``A.``) but
    keeps the option's code intact::

        <bare code line>
        B. ...
        C. ...
        D. ...
    """
    for source in sources:
        recovered, consumed = _leading_bare_in_source(source, options, expected)
        if recovered:
            return recovered, consumed
    return {}, set()


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
    expected = tuple(
        key.upper() for key in expected_keys if key.upper() in _OPTION_KEYS
    )
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
                    labeled[key].append(
                        (_option_quality(literal) + 10, -source_idx, literal)
                    )
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

    # Fuzzy known-group recovery runs before the leading-bare rule so a
    # group-grounded option never competes with a guessed A.
    consumed_lines: set[str] = set()
    if any(key not in options for key in expected):
        group_recovered, group_consumed = _recover_known_group_fragments(
            normalized_sources,
            options,
            expected,
        )
        consumed_lines |= group_consumed
        for key, value in group_recovered.items():
            if key not in options:
                options[key] = value
    else:
        group_recovered = {}

    # Single leading bare code line before the first labeled option → A.
    if "A" not in options:
        leading_recovered, leading_consumed = _recover_single_leading_bare_option(
            normalized_sources,
            options,
            expected,
        )
        consumed_lines |= leading_consumed
        for key, value in leading_recovered.items():
            if key not in options:
                options[key] = value
    else:
        leading_recovered = {}

    repaired_keys = [
        key
        for key in options
        if key not in primary_existing or options[key] != primary_existing.get(key)
    ]
    warnings: list[str] = []
    missing = [key for key in expected if key not in options]
    if missing:
        warnings.append(f"missing_options:{','.join(missing)}")
    if group_recovered:
        warnings.append(
            f"known_group_fragment_recovered:{','.join(sorted(group_recovered))}"
        )
    if leading_recovered:
        warnings.append(f"leading_bare_recovered:{','.join(sorted(leading_recovered))}")
    if mirror_repairs:
        warnings.append(f"mirror_code_repaired:{mirror_repairs}")

    recovered_text = _render_canonical_text(
        normalized_sources[0],
        options,
        expected,
        drop_lines=consumed_lines,
    )
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
    run = sorted(
        enumerate(runs), key=lambda pair: (len(pair[1]), pair[0]), reverse=True
    )[0][1]
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


def _render_canonical_text(
    primary: str,
    options: dict[str, str],
    expected: tuple[str, ...],
    *,
    drop_lines: set[str] | None = None,
) -> str:
    if not options:
        return primary

    drop = drop_lines or set()
    lines = primary.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Drop a line that was consumed as the OCR source for a recovery so it
        # is not duplicated next to the canonical option re-emitted below.
        if stripped in drop:
            continue
        # Only drop a labeled line when its key will be re-emitted canonically;
        # keep lines for keys that failed recovery so real content is not lost.
        match = _LABEL_LINE_RE.match(stripped) or _BROAD_LINE_RE.match(stripped)
        if match and match.group(1).upper() in options:
            continue
        # Remove a line containing a complete inline option block only when every
        # inline label key survived recovery.
        inline_matches = list(_INLINE_LABEL_RE.finditer(line))
        if len(inline_matches) >= 2 and all(
            m.group(1).upper() in options for m in inline_matches
        ):
            prefix = re.split(
                r"(?<![A-Za-z])[A-Da-d]\s*[.．、:：)）]", line, maxsplit=1
            )[0].strip()
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
