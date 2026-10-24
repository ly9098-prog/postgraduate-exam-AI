"""Normalize v2 administrative transition results without Redis ownership."""

from __future__ import annotations

from typing import Any


def normalize_v2_admin_result(result: Any) -> int:
    """Preserve the historical integer Lua result, mapping nil/invalid to 0."""
    try:
        return int(result) if result is not None else 0
    except (TypeError, ValueError):
        return 0


def v2_cancel_reason(reason: str, *, limit: int = 200) -> str:
    """Apply the historical admin cancellation reason cap."""
    return reason[:limit]


def should_log_v2_cancel(result: int) -> bool:
    return result > 0


def v2_mark_corrupt_success(result: Any) -> bool:
    return bool(result)
