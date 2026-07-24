"""Table detection stage — rule engine for detecting table-like structures.

Extracted from ``pipeline_orchestrator.py:_run_table_detect`` (P5-2).
"""

from __future__ import annotations

import logging

from app.features.pipeline_stages._helpers import _count_risk_flags
from app.features.table_region_detector import detect_table_candidate

logger = logging.getLogger(__name__)


def run_table_detect_stage(questions: list[dict]) -> dict:
    """Detect table candidates in OCR text and add risk flags + Markdown segments.

    Lightweight rule engine — no AI calls.

    Returns:
        dict with ``questions``, ``warnings``, ``risk_flag_counts`` keys.
    """
    if not questions:
        return {"questions": questions, "warnings": ["table_detect: empty questions"]}

    warnings: list[str] = []
    table_count = 0

    for q in questions:
        stem = q.get("stem") or q.get("parsed_content", {}).get("text") or ""
        if not stem or len(stem) < 40:
            continue

        result = detect_table_candidate(stem)
        if not result["is_table"]:
            continue

        table_count += 1
        flags = list(q.get("risk_flags") or [])
        flags.append("table_detected")
        if result["confidence"] < 0.5 or not result["markdown"]:
            flags.append("table_low_confidence")
        else:
            flags.append("table_requires_review")

        segments: list[dict] = list(q.get("segments") or [])
        segments.append({
            "type": "table_markdown",
            "markdown": result["markdown"],
            "source_page": q.get("page_start") or 1,
            "bbox": None,
            "confidence": result["confidence"],
            "requires_review": result["confidence"] < 0.5 or not result["markdown"],
        })
        q["segments"] = segments
        q["parsed_content"] = {
            **(q.get("parsed_content") or {}),
            "render_mode": "segments",
            "segments": segments,
        }
        q["risk_flags"] = flags

    if table_count:
        warnings.append(f"table_detect: {table_count} table candidates flagged")

    return {
        "questions": questions,
        "warnings": warnings,
        "risk_flag_counts": _count_risk_flags(questions),
    }
