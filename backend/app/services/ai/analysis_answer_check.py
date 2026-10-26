"""Answer-check traversal and comparison through the original content ports."""

from __future__ import annotations


def extract_answer_check(value, depth: int = 0, *, ports) -> dict | None:
    """Find the machine-verifiable ``answer_check`` object in model output."""
    if depth > 6 or value is None:
        return None
    if isinstance(value, str):
        decoded = ports("_decode_structured_content")(value)
        if decoded is None or decoded == value:
            return None
        return ports("_extract_answer_check")(decoded, depth + 1)
    if isinstance(value, list):
        for item in value:
            found = ports("_extract_answer_check")(item, depth + 1)
            if found is not None:
                return found
        return None
    if not isinstance(value, dict):
        return None
    for key in ports("_ANSWER_CHECK_KEYS"):
        candidate = value.get(key)
        if isinstance(candidate, dict):
            return candidate
    for key in ports("_ANALYSIS_WRAPPER_KEYS"):
        if key in value:
            found = ports("_extract_answer_check")(value.get(key), depth + 1)
            if found is not None:
                return found
    for nested in value.values():
        if isinstance(nested, (dict, list, str)):
            found = ports("_extract_answer_check")(nested, depth + 1)
            if found is not None:
                return found
    return None


def canonical_answer_echo(value, expected: str, *, ports) -> str:
    raw = str(value or "").strip().upper()
    expected = str(expected or "").strip().upper()
    if expected and ports("re").fullmatch(r"[A-Z](?:,[A-Z])*", expected):
        letters = sorted(set(ports("re").findall(r"[A-Z]", raw)))
        return ",".join(letters)
    return raw.replace("，", ",").replace("；", ",").replace("、", ",")


def canonical_answer_check_list(value, *, ports) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [item for item in ports("re").split(r"[,，、;；\s]+", value) if item]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    result: list[str] = []
    for item in items:
        if isinstance(item, dict):
            item = item.get("label") or item.get("key") or item.get("id") or ""
        text = (
            str(item or "").strip().translate(ports("_ROMAN_ECHO_TRANSLATION")).upper()
        )
        if text and text not in result:
            result.append(text)
    return result


def validate_answer_check(
    raw_content: str, expected: dict, *, ports
) -> tuple[bool, str, dict | None]:
    decoded = ports("_decode_structured_content")(raw_content)
    actual = ports("_extract_answer_check")(
        decoded if decoded is not None else raw_content
    )
    if actual is None:
        return (False, "answer_check_missing", None)
    correct_actual = ports("_canonical_answer_echo")(
        actual.get("correct_answer", actual.get("correctAnswer", "")),
        str(expected.get("correct_answer") or ""),
    )
    user_actual = ports("_canonical_answer_echo")(
        actual.get("user_answer", actual.get("userAnswer", "")),
        str(expected.get("user_answer") or ""),
    )
    correct_expected = ports("_canonical_answer_echo")(
        expected.get("correct_answer", ""), str(expected.get("correct_answer") or "")
    )
    user_expected = ports("_canonical_answer_echo")(
        expected.get("user_answer", ""), str(expected.get("user_answer") or "")
    )
    if correct_actual != correct_expected:
        return (False, "answer_check_correct_mismatch", actual)
    if user_actual != user_expected:
        return (False, "answer_check_user_mismatch", actual)
    missing_actual = ports("_canonical_answer_check_list")(
        actual.get("missing", actual.get("missing_items", []))
    )
    extra_actual = ports("_canonical_answer_check_list")(
        actual.get("extra", actual.get("extra_items", []))
    )
    missing_expected = ports("_canonical_answer_check_list")(
        expected.get("missing", [])
    )
    extra_expected = ports("_canonical_answer_check_list")(expected.get("extra", []))
    if sorted(missing_actual) != sorted(missing_expected):
        return (False, "answer_check_missing_mismatch", actual)
    if sorted(extra_actual) != sorted(extra_expected):
        return (False, "answer_check_extra_mismatch", actual)
    return (True, "", actual)
