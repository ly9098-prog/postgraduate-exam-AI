"""Shared helper functions for pipeline stage modules.

Extracted from duplicated definitions across ``pipeline_stages/`` modules
and ``pipeline_orchestrator.py`` (P5 code quality fix).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _count_risk_flags(questions: list[dict]) -> dict[str, int]:
    """Aggregate risk_flag frequencies across a list of questions."""
    counts: dict[str, int] = {}
    for q in questions:
        for flag in q.get("risk_flags") or []:
            counts[str(flag)] = counts.get(str(flag), 0) + 1
    return counts


def _blank_option_group_summary(groups: Any) -> list[dict]:
    """Build a human-readable summary of blank_option_groups for logging."""
    if not isinstance(groups, list):
        return []
    summary = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        options = group.get("options") or {}
        if isinstance(options, dict):
            option_keys = sorted(
                str(key).upper() for key in options.keys() if str(key).strip()
            )
            first_a_preview = str(options.get("A") or options.get("a") or "")[:40]
        elif isinstance(options, list):
            option_keys = sorted(
                str(option.get("key") or "").upper()
                for option in options
                if isinstance(option, dict) and str(option.get("key") or "").strip()
            )
            first_a_preview = ""
            for option in options:
                if (
                    isinstance(option, dict)
                    and str(option.get("key") or "").upper() == "A"
                ):
                    first_a_preview = str(option.get("text") or "")[:40]
                    break
        else:
            option_keys = []
            first_a_preview = ""
        summary.append(
            {
                "id": group.get("id")
                or group.get("blank_id")
                or group.get("label")
                or index + 1,
                "option_keys": option_keys,
                "has_a": "A" in option_keys,
                "first_a_preview": first_a_preview,
            }
        )
    return summary


def _log_multi_blank_stage(stage: str, questions: list[dict], **context: Any) -> None:
    """Log multi_blank_choice questions passing through a pipeline stage."""
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        groups = question.get("blank_option_groups")
        if groups is None:
            parsed_content = question.get("parsed_content")
            if isinstance(parsed_content, dict):
                groups = parsed_content.get("blank_option_groups")
        summary = _blank_option_group_summary(groups)
        if (
            question.get("question_type")
            not in (
                "multi_blank_choice",
                "multi_blank_multiple_choice",
            )
            and not summary
        ):
            continue
        logger.warning(
            "multi_blank_choice pipeline stage",
            extra={
                "stage": stage,
                "question_index": index,
                "question_type": question.get("question_type"),
                "stem_preview": str(
                    question.get("stem") or question.get("raw_question_text") or ""
                )[:80],
                "blank_option_group_count": len(summary),
                "blank_option_groups": summary,
                **context,
            },
        )
