"""Split quality evaluation — assesses split output quality at pipeline end.

Observation-only — no DAG or routing changes.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def evaluate_split_quality(
    raw_questions: list[dict],
    split_diagnostics: dict | None = None,
    layout_result: dict | None = None,
) -> dict[str, Any]:
    """Evaluate quality of split output.

    Metrics:
    - split_quality_score: 0-1 overall quality
    - option_recovery_rate: 0-1 proportion of questions with options
    - order_accuracy: 0-1 sequential order accuracy

    Args:
        raw_questions: list of raw_question dicts from split stage.
        split_diagnostics: diagnostics dict from split stage (optional).
        layout_result: layout reconstruction result (optional, for context).

    Returns:
        dict with evaluation metrics.
    """
    if not raw_questions:
        return {
            "split_quality_score": 0.0,
            "option_recovery_rate": 0.0,
            "order_accuracy": 1.0,
            "question_count": 0,
            "confidence_distribution": {},
            "warnings": ["split_quality: no questions to evaluate"],
        }

    n = len(raw_questions)

    # ── Option recovery ──
    with_options = sum(1 for q in raw_questions if q.get("has_options"))
    option_recovery_rate = round(with_options / n, 3) if n > 0 else 0.0

    # ── Order accuracy — sequential question numbers ──
    numbers = [q["number"] for q in raw_questions if q.get("number") is not None]
    if len(numbers) >= 2:
        first = numbers[0]
        expected = list(range(first, first + len(numbers)))
        correct = sum(1 for a, b in zip(numbers, expected) if a == b)
        order_accuracy = round(correct / len(numbers), 3)
    else:
        order_accuracy = 1.0

    # ── Confidence distribution ──
    confidences = [q.get("confidence", 0.0) for q in raw_questions]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    high = sum(1 for c in confidences if c >= 0.8)
    medium = sum(1 for c in confidences if 0.5 <= c < 0.8)
    low = sum(1 for c in confidences if c < 0.5)

    confidence_distribution = {
        "high": {"count": high, "percentage": round(high / n * 100, 1)},
        "medium": {"count": medium, "percentage": round(medium / n * 100, 1)},
        "low": {"count": low, "percentage": round(low / n * 100, 1)},
    }

    # ── Overall quality score ──
    # 40 % option recovery, 30 % confidence, 30 % order accuracy
    split_quality_score = round(
        option_recovery_rate * 0.4
        + avg_confidence * 0.3
        + order_accuracy * 0.3,
        3,
    )

    warnings: list[str] = []
    if option_recovery_rate < 0.5:
        warnings.append(
            f"split_quality: low option recovery rate {option_recovery_rate:.1%}"
        )
    if order_accuracy < 0.8:
        warnings.append(
            f"split_quality: order issue, accuracy={order_accuracy:.1%}"
        )
    if avg_confidence < 0.5:
        warnings.append(
            f"split_quality: low avg confidence {avg_confidence:.2f}"
        )

    result: dict[str, Any] = {
        "split_quality_score": split_quality_score,
        "option_recovery_rate": option_recovery_rate,
        "order_accuracy": order_accuracy,
        "question_count": n,
        "avg_confidence": round(avg_confidence, 3),
        "with_options_count": with_options,
        "confidence_distribution": confidence_distribution,
    }
    if split_diagnostics:
        result["split_mode"] = split_diagnostics.get("split_mode", "unknown")
    if warnings:
        result["warnings"] = warnings

    return result
