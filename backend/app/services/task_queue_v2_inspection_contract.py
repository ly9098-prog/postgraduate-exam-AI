"""Project v2 Redis task hashes for read-only inspection."""

from __future__ import annotations

import json
from typing import Any


def build_v2_task_inspection(
    task_id: str,
    raw_hash: Any,
) -> dict | None:
    """Return the historical task-hash projection, or None when absent."""
    if not raw_hash:
        return None
    result: dict = {"task_id": task_id}
    for key, value in raw_hash.items():
        if key == "data":
            try:
                result[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                result[key] = value
        else:
            result[key] = value
    return result
