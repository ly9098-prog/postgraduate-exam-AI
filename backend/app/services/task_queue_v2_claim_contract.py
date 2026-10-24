"""Validate and materialize claimed v2 tasks without Redis ownership."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from app.services.task_queue_contract import Task, TaskStatus


@dataclass(slots=True)
class V2ClaimResult:
    task: Task | None
    corrupt_error: str | None


def build_v2_claimed_task(
    claim: list[str] | tuple[str, ...] | None,
    *,
    task_type: str,
    owner_token: str,
) -> V2ClaimResult:
    """Validate a Redis claim result and build the processing task snapshot."""
    if claim is None or len(claim) != 5:
        return V2ClaimResult(task=None, corrupt_error=None)

    task_id, raw_payload, stored_token, stored_gen, lease_expiry = claim
    try:
        task = Task.from_dict(json.loads(raw_payload))
        if task.task_id != task_id or task.task_type != task_type:
            raise ValueError(
                f"task identity mismatch: hash={task_id}/{task_type} "
                f"payload={task.task_id}/{task.task_type}"
            )
    except Exception as exc:
        return V2ClaimResult(task=None, corrupt_error=f"{task_id}:{str(exc)[:200]}")

    task.status = TaskStatus.PROCESSING
    task.lease_expires_at = float(lease_expiry or 0)
    task.owner_token = stored_token or owner_token
    task.generation = int(stored_gen or 0)
    task.updated_at = time.time()
    return V2ClaimResult(task=task, corrupt_error=None)


def v2_dequeue_unavailable(error: Any) -> str:
    return f"Redis unavailable during dequeue: {error}"
