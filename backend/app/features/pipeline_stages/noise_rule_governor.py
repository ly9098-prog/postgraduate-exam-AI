"""Adaptive Rule Governance — auto-adjust noise cleaning policy based on metrics.

Monitors the false-positive suspected rate (lines classified as noise but
protected by safety guards).  When the FP rate exceeds a threshold, the
governor recommends switching to ``safe_mode`` (confidence threshold 0.6 → 0.9)
to reduce removal aggressiveness.

Exports:
    evaluate_policy — main entry, returns adjusted policy + change log
    DEFAULT_POLICY — default noise cleaning policy
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default policy
# ---------------------------------------------------------------------------

DEFAULT_POLICY: dict[str, Any] = {
    "safe_mode": False,
    "language_weights": {
        "c_cpp_noise": 1.0,
        "python_noise": 1.0,
        "tag_noise": 1.0,
        "lang_label": 1.0,
        "generic_ocr_noise": 1.0,
    },
}

# When FP rate is below this threshold → normal mode (threshold 0.6).
_FP_RATE_LOW = 0.02
# When FP rate is above this threshold → safe mode (threshold 0.9).
_FP_RATE_HIGH = 0.10


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_policy(
    false_positive_suspected_count: int = 0,
    total_protected_count: int = 0,
    total_removed_count: int = 0,
    current_policy: dict | None = None,
) -> dict[str, Any]:
    """Evaluate current policy against observed metrics and suggest adjustments.

    The governor computes the effective false-positive rate::

        fp_rate = false_positive_suspected / (removed + protected)

    Rules:

    - ``fp_rate > FP_RATE_HIGH (0.10)`` → enable safe_mode (threshold 0.9)
    - ``fp_rate < FP_RATE_LOW (0.02)`` → disable safe_mode (threshold 0.6)
    - Otherwise → keep current setting

    Args:
        false_positive_suspected_count: Lines classified as noise then protected
            by a safety guard (from ``NoiseMetrics.false_positive_suspected_count``).
        total_protected_count: Total lines protected (from
            ``NoiseMetrics.protected_lines_count``).
        total_removed_count: Total lines actually removed (from
            ``NoiseMetrics.removed_lines_count``).
        current_policy: The current policy dict (uses ``DEFAULT_POLICY``
            when ``None``).

    Returns:
        A dict with:
        - ``policy`` (updated policy dict)
        - ``changes`` (list of human-readable change descriptions)
        - ``false_positive_rate`` (float)
    """
    policy = dict(current_policy or DEFAULT_POLICY)

    total_decisions = total_removed_count + total_protected_count
    if total_decisions == 0:
        return {
            "policy": policy,
            "changes": ["no_data_available"],
            "false_positive_rate": 0.0,
        }

    false_positive_rate = false_positive_suspected_count / max(total_decisions, 1)
    changes: list[str] = []

    previous_safe_mode = policy.get("safe_mode", False)
    if false_positive_rate > _FP_RATE_HIGH:
        if not previous_safe_mode:
            policy["safe_mode"] = True
            changes.append(
                f"safe_mode_enabled: fp_rate={false_positive_rate:.3f} "
                f"> threshold={_FP_RATE_HIGH}"
            )
    elif false_positive_rate < _FP_RATE_LOW and previous_safe_mode:
        policy["safe_mode"] = False
        changes.append(
            f"safe_mode_disabled: fp_rate={false_positive_rate:.3f} "
            f"< threshold={_FP_RATE_LOW}"
        )

    if not changes:
        changes.append("no_change_needed")

    return {
        "policy": policy,
        "changes": changes,
        "false_positive_rate": round(false_positive_rate, 4),
    }
