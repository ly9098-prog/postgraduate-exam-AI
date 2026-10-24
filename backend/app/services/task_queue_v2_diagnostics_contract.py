"""Build v2 dead/corrupt diagnostic entries without Redis ownership."""

from __future__ import annotations

import json
from typing import Any


def build_v2_dead_entry(task_id: str, raw_payload: Any) -> dict:
    """Return a dead-list entry, preserving corrupt/expired diagnostics."""
    if not raw_payload:
        return {"task_id": task_id, "error": "hash_expired"}
    try:
        return json.loads(raw_payload)
    except json.JSONDecodeError:
        return {"task_id": task_id, "error": "corrupt_payload"}


def build_v2_corrupt_entry(
    task_id: str,
    discovered_at: Any,
    raw_payload: Any,
) -> dict:
    """Return a corrupt-list entry, preserving score and payload precedence."""
    entry = {"task_id": task_id, "discovered_at": discovered_at}
    if not raw_payload:
        return entry
    try:
        entry.update(json.loads(raw_payload))
    except json.JSONDecodeError:
        entry["error"] = "corrupt_payload"
    return entry
