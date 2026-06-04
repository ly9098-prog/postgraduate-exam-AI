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

    updated_questions: list[dict] = []
    for i, q in enumerate(questions):
        new_q = dict(q)
        warnings = list(new_q.get("warnings", []))

        if i in incomplete_indices:
            issue = next(item for item in incomplete_options if item["index"] == i)
            warnings.append(f"incomplete_options: missing {','.join(issue['missing'])}")

        if i in missing_ans_indices:
            warnings.append("missing_answer_for_objective_question")

        new_q["warnings"] = warnings
        updated_questions.append(new_q)

    stats = {
        "total_checked": len(questions),
        "number_gap_count": len(number_gaps),
        "incomplete_option_count": len(incomplete_options),
        "missing_answer_count": len(missing_answers),
    }

    return {
        "questions": updated_questions,
        "batch_validation_diagnostics": {
            "number_gaps": number_gaps,
            "incomplete_options": incomplete_options,
            "missing_answers": missing_answers,
            "stats": stats,
        },
    }
