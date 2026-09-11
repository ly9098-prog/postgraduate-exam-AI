"""Noise Metrics Observability Layer — metrics collection for code language noise cleaning.

Provides ``NoiseMetrics`` (per-document dataclass) and ``NoiseMetricsCollector``
that records statistics during the cleaning pass. Designed for integration with
``code_language_noise_layer`` and consumption by ``noise_drift_detector`` and
``noise_rule_governor``.

Exports:
    NoiseMetrics — per-document metrics dataclass
    NoiseMetricsCollector — callable from clean_code_language_noise
    format_metrics_summary — aggregate multiple metrics into a batch summary
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-document metrics
# ---------------------------------------------------------------------------


@dataclass
class NoiseMetrics:
    """Per-document noise metrics for observability and drift detection.

    Properties compute derived values from raw counts:
        noise_ratio — fraction of lines classified as noise
        c_cpp_noise_ratio — fraction of lines classified as C/C++ noise
        risk_level — ``"low"``, ``"medium"``, or ``"high"``
    """

    doc_id: str = ""
    total_lines: int = 0
    total_zone_lines: int = 0
    total_transition_zones: int = 0
    total_noise_detected: int = 0
    removed_lines_count: int = 0
    protected_lines_count: int = 0
    false_positive_suspected_count: int = 0
    noise_type_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # type: ignore[arg-type]
    removed_lines: list[int] = field(default_factory=list)

    @property
    def noise_ratio(self) -> float:
        return self.total_noise_detected / max(self.total_lines, 1)

    @property
    def c_cpp_noise_ratio(self) -> float:
        return self.noise_type_counts.get("c_cpp_noise", 0) / max(self.total_lines, 1)

    @property
    def risk_level(self) -> str:
        if self.noise_ratio > 0.3:
            return "high"
        if self.noise_ratio > 0.1:
            return "medium"
        return "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "noise_ratio": round(self.noise_ratio, 4),
            "c_cpp_noise_ratio": round(self.c_cpp_noise_ratio, 4),
            "risk_level": self.risk_level,
            "total_lines": self.total_lines,
            "total_transition_zones": self.total_transition_zones,
            "total_noise_detected": self.total_noise_detected,
            "removed_lines_count": self.removed_lines_count,
            "protected_lines_count": self.protected_lines_count,
            "false_positive_suspected_count": self.false_positive_suspected_count,
            "noise_type_counts": dict(self.noise_type_counts),
        }


# ---------------------------------------------------------------------------
# Metrics collector — wired into clean_code_language_noise
# ---------------------------------------------------------------------------


class NoiseMetricsCollector:
    """Collects noise metrics incrementally during a cleaning pass.

    Usage::

        collector = NoiseMetricsCollector("doc_001")
        clean_text = clean_code_language_noise(text, _collector=collector)
        report = collector.metrics.to_dict()
    """

    def __init__(self, doc_id: str = "") -> None:
        self.metrics = NoiseMetrics(doc_id=doc_id)

    def record_total_lines(self, count: int) -> None:
        self.metrics.total_lines = count

    def record_zones(self, zones: list[tuple[int, int]]) -> None:
        self.metrics.total_transition_zones = len(zones)
        self.metrics.total_zone_lines = sum(end - start + 1 for start, end in zones)

    def record_classification(self, noise_type: str, _confidence: float) -> None:
        """Record a noise classification result (detected noise only)."""
        if not noise_type:
            return
        self.metrics.total_noise_detected += 1
        self.metrics.noise_type_counts[noise_type] += 1

    def record_removal(self, line_num: int, _noise_type: str) -> None:
        """Record that a noise line was removed."""
        self.metrics.removed_lines_count += 1
        self.metrics.removed_lines.append(line_num)

    def record_protected(self, _noise_type: str) -> None:
        """Record that a noise-classified line was kept (guard fired).

        Every protected line is also counted as a suspected false positive
        since the classifier identified it as noise but a safety guard
        prevented removal — the classifier may have been wrong.
        """
        self.metrics.protected_lines_count += 1
        self.metrics.false_positive_suspected_count += 1


# ---------------------------------------------------------------------------
# Batch aggregation
# ---------------------------------------------------------------------------


def format_metrics_summary(metrics_list: list[NoiseMetrics]) -> dict[str, Any]:
    """Aggregate multiple per-document metrics into a batch summary.

    Args:
        metrics_list: Per-document metrics from a batch run.

    Returns:
        Dict with total counts, averages, noise-type distribution,
        and risk-level distribution.
    """
    if not metrics_list:
        return {}

    total = len(metrics_list)
    total_noise = sum(m.total_noise_detected for m in metrics_list)
    total_removed = sum(m.removed_lines_count for m in metrics_list)
    total_protected = sum(m.protected_lines_count for m in metrics_list)
    total_fp = sum(m.false_positive_suspected_count for m in metrics_list)

    type_counts: dict[str, int] = defaultdict(int)
    for m in metrics_list:
        for noise_type, count in m.noise_type_counts.items():
            type_counts[noise_type] += count

    risk_distribution: dict[str, int] = defaultdict(int)
    for m in metrics_list:
        risk_distribution[m.risk_level] += 1

    return {
        "documents_processed": total,
        "total_noise_detected": total_noise,
        "total_removed_lines": total_removed,
        "total_protected_lines": total_protected,
        "total_false_positive_suspected": total_fp,
        "noise_type_distribution": dict(type_counts),
        "risk_distribution": dict(risk_distribution),
        "avg_noise_ratio": round(sum(m.noise_ratio for m in metrics_list) / total, 4),
        "high_risk_docs": [m.doc_id for m in metrics_list if m.risk_level == "high"],
        "per_document": [m.to_dict() for m in metrics_list],
    }
