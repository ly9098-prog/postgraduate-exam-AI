"""Build v1 dead-list diagnostics and purge plans without Redis ownership."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


def build_v1_dead_entry(task_id: str, raw_payload: Any) -> dict:
    """Return a v1 dead-list entry, preserving corrupt/expired diagnostics."""
    if not raw_payload:
        return {"task_id": task_id, "error": "hash_expired"}
    try:
        return json.loads(raw_payload)
    except json.JSONDecodeError:
        return {"task_id": task_id, "error": "corrupt_payload"}


@dataclass(slots=True)
class V1DeadPurgePlan:
    remove_from_dead: bool
    delete_hash: bool


def build_v1_dead_purge_plan(
    raw_payload: Any,
    *,
    now: float,
    max_age_sec: int,
) -> V1DeadPurgePlan:
    """Preserve the historical v1 purge rules for one dead-list entry."""
    if not raw_payload:
        return V1DeadPurgePlan(remove_from_dead=True, delete_hash=False)
    try:
        task_dict = json.loads(raw_payload)
        updated = task_dict.get("updated_at", 0)
    except json.JSONDecodeError:
        return V1DeadPurgePlan(remove_from_dead=True, delete_hash=False)
    if now - updated > max_age_sec:
        return V1DeadPurgePlan(remove_from_dead=True, delete_hash=True)
    return V1DeadPurgePlan(remove_from_dead=False, delete_hash=False)
