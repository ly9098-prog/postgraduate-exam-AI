"""Routing metrics — collect, compute, and report routing effectiveness.

Observation-only — no DAG or routing changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RoutingRecord:
    """Single pipeline run routing decision and outcome."""

    pipeline_id: str
    split_mode: str
    layout_confidence: float
    option_detection_score: float
    option_detection_failed: bool
    question_count: int
    option_missing_questions: int
    avg_split_confidence: float
    split_quality_score: float
    vl_trigger_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


class RoutingMetricsCollector:
    """Collect routing decisions and outcomes across pipeline runs."""

    def __init__(self) -> None:
        self.records: list[RoutingRecord] = []

    def add_record(self, record: RoutingRecord) -> None:
        self.records.append(record)

    def compute_summary(self) -> dict[str, Any]:
        """Aggregate routing metrics from all collected records."""
        if not self.records:
            return {
                "total_runs": 0,
                "mode_distribution": {},
                "success_rates": {},
                "option_missing_rates": {},
                "vl_trigger_rate": 0.0,
                "vl_trigger_reason_distribution": {},
                "over_trigger_warning": None,
                "aggregate_option_missing_rate": 0.0,
            }

        total = len(self.records)

        # ── Mode distribution ──
        mode_counts: dict[str, int] = {}
        for r in self.records:
            mode_counts[r.split_mode] = mode_counts.get(r.split_mode, 0) + 1

        mode_distribution = {
            mode: {
                "count": count,
                "pct": round(count / total * 100, 1),
            }
            for mode, count in sorted(mode_counts.items())
        }

        # ── Success rates per mode (success = questions produced) ──
        mode_success: dict[str, int] = {}
        mode_total: dict[str, int] = {}
        for r in self.records:
            mode_total[r.split_mode] = mode_total.get(r.split_mode, 0) + 1
            if r.question_count > 0:
                mode_success[r.split_mode] = mode_success.get(r.split_mode, 0) + 1

        success_rates = {
            mode: {
                "success": mode_success.get(mode, 0),
                "total": count,
                "rate": round(mode_success.get(mode, 0) / count, 3) if count > 0 else 0.0,
            }
            for mode, count in mode_total.items()
        }

        # ── Option missing rates per mode ──
        mode_missing: dict[str, int] = {}
        mode_qcount: dict[str, int] = {}
        for r in self.records:
            mode_qcount[r.split_mode] = (
                mode_qcount.get(r.split_mode, 0) + r.question_count
            )
            mode_missing[r.split_mode] = (
                mode_missing.get(r.split_mode, 0) + r.option_missing_questions
            )

        option_missing_rates = {}
        for mode in mode_total:
            total_q = mode_qcount.get(mode, 0)
            option_missing_rates[mode] = {
                "missing": mode_missing.get(mode, 0),
                "total_questions": total_q,
                "missing_rate": round(
                    mode_missing.get(mode, 0) / total_q, 3
                ) if total_q > 0 else 0.0,
            }

        # ── VL trigger analysis ──
        vl_records = [r for r in self.records if r.split_mode == "vl_rebuild"]
        vl_trigger_rate = round(len(vl_records) / total, 3) if total > 0 else 0.0

        vl_reasons: dict[str, int] = {}
        for r in vl_records:
            reason = r.vl_trigger_reason or "unknown"
            vl_reasons[reason] = vl_reasons.get(reason, 0) + 1

        vl_trigger_reason_distribution = {
            reason: {
                "count": count,
                "pct": round(count / len(vl_records) * 100, 1) if vl_records else 0.0,
            }
            for reason, count in sorted(vl_reasons.items(), key=lambda x: -x[1])
        }

        # ── Over-trigger detection ──
        over_trigger_warning: str | None = None
        if vl_trigger_rate > 0.1:
            over_trigger_warning = (
                f"VL trigger rate {vl_trigger_rate:.1%} exceeds 10% threshold; "
                "routing thresholds may be too aggressive"
            )

        # ── Aggregate option missing rate ──
        total_questions = sum(r.question_count for r in self.records)
        total_missing = sum(r.option_missing_questions for r in self.records)
        aggregate_option_missing_rate = round(
            total_missing / max(total_questions, 1), 3
        )

        return {
            "total_runs": total,
            "mode_distribution": mode_distribution,
            "success_rates": success_rates,
            "option_missing_rates": option_missing_rates,
            "vl_trigger_rate": vl_trigger_rate,
            "vl_trigger_reason_distribution": vl_trigger_reason_distribution,
            "over_trigger_warning": over_trigger_warning,
            "aggregate_option_missing_rate": aggregate_option_missing_rate,
        }


def build_routing_metrics(data: dict) -> dict[str, Any]:
    """Build per-run routing metrics from pipeline data.

    Called after split stage completes. Stores result in data['routing_metrics'].

    Args:
        data: Pipeline data dict (must contain split results, layout_result, etc.).

    Returns:
        dict with per-run routing metrics.
    """
    split_diagnostics = data.get("split_diagnostics") or {}
    raw_questions = data.get("raw_questions") or []
    layout_result = data.get("layout_result") or {}
    split_quality = data.get("split_quality") or {}

    split_mode = split_diagnostics.get("split_mode", "unknown")
    layout_confidence = layout_result.get("layout_confidence", 1.0)
    option_detection_score = layout_result.get("option_detection_score", 1.0)
    option_detection_failed = layout_result.get("option_detection_failed", False)

    question_count = len(raw_questions)
    option_missing_questions = sum(
        1 for q in raw_questions if not q.get("has_options")
    )
    avg_confidence = (
        sum(q.get("confidence", 0.0) for q in raw_questions) / max(question_count, 1)
    )
    split_quality_score = split_quality.get("split_quality_score", 0.0)

    # VL is now purely confidence-triggered (frozen policy)
    vl_trigger_reason: str | None = "low_confidence" if split_mode == "vl_rebuild" else None

    metrics = {
        "split_mode": split_mode,
        "layout_confidence": round(layout_confidence, 3),
        "option_detection_score": round(option_detection_score, 3),
        "option_detection_failed": option_detection_failed,
        "question_count": question_count,
        "option_missing_count": option_missing_questions,
        "option_missing_rate": round(
            option_missing_questions / max(question_count, 1), 3
        ),
        "avg_split_confidence": round(avg_confidence, 3),
        "split_quality_score": split_quality_score,
        "vl_trigger_reason": vl_trigger_reason,
    }
    return metrics


_global_collector: RoutingMetricsCollector | None = None


def get_global_collector() -> RoutingMetricsCollector:
    """Get or create process-level routing metrics collector."""
    global _global_collector
    if _global_collector is None:
        _global_collector = RoutingMetricsCollector()
    return _global_collector


def reset_global_collector() -> None:
    """Reset the global collector (for testing)."""
    global _global_collector
    _global_collector = None
