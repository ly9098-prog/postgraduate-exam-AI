"""Answer normalization and comparison utilities.

Single source of truth for all answer judgment across practice, review, and grading.
Multi-blank choice logic is delegated to app.features.multi_blank_choice.
"""

import re

from app.features.multi_blank_choice import (
    parse_multi_blank_answer,
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


def normalize_blank_answer(answer: str) -> dict:
    """Parse blank-slot answer format into dict using multi_blank_choice module."""
    parsed, _ = parse_multi_blank_answer(answer)
    return parsed


def is_answer_correct(
    user_answer: str,
    correct_answer: str,
    question_type: str,
) -> bool:
    """Check if user_answer matches correct_answer for the given question type.

    - multiple_choice: normalized set comparison (order-independent)
    - true_false / judgement: value normalized to A/B
    - multi_blank_choice: slot-by-slot comparison (all required, no extras, order-independent)
    - single_choice / others: case-insensitive trim comparison
    """
    if not user_answer or not correct_answer:
        return False

    if is_multi_blank_type(question_type):
        # Parse both answers using the unified module
        correct_map, _c_err = parse_multi_blank_answer(correct_answer)
        user_map, _u_err = parse_multi_blank_answer(user_answer)
        if not correct_map:
            return False
        if not user_map:
            return False
        # All correct slots must be present in user answer
        # and user answer must not have extra slots
        if set(user_map.keys()) != set(correct_map.keys()):
            return False
        # Each slot value must match exactly
        return user_map == correct_map

    if is_true_false_type(question_type):
        ua = user_answer.strip().lower()
        ca = correct_answer.strip().lower()
        u = "A" if ua in _TRUE_FALSE_TRUE else ("B" if ua in _TRUE_FALSE_FALSE else ua.upper())
        c = "A" if ca in _TRUE_FALSE_TRUE else ("B" if ca in _TRUE_FALSE_FALSE else ca.upper())
        return u == c

    if is_multiple_choice_type(question_type):
        return serialize_choice_answer(user_answer) == serialize_choice_answer(correct_answer)

    # single_choice or fallback: case-insensitive, whitespace-trimmed
    return user_answer.strip().upper() == correct_answer.strip().upper()
