"""Answer normalization and comparison utilities.

Single source of truth for all answer judgment across practice, review, and grading.
Multi-blank choice logic is delegated to app.features.multi_blank_choice.
"""

import re

from app.features.multi_blank_choice import (
    extract_blank_slots,
    parse_multi_blank_answer,
)
from app.features.question_type import (
    is_multi_blank_multiple_type as _is_multi_blank_multiple_type,
)
from app.features.question_type import (
    is_multi_blank_type as _is_multi_blank_type,
)
from app.features.question_type import (
    is_multiple_choice_type as _is_multiple_choice_type,
)
from app.features.question_type import (
    is_true_false_type as _is_true_false_type,
)

_TRUE_FALSE_TRUE = {"a", "true", "对", "是", "正确", "t", "yes", "1"}
_TRUE_FALSE_FALSE = {"b", "false", "错", "否", "错误", "f", "no", "0"}


def is_multiple_choice_type(question_type: str) -> bool:
    return _is_multiple_choice_type(question_type)


def is_true_false_type(question_type: str) -> bool:
    return _is_true_false_type(question_type)


def is_multi_blank_type(question_type: str) -> bool:
    return _is_multi_blank_type(question_type)


def is_multi_blank_multiple_type(question_type: str) -> bool:
    return _is_multi_blank_multiple_type(question_type)


def _slot_letter_set(value: str) -> set[str]:
    """Normalize a slot value ("A,C" / "AC") to a set of uppercase letters."""
    return {ch for ch in str(value).upper() if "A" <= ch <= "H"}


def normalize_choice_answer(answer: str) -> list[str]:
    """Normalize a choice answer to a sorted, deduplicated list of option letters.

    Supports: "A,C", "C,A", "AC", "A C", "A；C", "A，C", "a,c"
    """
    if not answer:
        return []
    s = str(answer).upper().strip()
    # Try splitting by common delimiters
    parts = [p.strip() for p in re.split(r"[;,；，\s]+", s) if p.strip()]
    if len(parts) <= 1:
        # No delimiter — try adjacent uppercase letters (e.g. "AC" -> ["A","C"])
        parts = [ch for ch in s if "A" <= ch <= "Z"]
    # Filter, deduplicate, sort
    seen = set()
    result = []
    for p in parts:
        if len(p) == 1 and "A" <= p <= "Z" and p not in seen:
            seen.add(p)
            result.append(p)
    result.sort()
    return result


def serialize_choice_answer(answer: str) -> str:
    """Normalize and serialize to a stable form like "A,C"."""
    return ",".join(normalize_choice_answer(answer))


def normalize_blank_answer(answer: str, slot_ids: list[str] | None = None) -> dict:
    """Parse blank-slot answer format into dict using multi_blank_choice module."""
    parsed, _ = parse_multi_blank_answer(answer, slot_ids=slot_ids)
    return parsed


def extract_multi_blank_slot_ids(
    content: dict | None, options: object | None = None
) -> list[str]:
    """Resolve trusted multi-blank slot ids from immutable question content.

    Legacy imports may store the standard answer as positional ``A,B``/``AB``.
    Positional parsing is only safe when the slot order comes from the question
    itself (not from user-submitted answer keys), so both practice and review
    grading use this helper before comparing answers.
    """
    if not isinstance(content, dict):
        content = {}

    for key in ("blank_option_groups", "blank_groups"):
        raw_groups = content.get(key)
        if not isinstance(raw_groups, list):
            continue
        ids: list[str] = []
        for group in raw_groups:
            if not isinstance(group, dict):
                continue
            slot_id = str(group.get("id") or group.get("slot_id") or "").strip()
            if slot_id and slot_id not in ids:
                ids.append(slot_id)
        if ids:
            return ids

    for key in ("blank_ids", "blank_markers"):
        raw_ids = content.get(key)
        if isinstance(raw_ids, list):
            ids = []
            for value in raw_ids:
                slot_id = str(value or "").strip()
                if slot_id and slot_id not in ids:
                    ids.append(slot_id)
            if ids:
                return ids

    # Some historical imports put grouped blank data in the top-level options
    # snapshot instead of content.blank_option_groups. Accept the common list
    # and id-keyed map shapes, but never treat a flat {A: ..., B: ...} option
    # map as slot ids.
    if isinstance(options, list):
        ids: list[str] = []
        for index, group in enumerate(options):
            if not isinstance(group, dict):
                continue
            slot_id = str(
                group.get("id") or group.get("marker") or group.get("blank_id") or ""
            ).strip()
            if slot_id and slot_id not in ids:
                ids.append(slot_id)
        if ids:
            return ids
    elif isinstance(options, dict):
        nested_groups = options.get("blank_option_groups") or options.get("groups")
        if isinstance(nested_groups, list):
            ids = []
            for group in nested_groups:
                if not isinstance(group, dict):
                    continue
                slot_id = str(
                    group.get("id")
                    or group.get("marker")
                    or group.get("blank_id")
                    or ""
                ).strip()
                if slot_id and slot_id not in ids:
                    ids.append(slot_id)
            if ids:
                return ids
        keys = [str(key).strip() for key in options.keys()]
        if keys and not all(re.fullmatch(r"[A-Za-z]", key or "") for key in keys):
            group_like = all(
                isinstance(options.get(key), (dict, list)) for key in options.keys()
            )
            if group_like:
                return [key for key in keys if key]

    stem = content.get("text") or content.get("stem") or ""
    return extract_blank_slots(str(stem))


def is_answer_correct(
    user_answer: str,
    correct_answer: str,
    question_type: str,
    *,
    slot_ids: list[str] | None = None,
) -> bool:
    """Check if user_answer matches correct_answer for the given question type.

    - multiple_choice: normalized set comparison (order-independent)
    - true_false: value normalized to A/B
    - multi_blank_choice: slot-by-slot comparison (all required, no extras)
      - multi_blank_choice: each slot holds exactly one letter
      - multi_blank_multiple_choice: each slot is a letter set,
        compared order-independently (subset semantics per slot)
    - single_choice / others: case-insensitive trim comparison
    """
    if not user_answer or not correct_answer:
        return False

    if is_multi_blank_type(question_type):
        # Parse both answers using the unified module
        correct_map, _c_err = parse_multi_blank_answer(
            correct_answer, slot_ids=slot_ids
        )
        user_map, _u_err = parse_multi_blank_answer(user_answer, slot_ids=slot_ids)
        if not correct_map:
            return False
        if not user_map:
            return False
        # All correct slots must be present in user answer
        # and user answer must not have extra slots
        if set(user_map.keys()) != set(correct_map.keys()):
            return False
        if is_multi_blank_multiple_type(question_type):
            # Multi-select blank: each slot is a set of letters. The user's
            # selection must contain every correct letter (extra wrong letters
            # make the slot wrong via the subset check below failing only when
            # user misses a letter; to also reject extras we require equality).
            return all(
                _slot_letter_set(user_map[slot]) == _slot_letter_set(correct_map[slot])
                for slot in correct_map
            )
        # Single-select blank: each slot value must match exactly
        return user_map == correct_map

    if is_true_false_type(question_type):
        ua = user_answer.strip().lower()
        ca = correct_answer.strip().lower()
        u = (
            "A"
            if ua in _TRUE_FALSE_TRUE
            else ("B" if ua in _TRUE_FALSE_FALSE else ua.upper())
        )
        c = (
            "A"
            if ca in _TRUE_FALSE_TRUE
            else ("B" if ca in _TRUE_FALSE_FALSE else ca.upper())
        )
        return u == c

    if is_multiple_choice_type(question_type):
        return serialize_choice_answer(user_answer) == serialize_choice_answer(
            correct_answer
        )

    # single_choice or fallback: case-insensitive, whitespace-trimmed
    return user_answer.strip().upper() == correct_answer.strip().upper()
