"""Noise Drift Detection — detect changes in OCR code language noise distribution.

Compares the runtime noise-type distribution against a baseline using
KL divergence. A high divergence score indicates the OCR model or input
distribution has changed (e.g. PaddleOCR version upgrade, new question
source), which may require updating noise patterns.

Exports:
    detect_drift — main entry, compares runtime vs baseline
    DEFAULT_BASELINE — initial noise type distribution estimate
    DRIFT_THRESHOLD — default KL divergence threshold
"""

from __future__ import annotations

import math
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default baseline distribution (estimated from development stress tests)
# ---------------------------------------------------------------------------

# These values represent the expected noise-type distribution. They are
# estimates and should be updated once production data is available.
DEFAULT_BASELINE: dict[str, float] = {
    "c_cpp_noise": 0.50,
    "python_noise": 0.05,
    "tag_noise": 0.15,
    "lang_label": 0.10,
    "generic_ocr_noise": 0.20,
}

DRIFT_THRESHOLD = 0.15

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _distribution_from_counts(counts: dict[str, int]) -> dict[str, float]:
    """Convert a dict of category counts to a probability distribution.

    Returns an empty dict when the total count is zero.
    """
    total = sum(counts.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counts.items()}


def _kl_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Compute KL(P || Q) with Laplace smoothing.

    KL divergence measures how much the runtime distribution ``q`` differs
    from the baseline ``p``.  Higher values indicate more drift.

    Laplace smoothing (1e-10) prevents division by zero when a category
    appears in one distribution but not the other.
    """
    all_keys = set(p) | set(q)
    divergence = 0.0
    for key in all_keys:
        p_val = p.get(key, 1e-10)
        q_val = q.get(key, 1e-10)
        if p_val > 0 and q_val > 0:
            divergence += p_val * math.log(p_val / q_val)
    return divergence


def _find_top_changed(
    baseline: dict[str, float],
    runtime: dict[str, float],
) -> tuple[str, float]:
    """Find the noise type with the largest absolute probability change.

    Returns:
        (noise_type_name, max_delta)
    """
    top_change = ""
    max_delta = 0.0
    for noise_type in set(baseline) | set(runtime):
        b = baseline.get(noise_type, 0.0)
        r = runtime.get(noise_type, 0.0)
        delta = abs(r - b)
        if delta > max_delta:
            max_delta = delta
            top_change = noise_type
    return top_change, max_delta


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_drift(
    runtime_counts: dict[str, int],
    baseline: dict[str, float] | None = None,
    threshold: float = DRIFT_THRESHOLD,
) -> dict[str, Any]:
    """Detect whether the noise-type distribution has drifted from baseline.

    Args:
        runtime_counts: Observed noise-type counts from the current batch
            (e.g. ``{"c_cpp_noise": 12, "python_noise": 1, ...}``).
        baseline: Expected probability distribution.  Uses
            ``DEFAULT_BASELINE`` when ``None``.
        threshold: KL divergence threshold above which drift is flagged.

    Returns:
        A dict with the following keys:

        - ``drift_detected`` (bool)
        - ``drift_score`` (float, KL divergence)
        - ``top_changed_noise`` (str, noise type with largest change)
        - ``max_delta`` (float, absolute change of top_changed_noise)
        - ``threshold`` (float, threshold used)
        - ``baseline_distribution`` (dict)
        - ``runtime_distribution`` (dict)
    """
    baseline_dist = baseline if baseline is not None else DEFAULT_BASELINE.copy()
    runtime_dist = _distribution_from_counts(runtime_counts)

    if not runtime_dist:
        return {
            "drift_detected": False,
            "drift_score": 0.0,
            "top_changed_noise": "",
            "max_delta": 0.0,
            "threshold": threshold,
            "message": "no_runtime_data",
            "baseline_distribution": baseline_dist,
            "runtime_distribution": {},
        }

    score = _kl_divergence(baseline_dist, runtime_dist)
    top_change, max_delta = _find_top_changed(baseline_dist, runtime_dist)

    return {
        "drift_detected": score > threshold,
        "drift_score": round(score, 4),
        "top_changed_noise": top_change,
        "max_delta": round(max_delta, 4),
        "threshold": threshold,
        "baseline_distribution": baseline_dist,
        "runtime_distribution": runtime_dist,
    }
