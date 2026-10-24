"""Decide which v2 dead-list entries may be purged without Redis ownership."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class V2DeadPurgePlan:
    remove_from_dead: bool
    delete_hash: bool


def build_v2_dead_purge_plan(
    raw_payload: Any,
    *,
    now: float,
    max_age_sec: int,
) -> V2DeadPurgePlan:
    """Preserve the historical purge rules for one dead-list entry.

    Missing and corrupt payloads are removed from the dead list without a hash
    delete. Valid old payloads remove both. Non-object valid JSON retains the
    historical ``AttributeError`` so the caller's existing failure boundary can
    abort the purge.
    """
    if not raw_payload:
        return V2DeadPurgePlan(remove_from_dead=True, delete_hash=False)
    try:
        task_dict = json.loads(raw_payload)
        updated = task_dict.get("updated_at", 0)
    except json.JSONDecodeError:
        return V2DeadPurgePlan(remove_from_dead=True, delete_hash=False)
    if now - updated > max_age_sec:
        return V2DeadPurgePlan(remove_from_dead=True, delete_hash=True)
    return V2DeadPurgePlan(remove_from_dead=False, delete_hash=False)
