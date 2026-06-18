"""Shared Roman numeral constants, schemas, and candidate-fix generation.

Single source of truth for Roman numeral handling across the OCR pipeline.
Replaces duplicated constants in text_normalizer.py, batch_validation.py,
and question_splitter.py.
"""

import re

# ---------------------------------------------------------------------------
# Constants (single source of truth)
# ---------------------------------------------------------------------------

_ROMAN_SUBITEM_TOKEN = r"(?:VIII|VII|III|VI|IV|IX|II|V|X|I)"

_RE_ROMAN_SUBITEM_MARKER = re.compile(
    r"(?<![A-Za-z])" + _ROMAN_SUBITEM_TOKEN + r"(?![A-Za-z])\s*[.、)）]"
)

_ROMAN_TO_VALUE: dict[str, int] = {
    "VIII": 8, "VII": 7, "III": 3, "VI": 6, "IV": 4, "IX": 9,
    "II": 2, "V": 5, "X": 10, "I": 1,
}

_VALUE_TO_ROMAN: dict[int, str] = {v: k for k, v in _ROMAN_TO_VALUE.items()}

# ---------------------------------------------------------------------------
# Anomaly type constants
# ---------------------------------------------------------------------------

DUPLICATE = "duplicate"              # I,II,II,IV → position 2 should be III
GAP = "gap"                           # I,II,IV → missing III
OCR_DIGIT_CONFUSION = "ocr_digit_confusion"  # "1、" where "I、" belongs
SEQUENCE_BREAK = "sequence_break"     # non-monotonic, not a simple dup/gap

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def has_roman_subitem_list(text: str) -> bool:
    """Check if text contains >=2 distinct Roman numeral markers (I./II./…)."""
    if not text:
        return False
    markers = _RE_ROMAN_SUBITEM_MARKER.findall(text)
    if len(markers) < 2:
        return False
    distinct = {
        re.match(_ROMAN_SUBITEM_TOKEN, m).group(0)  # type: ignore[union-attr]
        for m in markers
        if re.match(_ROMAN_SUBITEM_TOKEN, m)
    }
    return len(distinct) >= 2


def classify_roman_issue(tokens: list[str], values: list[int]) -> str:
    """Classify the type of Roman numeral anomaly from token/value sequences.

    Returns one of: DUPLICATE, GAP, SEQUENCE_BREAK.
    Returns empty string if the sequence is valid (monotonic +1).
    """
    if len(values) < 2:
        return ""

    # Check for duplicates
    for j in range(1, len(values)):
        if values[j] == values[j - 1]:
            return DUPLICATE

    # Check for gaps
    for j in range(1, len(values)):
        if values[j] - values[j - 1] != 1:
            return GAP

    return ""


# ---------------------------------------------------------------------------
# Candidate generators (rule-based, no AI)
# ---------------------------------------------------------------------------


def generate_duplicate_candidates(
    tokens: list[str], values: list[int]
) -> list[dict]:
    """Generate flat candidate fixes for duplicate Roman numeral sequences.

    Each candidate is a self-contained fix choice that AI can select by index.
    Example: tokens=["I","II","II","IV","V"], values=[1,2,2,4,5]

    Returns a flat list where each item is one concrete fix action.
    """
    candidates: list[dict] = []
    for j in range(1, len(values)):
        if values[j] == values[j - 1]:
            expected = values[j - 1] + 1
            new_token = _VALUE_TO_ROMAN.get(expected)
            if new_token:
                candidates.append({
                    "position": j,
                    "current_token": tokens[j],
                    "action": "replace_token",
                    "token": new_token,
                    "rationale": f"递增序列，{tokens[j-1]}后应为{new_token}",
                })
                candidates.append({
                    "position": j,
                    "current_token": tokens[j],
                    "action": "keep_as_is",
                    "rationale": "保留不变（若重复是有意的）",
                })
    return candidates


def generate_gap_candidates(
    tokens: list[str], values: list[int]
) -> list[dict]:
    """Generate flat candidate fixes for gap (missing item) in Roman numeral sequence.

    Each candidate is a self-contained fix choice that AI can select by index.
    Example: tokens=["I","II","IV","V"], values=[1,2,4,5]

    Returns a flat list where each item is one concrete fix action.
    """
    candidates: list[dict] = []
    for j in range(1, len(values)):
        diff = values[j] - values[j - 1]
        if diff > 1:
            missing_values = list(range(values[j - 1] + 1, values[j]))
            missing_tokens = [_VALUE_TO_ROMAN.get(v) for v in missing_values]
            missing_tokens = [t for t in missing_tokens if t]
            prev_token = tokens[j - 1]
            current_token = tokens[j]

            # Candidate: insert missing tokens (gap is real)
            candidates.append({
                "position": j,
                "current_token": current_token,
                "action": "insert_token",
                "token": missing_tokens[0] if missing_tokens else "",
                "rationale": f"缺少 {', '.join(missing_tokens)}，应在 {prev_token} 和 {current_token} 之间插入",
            })

            # Candidate: renumber subsequent (gap is OCR error on subsequent)
            if missing_tokens:
                candidates.append({
                    "position": j,
                    "current_token": current_token,
                    "action": "replace_token_at_position",
                    "token": missing_tokens[0],
                    "rationale": f"{current_token} 可能是 {missing_tokens[0]} 的 OCR 识别错误，修正当前位置",
                })

            # Candidate: keep as-is
            candidates.append({
                "position": j,
                "current_token": current_token,
                "action": "keep_as_is",
                "rationale": "保留不变（若跳号是有意的）",
            })
        elif diff < 1 and diff != 0:
            # Sequence break (reverse or non-monotonic)
            candidates.append({
                "position": j,
                "current_token": tokens[j],
                "action": "keep_as_is",
                "rationale": "保留不变（无法推断正确序列）",
            })

    return candidates


def generate_digit_confusion_candidates(
    option_key: str, option_text: str
) -> list[dict]:
    """Generate flat candidate fixes for digit 1 vs Roman I confusion in option text.

    Each candidate is a self-contained fix choice that AI can select by index.
    Example: option_key="A", option_text="1、II"
    """
    return [
        {
            "option_key": option_key,
            "option_text": option_text,
            "action": "replace_1_with_I",
            "rationale": "罗马数字上下文中，1 应为 I（OCR 混淆）",
        },
        {
            "option_key": option_key,
            "option_text": option_text,
            "action": "keep_as_is",
            "rationale": "保留不变（若数字 1 是正确的）",
        },
    ]


# ---------------------------------------------------------------------------
# Schema builder
# ---------------------------------------------------------------------------


def build_roman_anomaly(
    index: int,
    source: str,
    issue_type: str,
    tokens: list[str],
    values: list[int],
    text_snippet: str = "",
    candidates: list[dict] | None = None,
) -> dict:
    """Build a structured Roman numeral anomaly record."""
    anomaly: dict = {
        "index": index,
        "source": source,
        "issue_type": issue_type,
        "found_tokens": tokens,
        "found_values": values,
    }
    if text_snippet:
        anomaly["text_snippet"] = text_snippet
    if candidates:
        anomaly["candidates"] = candidates
    return anomaly


# ---------------------------------------------------------------------------
# Fix applicator (mechanical, no AI)
# ---------------------------------------------------------------------------


def apply_roman_fix(question: dict, decision: dict) -> dict:
    """Apply a Roman numeral fix decision to a question dict.

    The decision is what the AI chose from candidates.
    This function mechanically applies text substitutions.

    Supported decision shapes:
      - {"action": "replace_token", "source": "stem", "position": 2,
         "from_token": "II", "to_token": "III"}
      - {"action": "replace_1_with_I", "source": "option_A",
         "original_fragment": "1、II", "fixed_fragment": "I、II"}
      - {"action": "insert_token", "source": "stem", "after_position": 1,
         "token": "III"}
      - {"action": "keep_as_is"}

    Returns a shallow copy of question with fixes applied.
    """
    import copy
    q = copy.copy(question)
    action = decision.get("action", "")

    if action == "keep_as_is":
        return q

    source = decision.get("source", "")

    if action == "replace_token":
        return _apply_replace_token(q, source, decision)

    if action == "replace_1_with_I":
        return _apply_digit_fix(q, source, decision)

    if action == "insert_token":
        return _apply_insert_token(q, source, decision)

    return q


def _apply_replace_token(question: dict, source: str, decision: dict) -> dict:
    """Replace a Roman numeral token at a specific position in stem or option text."""
    from_token = decision.get("from_token", "")
    to_token = decision.get("to_token", "")
    position = decision.get("position")

    if not from_token or not to_token or position is None:
        return question

    q = dict(question)

    if source == "stem":
        text = q.get("stem", "")
        q["stem"] = _replace_nth_roman_token(text, from_token, to_token, position)
    elif source.startswith("option_"):
        opt_key = source.split("_", 1)[1].upper()
        options = q.get("options", [])
        new_options = []
        for opt in options:
            if isinstance(opt, dict) and opt.get("key", "").upper() == opt_key:
                new_opt = dict(opt)
                new_opt["text"] = _replace_nth_roman_token(
                    opt.get("text", ""), from_token, to_token, position
                )
                new_options.append(new_opt)
            else:
                new_options.append(opt)
        q["options"] = new_options

    return q


def _replace_nth_roman_token(
    text: str, from_token: str, to_token: str, nth: int
) -> str:
    """Replace the nth occurrence of a Roman token in text.

    nth is 0-indexed: 0 = first occurrence, 1 = second, etc.
    If nth exceeds available occurrences, replaces the last one found.
    """
    pattern = re.compile(
        r"(?<![A-Za-z])" + re.escape(from_token) + r"(?![A-Za-z])"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return text

    # Clamp nth to available range
    target_idx = min(nth, len(matches) - 1)
    m = matches[target_idx]

    return text[: m.start()] + to_token + text[m.end():]


def _apply_digit_fix(question: dict, source: str, decision: dict) -> dict:
    """Fix digit 1 → I confusion in option text."""
    original = decision.get("original_fragment", "")
    fixed = decision.get("fixed_fragment", "")

    if not original or not fixed or not source.startswith("option_"):
        return question

    opt_key = source.split("_", 1)[1].upper()
    q = dict(question)
    options = q.get("options", [])
    new_options = []
    for opt in options:
        if isinstance(opt, dict) and opt.get("key", "").upper() == opt_key:
            new_opt = dict(opt)
            new_opt["text"] = opt.get("text", "").replace(original, fixed, 1)
            new_options.append(new_opt)
        else:
            new_options.append(opt)
    q["options"] = new_options
    return q


def _apply_insert_token(question: dict, source: str, decision: dict) -> dict:
    """Insert a missing Roman numeral token into the stem enumeration lines."""
    token = decision.get("token", "")
    after_position = decision.get("after_position")

    if not token or after_position is None:
        return question

    q = dict(question)

    if source == "stem":
        text = q.get("stem", "")
        lines = text.split("\n")
        # Find the line with the marker at after_position, then insert after it
        marker_count = 0
        insert_idx = -1
        for i, line in enumerate(lines):
            if _RE_ROMAN_SUBITEM_MARKER.match(line.lstrip()):
                if marker_count == after_position:
                    insert_idx = i + 1
                    break
                marker_count += 1

        if insert_idx >= 0:
            # Determine indentation from surrounding lines
            indent = ""
            for line in lines:
                m = _RE_ROMAN_SUBITEM_MARKER.match(line.lstrip())
                if m:
                    indent = line[: line.index(m.group(0))]
                    break
            new_line = f"{indent}{token}. "
            lines.insert(insert_idx, new_line)
            q["stem"] = "\n".join(lines)

    return q
