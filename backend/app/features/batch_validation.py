"""Batch structural validation — cross-question integrity checks.

Pure-rule pass (no AI). Runs after normalize_schema, before batch_dedup.
Checks:
- Sequential question number continuity (gap detection)
- Option completeness for choice questions
- Answer presence for choice/true_false types

Flags anomalies as warnings on individual questions + batch-level stats.
"""

import logging
import re

logger = logging.getLogger(__name__)

_CHOICE_TYPES = ("single_choice", "multiple_choice")
_EXPECTED_OPTION_KEYS = {"A", "B", "C", "D"}

# 罗马数字枚举检测 — 用于验证题干中 I./II./III. 序列的完整性
_ROMAN_SUBITEM_TOKEN = r"(?:VIII|VII|III|VI|IV|IX|II|V|X|I)"
_RE_ROMAN_SUBITEM_MARKER = re.compile(
    r"(?<![A-Za-z])" + _ROMAN_SUBITEM_TOKEN + r"(?![A-Za-z])\s*[.、)）]"
)
_ROMAN_TO_VALUE = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
}


def _check_number_continuity(questions: list[dict]) -> list[dict]:
    """Detect gaps in question numbering sequence.

    Handles section resets: if a number drops back to 1 while the previous
    was > 1, treat it as a new section rather than a gap.
    """
    gaps: list[dict] = []
    prev_num: int | None = None

    for i, q in enumerate(questions):
        num = q.get("source", {}).get("page", 0)
        raw_text = q.get("raw_text", "")
        m = re.match(r"^\s*(\d+)\s*[.、)）]", raw_text)
        if m:
            num = int(m.group(1))
        else:
            # Fallback: use position-based numbering (1-indexed)
            num = i + 1

        if prev_num is not None:
            # Section reset detection: number drops to 1
            if num == 1 and prev_num > 1:
                prev_num = num
                continue

            # Gap detection
            if num > prev_num + 1:
                for missing in range(prev_num + 1, num):
                    gaps.append({
                        "expected": missing,
                        "actual": num,
                        "after_index": i - 1,
                    })

        prev_num = num

    return gaps


def _check_option_completeness(question: dict, index: int) -> dict | None:
    """For choice questions, check A/B/C/D are all present."""
    qt = question.get("question_type", "")
    if qt not in _CHOICE_TYPES:
        return None

    options = question.get("options", [])
    if not options:
        return {
            "index": index,
            "found": [],
            "missing": sorted(_EXPECTED_OPTION_KEYS),
        }

    found_keys: set[str] = set()
    for opt in options:
        if isinstance(opt, dict):
            found_keys.add(opt.get("key", "").upper())

    missing = _EXPECTED_OPTION_KEYS - found_keys
    if missing:
        return {
            "index": index,
            "found": sorted(found_keys),
            "missing": sorted(missing),
        }

    return None


def _check_answer_presence(question: dict, index: int) -> dict | None:
    """For choice/true_false types, verify answer field is non-empty."""
    qt = question.get("question_type", "")
    if qt not in (*_CHOICE_TYPES, "true_false"):
        return None

    answer = (question.get("answer") or "").strip()
    if not answer:
        return {
            "index": index,
            "question_type": qt,
        }

    return None


def _check_roman_numeral_sequence(questions: list[dict]) -> list[dict]:
    """检测题干和选项中罗马数字枚举序列的完整性。

    识别 I→II→II→IV→V 这类序列断裂（重复/非递增），
    以及 I→II→III→V 这类跳号（缺失项），
    标记具体断裂位置供下游 AI repair 和前端审核参考。
    """
    def _scan_text(text: str, index: int, source: str = "stem") -> list[dict]:
        """扫描单段文本中的罗马数字序列完整性。"""
        if not text:
            return []
        markers = _RE_ROMAN_SUBITEM_MARKER.findall(text)
        if len(markers) < 3:
            return []
        values: list[int] = []
        tokens: list[str] = []
        for m in markers:
            rm = re.match(_ROMAN_SUBITEM_TOKEN, m)
            if rm:
                token = rm.group(0)
                tokens.append(token)
                values.append(_ROMAN_TO_VALUE.get(token, 0))
        if len(values) < 3:
            return []
        if any(values[j] - values[j - 1] != 1 for j in range(1, len(values))):
            return [{
                "index": index,
                "source": source,
                "found_tokens": tokens,
                "found_values": values,
            }]
        return []

    issues: list[dict] = []
    for i, q in enumerate(questions):
        issues.extend(_scan_text(q.get("stem", ""), i, "stem"))
        for opt in q.get("options", []):
            if isinstance(opt, dict):
                opt_text = opt.get("text", "")
                opt_key = opt.get("key", "")
                issues.extend(_scan_text(opt_text, i, f"option_{opt_key}"))

    return issues


def _check_option_roman_digit_confusion(questions: list[dict]) -> list[dict]:
    """检测选项文本中阿拉伯数字 1 与罗马数字混淆。

    当题干或其它选项含罗马数字标记时，某选项文本中出现阿拉伯数字 1，
    说明 OCR 可能将罗马数字 I 误识为 1。典型场景：'A. 1、I' 应为 'A. I、II'。
    """
    issues: list[dict] = []
    for i, q in enumerate(questions):
        options = q.get("options", [])
        if not options:
            continue

        stem = q.get("stem", "")
        has_roman = bool(_RE_ROMAN_SUBITEM_MARKER.search(stem))
        if not has_roman:
            for opt in options:
                if isinstance(opt, dict) and _RE_ROMAN_SUBITEM_MARKER.search(opt.get("text", "")):
                    has_roman = True
                    break

        if not has_roman:
            continue

        for opt in options:
            if isinstance(opt, dict):
                opt_text = opt.get("text", "")
                opt_key = opt.get("key", "")
                if '1' in opt_text:
                    issues.append({
                        "index": i,
                        "option_key": opt_key,
                        "option_text": opt_text,
                    })

    return issues


def validate_batch_structure(questions: list[dict]) -> dict:
    """Run cross-question structural integrity checks.

    Args:
        questions: normalized questions from Stage 5

    Returns:
        dict with questions (warnings appended) and diagnostics
    """
    number_gaps = _check_number_continuity(questions)
    incomplete_options: list[dict] = []
    missing_answers: list[dict] = []
    roman_issues = _check_roman_numeral_sequence(questions)
    roman_digit_issues = _check_option_roman_digit_confusion(questions)

    for i, q in enumerate(questions):
        opt_issue = _check_option_completeness(q, i)
        if opt_issue:
            incomplete_options.append(opt_issue)

        ans_issue = _check_answer_presence(q, i)
        if ans_issue:
            missing_answers.append(ans_issue)

    # Append warnings to individual questions
    incomplete_indices = {item["index"] for item in incomplete_options}
    missing_ans_indices = {item["index"] for item in missing_answers}

    # Group roman numeral issues by index (stem + multiple options possible)
    roman_issues_by_index: dict[int, list[dict]] = {}
    for item in roman_issues:
        roman_issues_by_index.setdefault(item["index"], []).append(item)

    roman_digit_indices = {item["index"] for item in roman_digit_issues}

    updated_questions: list[dict] = []
    for i, q in enumerate(questions):
        new_q = dict(q)
        warnings = list(new_q.get("warnings", []))

        if i in incomplete_indices:
            issue = next(item for item in incomplete_options if item["index"] == i)
            warnings.append(f"incomplete_options: missing {','.join(issue['missing'])}")

        if i in missing_ans_indices:
            warnings.append("missing_answer_for_objective_question")

        if i in roman_issues_by_index:
            for issue in roman_issues_by_index[i]:
                source = issue.get("source", "stem")
                warnings.append(
                    f"broken_roman_numeral_sequence({source}): "
                    f"found {','.join(issue['found_tokens'])} "
                    f"(values {issue['found_values']})"
                )

        if i in roman_digit_indices:
            for item in roman_digit_issues:
                if item["index"] == i:
                    warnings.append(
                        f"option_roman_digit_confusion: option {item['option_key']} "
                        f"contains '1' in Roman context"
                    )

        new_q["warnings"] = warnings
        updated_questions.append(new_q)

    stats = {
        "total_checked": len(questions),
        "number_gap_count": len(number_gaps),
        "incomplete_option_count": len(incomplete_options),
        "missing_answer_count": len(missing_answers),
        "roman_numeral_issue_count": len(roman_issues),
        "roman_digit_confusion_count": len(roman_digit_issues),
    }

    return {
        "questions": updated_questions,
        "batch_validation_diagnostics": {
            "number_gaps": number_gaps,
            "incomplete_options": incomplete_options,
            "missing_answers": missing_answers,
            "roman_numeral_issues": roman_issues,
            "roman_digit_confusions": roman_digit_issues,
            "stats": stats,
        },
    }
