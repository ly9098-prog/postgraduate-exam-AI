"""Pure v2 queue-health rules shared by Redis-backed health queries."""

from __future__ import annotations

import json
from typing import Any


def v2_oldest_ready_age(
    task_id: Any,
    raw_payload: Any,
    *,
    now: float,
) -> float:
    """Return the oldest ready age while preserving historical invalid fallbacks."""
    if not task_id or not raw_payload:
        return 0.0
    try:
        created_at = float(json.loads(raw_payload).get("created_at", 0) or 0)
    except (ValueError, TypeError, json.JSONDecodeError):
        return 0.0
    return max(0.0, now - created_at) if created_at else 0.0
