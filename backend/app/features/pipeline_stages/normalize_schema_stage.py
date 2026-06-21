"""Schema normalization stage — standardize, validate, and deduplicate.

Extracted from ``pipeline_orchestrator.py:_run_normalize_schema``,
``_run_batch_validation``, and ``_run_batch_dedup`` (P5-2).
"""

from __future__ import annotations

import logging
from typing import Any

from app.features.batch_validation import validate_batch_structure
from app.features.question_normalizer import dedup_batch, normalize_questions

logger = logging.getLogger(__name__)


def _count_risk_flags(questions: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for q in questions:
        for flag in q.get("risk_flags") or []:
            counts[str(flag)] = counts.get(str(flag), 0) + 1
    return counts


def _blank_option_group_summary(groups: Any) -> list[dict]:
    if not isinstance(groups, list):
        return []
    summary = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        options = group.get("options") or {}
        if isinstance(options, dict):
            option_keys = sorted(str(key).upper() for key in options.keys() if str(key).strip())
            first_a_preview = str(options.get("A") or options.get("a") or "")[:40]
        elif isinstance(options, list):
            option_keys = sorted(
                str(option.get("key") or "").upper()
                for option in options
                if isinstance(option, dict) and str(option.get("key") or "").strip()
            )
            first_a_preview = ""
            for option in options:
                if isinstance(option, dict) and str(option.get("key") or "").upper() == "A":
                    first_a_preview = str(option.get("text") or "")[:40]
                    break
        else:
            option_keys = []
            first_a_preview = ""
        summary.append({
            "id": group.get("id") or group.get("blank_id") or group.get("label") or index + 1,
            "option_keys": option_keys,
            "has_a": "A" in option_keys,
            "first_a_preview": first_a_preview,
        })
    return summary


def _log_multi_blank_stage(stage: str, questions: list[dict], **context: Any) -> None:
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        groups = question.get("blank_option_groups")
        if groups is None:
            parsed_content = question.get("parsed_content")
            if isinstance(parsed_content, dict):
                groups = parsed_content.get("blank_option_groups")
        summary = _blank_option_group_summary(groups)
        if question.get("question_type") != "multi_blank_choice" and not summary:
            continue
        logger.warning(
            "multi_blank_choice pipeline stage",
            extra={
                "stage": stage,
                "question_index": index,
                "question_type": question.get("question_type"),
                "stem_preview": str(question.get("stem") or question.get("raw_question_text") or "")[:80],
                "blank_option_group_count": len(summary),
                "blank_option_groups": summary,
                **context,
            },
        )


def _is_book_import_mode(import_mode) -> bool:
    try:
        from app.features.import_mode import ImportMode
        if isinstance(import_mode, ImportMode):
            return import_mode == ImportMode.BOOK
    except ImportError:
        pass
    return str(import_mode or "").lower() == "book"


def run_normalize_schema_stage(
    raw_questions: list[dict],
    matched: list[dict],
    *,
    source_file: str = "",
    source_type: str = "",
    subject: str | None = None,
    import_mode: Any = None,
    exercise_regions_missing: bool = False,
) -> dict:
    """Normalize questions to standard schema, adding risk flags.

    Returns:
        dict with ``questions``, ``normalized_count``, ``risk_flag_counts``,
        ``errors``, ``warnings`` keys.
    """
    source_info = {
        "file": source_file,
        "type": source_type,
        "subject": subject or "",
    }
    result = normalize_questions(raw_questions, matched, source_info)

    questions = result.get("questions", [])
    _log_multi_blank_stage("normalize_schema", questions, source_type=source_type, source_file=source_file)
    errors = result.get("errors", [])
    warnings = result.get("warnings", [])

    invalid_count = sum(1 for q in questions if not q.get("is_valid", True))
    stage_warnings = list(warnings)
    if invalid_count:
        stage_warnings.append(f"{invalid_count} questions marked invalid")

    # Stage-level risk signals
    is_book = _is_book_import_mode(import_mode)
    no_regions_flagged = 0
    for q in questions:
        flags = list(q.get("risk_flags") or [])
        if exercise_regions_missing and is_book:
            flags.append("no_exercise_regions")
            no_regions_flagged += 1
        if (q.get("confidence_score") or 0) < 0.5:
            flags.append("low_confidence")
        if "garbled_text_detected" in (q.get("ocr_quality_flags") or []):
            flags.append("ocr_garbled_code")
        if flags:
            q["risk_flags"] = list(dict.fromkeys(flags))
    if no_regions_flagged:
        stage_warnings.append(
            f"no_exercise_regions risk flag attached to {no_regions_flagged} questions"
        )

    # Log each parsed question
    for q in questions:
        raw_opts = q.get("parsed_options") or q.get("options") or {}
        if isinstance(raw_opts, dict):
            opt_summary = ", ".join(
                f"{k}: {str(v)[:60]}" for k, v in sorted(raw_opts.items())
            ) or "(无选项)"
        elif isinstance(raw_opts, list):
            opt_summary = ", ".join(
                f"{o.get('key', '?')}: {str(o.get('text', ''))[:60]}"
                for o in raw_opts
            ) or "(无选项)"
        else:
            opt_summary = str(raw_opts)[:200]
        logger.info(
            "【OCR-7】schema归一化结果 | number=%s type=%s valid=%s conf=%.2f\n"
            "  └─ 题干: %.200s\n"
            "  └─ 选项: %s\n"
            "  └─ 答案: %s\n"
            "  └─ risk_flags: %s",
            q.get("number", "?"), q.get("question_type", "?"),
            q.get("is_valid", True), q.get("confidence_score", 0),
            str(q.get("stem") or q.get("parsed_content") or "")[:200],
            opt_summary[:200],
            str(q.get("parsed_answer") or "❌"),
            q.get("risk_flags") or [],
        )

    return {
        "questions": questions,
        "normalized_count": len(questions),
        "risk_flag_counts": _count_risk_flags(questions),
        "errors": list(errors),
        "warnings": stage_warnings,
    }


def run_batch_validation_stage(questions: list[dict]) -> dict:
    """Cross-question structural integrity validation (pure rules)."""
    result = validate_batch_structure(questions)

    warnings: list[str] = []
    stats = result["batch_validation_diagnostics"]["stats"]
    if stats["number_gap_count"] > 0:
        warnings.append(f"{stats['number_gap_count']} question number gaps detected")
    if stats["incomplete_option_count"] > 0:
        warnings.append(f"{stats['incomplete_option_count']} questions with incomplete options")
    if stats["missing_answer_count"] > 0:
        warnings.append(f"{stats['missing_answer_count']} questions missing answers")
    if stats.get("roman_numeral_issue_count", 0) > 0:
        warnings.append(f"{stats['roman_numeral_issue_count']} Roman numeral sequence issues detected")
    if stats.get("roman_digit_confusion_count", 0) > 0:
        warnings.append(f"{stats['roman_digit_confusion_count']} Roman digit confusion issues detected")

    return {
        "questions": result["questions"],
        "batch_validation_diagnostics": result["batch_validation_diagnostics"],
        "warnings": warnings,
    }


def run_batch_dedup_stage(questions: list[dict]) -> dict:
    """Flag batch-internal duplicates to skip expensive repair."""
    result = dedup_batch(questions)

    warnings: list[str] = []
    if result["duplicate_count"] > 0:
        warnings.append(f"{result['duplicate_count']} batch-internal duplicates flagged")

    return {
        "questions": result["questions"],
        "batch_dedup_diagnostics": {
            "unique_count": result["unique_count"],
            "duplicate_count": result["duplicate_count"],
            "duplicate_indices": result["duplicate_indices"],
        },
        "warnings": warnings,
    }
