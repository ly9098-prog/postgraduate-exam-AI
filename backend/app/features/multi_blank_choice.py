"""Multi-blank choice utilities — single source of truth for shared-option multi-blank questions.

A "multi-blank choice" (多空选择题) is a question with multiple blank slots in the stem,
each blank having its own set of options (or sharing one set), and each blank has a
separate answer. This module provides parsing, serialization, validation, and detection.

Data contract (also summarized in docs/backend/DB_SCHEMA.md):

    question_type = "multi_blank_choice"
    content.text = stem with blank slots
    content.blank_option_groups = [
        {"id": "①", "options": [{"key": "A", "text": "..."}, ...]},
        {"id": "②", "options": [{"key": "A", "text": "..."}, ...]},
    ]
    options = None
    answer = "①:B;②:D"  (canonical: slot:value; separated by ;)
"""

from __future__ import annotations

import re

# ── Slot ID extraction ───────────────────────────────────────────

# Common blank markers in stem text
_BLANK_PAREN_RE = re.compile(r"[（(]\s*[）)]")
_NUMBERED_BLANK_RE = re.compile(r"[（(]\s*(\d+)\s*[）)]")
_CIRCLED_BLANK_RE = re.compile(r"[（(]\s*([①-⑳])\s*[）)]")
_CIRCLED_NUM_RE = re.compile(r"[①-⑳]")
_UNDERSCORE_BLANK_RE = re.compile(r"_{3,}")

# Answer letter domain (single letter per capture; multi-letter slots are joined
# with "," — e.g. "①:A,C" — so a value group never spans pair separators).
# A separator between letters counts as an intra-value separator only when the
# next non-space char is another letter; a separator before a slot marker
# (circled digit / digit / （N）) is a pair separator.
_ANSWER_LETTER = r"[A-Ha-h]"
_ANSWER_LETTERS_ONE_OR_MORE = r"[A-Ha-h]+(?:\s*[，,、]\s*(?=[A-Ha-h])\s*[A-Ha-h]+)*"
# Value group used with explicit slot:value pairs; a following "letters:colon"
# run means the separator starts the next pair (e.g. "1:B,2:D").
_ANSWER_LETTERS_PAIR = (
    r"[A-Ha-h]+(?:\s*[，,、]\s*(?=\s*[A-Ha-h])(?!\s*[A-Ha-h]+\s*[:：])\s*[A-Ha-h]+)*"
)

# Answer patterns (in priority order)
_RE_CANONICAL = re.compile(
    r"([^:：;；]+?)\s*[:：]\s*(" + _ANSWER_LETTERS_PAIR + r")\s*(?:[;；]|$)"
)
_RE_CIRCLED_ANSWER = re.compile(r"([①-⑳])\s*(" + _ANSWER_LETTERS_ONE_OR_MORE + ")")
_RE_PAREN_ANSWER = re.compile(
    r"[（(]\s*(\d+)\s*[）)]\s*(" + _ANSWER_LETTERS_ONE_OR_MORE + ")"
)
_RE_DIGIT_SLOT_ANSWER = re.compile(
    r"(?:^|\s|第)(\d+)\s*(?:空|个|题)?\s*[：:是为]?\s*("
    + _ANSWER_LETTERS_ONE_OR_MORE
    + r")(?:[;；]|$)"
)
_RE_CHINESE_SLOT_PREFIX = re.compile(
    r"第\s*([一二三四五六七八九十\d]+)\s*空\s*[：:]?\s*("
    + _ANSWER_LETTERS_ONE_OR_MORE
    + r")"
)


def extract_blank_slots(stem: str) -> list[str]:
    """Extract blank slot IDs from stem text.

    Detects patterns in order:
    - Named circled digits: ①（ ）, ②（ ） → ["①", "②"]
    - Numbered parentheses: (1)（ ）, (2)（ ） → ["1", "2"]
    - Anonymous parentheses: （ ）（ ） → ["1", "2"]
    - Underscores: ____, ___

    Returns:
        List of slot IDs. For anonymous blanks, generates "1", "2", etc.
    """
    if not stem:
        return []

    slots: list[str] = []

    # Priority 1: Named circled markers (① ② etc.) with explicit parentheses
    circled_with_paren = list(_CIRCLED_BLANK_RE.finditer(stem))
    if circled_with_paren:
        slots = [m.group(1) for m in circled_with_paren]
        return slots

    # Priority 2: Standalone circled numbers (① ②) without explicit ( ) around them
    standalone_circled = list(_CIRCLED_NUM_RE.finditer(stem))
    if standalone_circled:
        slots = [m.group(0) for m in standalone_circled]
        return slots

    # Priority 3: Numbered parentheses like (1) (2)
    numbered = list(_NUMBERED_BLANK_RE.finditer(stem))
    if numbered:
        slots = [m.group(1) for m in numbered]
        return slots

    # Priority 4: Anonymous parentheses （ ）, count them
    anonymous = list(_BLANK_PAREN_RE.finditer(stem))
    if anonymous:
        slots = [str(i + 1) for i in range(len(anonymous))]
        return slots

    # Priority 5: Underscore blanks
    underscores = list(_UNDERSCORE_BLANK_RE.finditer(stem))
    if underscores:
        slots = [str(i + 1) for i in range(len(underscores))]
        return slots

    return slots


def normalize_answer_value(raw_value: str) -> str:
    """Normalize a slot value to canonical form.

    Single letter → "A". Multi letters (comma/顿号 separated or run together,
    e.g. "A,C" / "A、C" / "AC") → canonical comma-joined "A,C" (deduplicated,
    option order preserved as entered order sorted by letter).
    """
    letters = re.findall(r"[A-Ha-h]", raw_value)
    if not letters:
        return ""
    upper_sorted = sorted({ch.upper() for ch in letters})
    return ",".join(upper_sorted)


# ── Answer parsing ───────────────────────────────────────────────


def parse_multi_blank_answer(
    answer: str | list | dict | None,
    slot_ids: list[str] | None = None,
    allow_positional: bool = True,
) -> tuple[dict[str, str], list[str]]:
    """Parse a multi-blank answer string into a slot→value mapping.

    Compatible formats:
        "①:B;②:D"        — canonical
        "①:B;②:A,C"      — canonical, multi-letter slot (multi-select blank)
        "①B、②D"          — Chinese comma
        "① AC、② D"       — multi letters in one slot
        "① B，② D"        — with spaces
        "(1)B、(2)D"      — parenthesized digits
        "1:B,2:D"         — digit slots
        "第1空B，第2空D"  — Chinese natural language
        "A,B"             — positional (requires slot_ids and allow_positional)
        "B,D"             — positional
        {"①": "B", "②": "D"} — dict input

    Returns:
        (slot_map, errors) where slot_map is {slot_id: value_letter}
        and errors is a list of error messages (empty on success).
        Values outside A-H produce "invalid_value_for_slot_<slot>" errors.

    Rules:
        - Answer letters are uppercased; multi-letter slots are canonicalized
          to comma-joined sorted letters (e.g. "C,A" → "A,C").
        - Duplicate slot IDs are deduplicated (last wins with a warning).
        - Unknown slot IDs are not included but produce warnings.
        - Positional "A,B" only accepted when slot_ids is provided,
          answer count matches slot count, and allow_positional=True.
    """
    errors: list[str] = []

    if answer is None:
        return {}, errors

    # Handle dict input
    if isinstance(answer, dict):
        result: dict[str, str] = {}
        for k, v in answer.items():
            key = str(k).strip()
            val = normalize_answer_value(str(v))
            if val:
                result[key] = val
            else:
                errors.append(f"invalid_value_for_slot_{key}: {v}")
        return result, errors

    # Handle list input
    if isinstance(answer, list):
        items = [str(item).strip().upper() for item in answer if str(item).strip()]
        if not items:
            return {}, errors
        if (
            slot_ids
            and len(items) == len(slot_ids)
            and all(re.match(r"^[A-H](?:,[A-H])*$", i) for i in items)
        ):
            return dict(zip(slot_ids, items)), errors
        # Single element? Try parsing it as string
        if len(items) == 1:
            answer = items[0]
        else:
            errors.append(f"list_answer_without_matching_slot_ids: {items}")
            return {}, errors

    text = str(answer).strip()
    if not text:
        return {}, errors

    result: dict[str, str] = {}

    def _add_pair(slot: str, raw_val: str) -> None:
        slot = slot.strip()
        val = normalize_answer_value(raw_val)
        if slot and val:
            result[slot] = val
        elif slot and raw_val.strip():
            # Letters outside A-H (e.g. "①:X") — emit an invalid-value error
            # instead of failing the whole answer as unparseable.
            errors.append(f"invalid_value_for_slot_{slot}: {raw_val.strip()}")

    # -- Strategy 1: Canonical "slot:value; slot:value" OR "slot:value,slot:value" --
    # Split by semicolons or commas that appear between "letter" and "digit/circled" boundaries
    # Use a regex that handles both semicolons and commas as pair separators
    #
    # Match: "slot:value" pairs — slot is any non-empty text up to :, value is
    # one or more letters (comma/顿号 separated allowed within a value)
    # Pairs can be separated by ; or ,
    all_pairs = list(
        re.finditer(
            r"([^:：;；]+?)\s*[:：]\s*([A-Za-z][A-Za-z\s，,、]*)\s*(?:[;；]|$)",
            text,
        )
    )
    if len(all_pairs) >= 2:
        for m in all_pairs:
            _add_pair(m.group(1), m.group(2))
        if result:
            return result, errors

    # Single canonical pair with more than one colon/equals - try broader match
    if ":" in text or "：" in text:
        for m in re.finditer(r"(.+?)\s*[:：]\s*([A-Za-z][A-Za-z\s，,、]*)\s*", text):
            _add_pair(m.group(1), m.group(2))
        if result:
            result.pop("", None)
            # If we got only 1 result but text clearly has multiple slots separated
            # by comma, try comma-split per pair
            if len(result) == 1 and ("," in text or "，" in text):
                parts = re.split(r"[，,]", text)
                for part in parts:
                    m2 = re.match(
                        r"(.+?)\s*[:：]\s*([A-Za-z][A-Za-z\s，,、]*)\s*",
                        part.strip(),
                    )
                    if m2:
                        _add_pair(m2.group(1), m2.group(2))
                result.pop("", None)
            if result:
                return result, errors

    # -- Strategy 2: Circled answer "①B、②D" / "①AC、②D" --
    circled_matches = list(_RE_CIRCLED_ANSWER.finditer(text))
    if len(circled_matches) >= 2:
        for m in circled_matches:
            _add_pair(m.group(1), m.group(2))
        return result, errors

    # -- Strategy 3: Parenthesized digits "(1)B、(2)D" --
    paren_matches = list(_RE_PAREN_ANSWER.finditer(text))
    if len(paren_matches) >= 2:
        for m in paren_matches:
            _add_pair(m.group(1), m.group(2))
        return result, errors

    # -- Strategy 4: Chinese slot prefix "第1空B，第2空D" --
    chinese_matches = list(_RE_CHINESE_SLOT_PREFIX.finditer(text))
    if len(chinese_matches) >= 2:
        for m in chinese_matches:
            cn_digit = m.group(1)
            slot = str(_CN_TO_INT.get(cn_digit, cn_digit))
            _add_pair(slot, m.group(2))
        return result, errors

    # -- Strategy 5: Digit slot "第1空B，第2空D" (loose) --
    digit_matches = list(_RE_DIGIT_SLOT_ANSWER.finditer(text))
    if len(digit_matches) >= 2:
        for m in digit_matches:
            _add_pair(m.group(1), m.group(2))
        return result, errors

    # -- Strategy 7: Positional "A,B" or "B,D" --
    # Only when allow_positional is true AND no colon-based patterns were present
    if allow_positional and slot_ids and ":" not in text and "：" not in text:
        # Try comma-separated letters
        parts = [p.strip().upper() for p in re.split(r"[，,、\s]+", text) if p.strip()]
        letters = [p for p in parts if re.match(r"^[A-H]$", p)]
        if len(letters) >= 2 and len(letters) == len(slot_ids):
            return dict(zip(slot_ids, letters)), errors
        # Single letter with count check
        if len(letters) == 1 and len(slot_ids) == 1:
            return dict(zip(slot_ids, letters)), errors

    # -- Strategy 8: Try single circled "①B" or "(1)B" pattern --
    single_circled = _RE_CIRCLED_ANSWER.match(text)
    if single_circled:
        _add_pair(single_circled.group(1), single_circled.group(2))
        return result, errors

    single_paren = _RE_PAREN_ANSWER.match(text)
    if single_paren:
        _add_pair(single_paren.group(1), single_paren.group(2))
        return result, errors

    # -- Strategy 9: Just letters — "AB" or "A" or "AC,BD" —
    # "AC,BD" style: comma-separated letter groups, one per slot (positional).
    # A single run like "BD" is positional when each letter maps to one slot.
    letter_groups = [
        normalize_answer_value(p)
        for p in re.split(r"[，,、\s]+", text)
        if p and re.fullmatch(r"[A-Ha-h]+", p)
    ]
    if slot_ids and allow_positional and ":" not in text and "：" not in text:
        if len(letter_groups) == len(slot_ids) and all(letter_groups):
            return dict(zip(slot_ids, letter_groups)), errors
        # Contiguous run "BD" with N slots → one letter per slot
        single_run = re.fullmatch(r"[A-Ha-h]+", text.strip())
        if single_run and len(text.strip()) == len(slot_ids):
            return (
                dict(
                    zip(
                        slot_ids,
                        [ch.upper() for ch in text.strip().upper()],
                    )
                ),
                errors,
            )

    errors.append(f"unparseable_answer: {text}")
    return {}, errors


_CN_TO_INT: dict[str, str] = {
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
    "十": "10",
}


# ── Serialization ────────────────────────────────────────────────


def serialize_multi_blank_answer(
    answer_map: dict[str, str],
    slot_ids: list[str],
) -> str:
    """Serialize a slot→value mapping to canonical format.

    Format: "slot1:value1;slot2:value2"

    Args:
        answer_map: {slot_id: value_letter}
        slot_ids: Ordered list of slot IDs determining serialization order.

    Returns:
        Canonical string, or empty string if answer_map is empty.

    Only slots present in slot_ids are serialized, in the given order.
    """
    if not answer_map or not slot_ids:
        return ""

    parts: list[str] = []
    for sid in slot_ids:
        val = answer_map.get(sid)
        if val:
            canonical = normalize_answer_value(str(val))
            if canonical:
                parts.append(f"{sid}:{canonical}")
    return ";".join(parts)


# ── Build blank option groups ────────────────────────────────────


def build_blank_option_groups(
    slot_ids: list[str],
    shared_options: list[dict] | dict,
) -> list[dict]:
    """Build blank_option_groups from shared options for each slot.

    Args:
        slot_ids: Ordered list of slot IDs (e.g. ["①", "②"]).
        shared_options: Either:
            - list[dict]: [{"key": "A", "text": "..."}, ...]
            - dict: {"A": "text", "B": "text", ...}

    Returns:
        list[dict]: [{"id": "①", "options": [{"key": "A", ...}, ...]}, ...]
    """
    if not slot_ids:
        return []

    # Normalize shared_options to list[dict]
    if isinstance(shared_options, dict):
        opts = sorted(
            [{"key": k.upper(), "text": str(v)} for k, v in shared_options.items()],
            key=lambda x: x["key"],
        )
    elif isinstance(shared_options, list):
        opts = []
        for item in shared_options:
            if isinstance(item, dict):
                key = (item.get("key") or "").upper()
                text = item.get("text") or ""
                if key and text:
                    opts.append({"key": key, "text": text})
        opts.sort(key=lambda x: x["key"])
    else:
        opts = []

    if not opts or len(opts) < 2:
        return []

    return [{"id": sid, "options": [dict(o) for o in opts]} for sid in slot_ids]


# ── Validation ───────────────────────────────────────────────────


def _group_option_keys(groups: list[dict], slot_id: str) -> set[str]:
    """Return the option keys of the group with the given slot id."""
    for group in groups:
        if str(group.get("id") or "").strip() == slot_id:
            return {
                str(o.get("key") or "").upper() for o in (group.get("options") or [])
            }
    return set()


def validate_multi_blank_question(
    groups: list[dict],
    answer: str | dict | None,
) -> tuple[bool, list[str]]:
    """Validate a multi_blank_choice question before publishing.

    Args:
        groups: blank_option_groups list
        answer: Canonical answer string or slot→value dict

    Returns:
        (is_valid, errors)

    Validation rules:
        - At least 2 blank groups
        - Each group has a non-empty, unique id
        - Each group has at least 2 options
        - Each group's option keys are unique
        - Answer covers all group ids (no missing slots)
        - No extra answer slots beyond groups
        - Each answer value exists in the corresponding group's options
    """
    errors: list[str] = []

    if not groups:
        errors.append("missing_blank_option_groups")
        return False, errors

    if len(groups) < 2:
        errors.append("multi_blank_choice_requires_at_least_2_blanks")

    # Check group ids
    group_ids: list[str] = []
    seen_ids: set[str] = set()
    for i, group in enumerate(groups):
        gid = str(group.get("id") or "").strip()
        if not gid:
            errors.append(f"group_{i}_has_empty_id")
            continue
        if gid in seen_ids:
            errors.append(f"duplicate_group_id_{gid}")
        seen_ids.add(gid)
        group_ids.append(gid)

        # Check options
        opts = group.get("options") or []
        if len(opts) < 2:
            errors.append(f"group_{gid}_has_less_than_2_options")

        seen_keys: set[str] = set()
        for opt in opts:
            key = str(opt.get("key") or "").upper()
            if key in seen_keys:
                errors.append(f"group_{gid}_duplicate_option_key_{key}")
            seen_keys.add(key)

    # Parse and validate answer
    if not group_ids:
        return False, errors

    if answer is None or (isinstance(answer, str) and not answer.strip()):
        errors.append("multi_blank_choice_missing_answer")
        return False, errors

    if isinstance(answer, str):
        answer_map, parse_errors = parse_multi_blank_answer(
            answer, slot_ids=group_ids, allow_positional=False
        )
        errors.extend(parse_errors)
    elif isinstance(answer, dict):
        answer_map = answer
    else:
        errors.append(f"invalid_answer_type: {type(answer).__name__}")
        return False, errors

    if not answer_map:
        # Invalid slot values (non A-H letters) surface as
        # invalid_value_for_slot_<slot> errors; name the offending slot's
        # option set so reviewers see which group is wrong.
        for error in list(errors):
            m = re.match(r"invalid_value_for_slot_(.+?):", error)
            if m:
                slot = m.group(1)
                valid_keys = _group_option_keys(groups, slot)
                if valid_keys:
                    errors.append(
                        f"answer_{slot}=not_in_group_options_{sorted(valid_keys)}"
                    )
        if any("not_in_group_options" in e for e in errors):
            return False, errors
        if not any("unparseable" in e for e in errors):
            errors.append("multi_blank_choice_empty_answer_after_parse")
        return False, errors

    # Check coverage
    missing_slots = [gid for gid in group_ids if gid not in answer_map]
    if missing_slots:
        errors.append(f"answer_missing_slots: {','.join(missing_slots)}")

    extra_slots = [sid for sid in answer_map if sid not in seen_ids]
    if extra_slots:
        errors.append(f"answer_extra_slots: {','.join(extra_slots)}")

    # Check each answer value exists in group options
    group_opts_map: dict[str, set[str]] = {}
    for group in groups:
        gid = str(group.get("id") or "").strip()
        group_opts_map[gid] = {
            str(o.get("key") or "").upper() for o in (group.get("options") or [])
        }

    for gid, val in answer_map.items():
        if gid not in group_opts_map:
            continue
        valid_keys = group_opts_map[gid]
        letters = [v for v in str(val).split(",") if v]
        invalid = [v for v in letters if v not in valid_keys]
        if invalid:
            errors.append(
                f"answer_{gid}={val}_not_in_group_options_{sorted(valid_keys)}"
            )

    return len(errors) == 0, errors


# ── Detection ────────────────────────────────────────────────────


def detect_shared_option_multi_blank(
    stem: str,
    options: list[dict] | dict | None,
    answer: str | None,
    explicit_question_type: str | None = None,
) -> dict:
    """Detect if a question is a shared-option multi-blank choice.

    A shared-option multi-blank choice has:
    - At least 2 blank slots in the stem
    - A single set of options shared by all blanks
    - An answer that parses to at least 2 slot values

    Args:
        stem: Question stem text (may contain blank markers)
        options: Parsed option list/dict (shared options)
        answer: Raw answer string
        explicit_question_type: If explicitly a multi-blank choice type
            (multi_blank_choice / multi_blank_multiple_choice), skip detection

    Returns:
        Detection result dict:
        {
            "is_multi_blank_choice": bool,
            "slot_ids": list[str],
            "blank_option_groups": list[dict],
            "serialized_answer": str,
            "reason": str,
            "warnings": list[str],
        }
    """
    warnings: list[str] = []
    result: dict = {
        "is_multi_blank_choice": False,
        "slot_ids": [],
        "blank_option_groups": [],
        "serialized_answer": "",
        "reason": "",
        "warnings": warnings,
    }

    # If explicitly typed as a multi-blank choice, trust it
    if explicit_question_type in (
        "multi_blank_choice",
        "multi_blank_multiple_choice",
    ):
        result["reason"] = "explicit_question_type"
        # Try to extract slots from stem first, then reconcile with answer
        slot_ids = extract_blank_slots(stem)
        if answer:
            parsed, _ = parse_multi_blank_answer(answer)
            parsed_slot_ids = list(parsed.keys())
            if parsed_slot_ids and set(parsed_slot_ids) != set(slot_ids):
                slot_ids = parsed_slot_ids
        if slot_ids and options:
            groups = build_blank_option_groups(slot_ids, options)
            if groups:
                result["slot_ids"] = slot_ids
                result["blank_option_groups"] = groups
                result["is_multi_blank_choice"] = True
                result["serialized_answer"] = serialize_multi_blank_answer(
                    parsed if answer else {}, slot_ids
                )
            else:
                warnings.append("explicit_type_but_could_not_build_groups")
        return result

    # Check for at least 2 blank slots in stem
    slot_ids = extract_blank_slots(stem)
    if len(slot_ids) < 2:
        return result

    # Must have options
    if not options:
        warnings.append("multiple_blanks_without_options")
        return result

    # Normalize options
    if isinstance(options, dict):
        opt_keys = sorted(options.keys())
    elif isinstance(options, list):
        opt_keys = sorted([o.get("key", "") for o in options if isinstance(o, dict)])
    else:
        return result

    # Need at least 2 option keys
    if len(opt_keys) < 2:
        warnings.append("multiple_blanks_but_options_insufficient")
        return result

    # Check if answer parses to at least 2 slots
    if answer:
        parsed, _parse_errors = parse_multi_blank_answer(
            answer, slot_ids=slot_ids, allow_positional=True
        )

        # If parsed slot IDs don't match stem-extracted slot IDs, reconcile.
        # This handles the case where stem has anonymous "（ ）" → ["1", "2"]
        # but answer uses "①", "②" → answer-derived IDs are more explicit.
        parsed_slot_ids = list(parsed.keys())
        if parsed_slot_ids and set(parsed_slot_ids) != set(slot_ids):
            # Use answer-derived slot IDs as they are more explicit
            slot_ids = parsed_slot_ids

        if len(parsed) < 2:
            warnings.append(f"answer_parsed_to_only_{len(parsed)}_slot(s)")
            result["reason"] = "multiple_blanks_with_options_but_answer_insufficient"
            return result

        # Serialize answer
        serialized = serialize_multi_blank_answer(parsed, slot_ids)
    else:
        parsed = {}
        serialized = ""
        warnings.append("multiple_blanks_with_options_but_no_answer")

    # Build blank option groups
    groups = build_blank_option_groups(slot_ids, options)
    if not groups:
        warnings.append("could_not_build_blank_option_groups")
        return result

    result["is_multi_blank_choice"] = True
    result["slot_ids"] = slot_ids
    result["blank_option_groups"] = groups
    result["serialized_answer"] = serialized
    result["reason"] = "shared_options_multi_blank_detected"

    # Additional warnings
    if len(slot_ids) != len(parsed):
        warnings.append(
            f"slot_count_mismatch: {len(slot_ids)} slots vs {len(parsed)} answers"
        )

    return result
