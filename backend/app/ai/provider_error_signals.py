"""Shared provider error markers used by transport and API classification."""

from __future__ import annotations

QUOTA_ERROR_MARKERS = (
    "insufficient_quota",
    "insufficientquota",
    "insufficient_balance",
    "balance_not_enough",
    "billing_hard_limit_reached",
    "arrearage",
    "exceeded your current quota",
    "allocationquota.freetieronly",
    "余额不足",
    "额度已用尽",
    "欠费",
)


def has_quota_error_marker(text: str) -> bool:
    return any(marker in text for marker in QUOTA_ERROR_MARKERS)
