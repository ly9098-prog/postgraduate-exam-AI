"""Build v2 completion payloads without owning Redis state transitions."""

from __future__ import annotations

import json
import time
from typing import Any

from app.services.task_queue_contract import Task, TaskStatus


def build_v2_completed_payload(
    task_or_id: Task | str,
    *,
    task_type: str = "",
    current_payload: str | None = None,
    updated_at: float | None = None,
) -> str:
    """Return the historical completed-task JSON shape for Redis."""
    resolved_updated_at = time.time() if updated_at is None else updated_at
    if isinstance(task_or_id, Task):
        data = task_or_id.to_dict()
        status = TaskStatus.COMPLETED.value
    else:
        data = (
            json.loads(current_payload)
            if current_payload
            else {
                "task_id": task_or_id,
                "task_type": task_type,
                "payload": {},
            }
        )
        status = "completed"

    data.update(
        {
            "status": status,
            "updated_at": resolved_updated_at,
            "lease_expires_at": 0.0,
            "owner_token": "",
            "error": "",
        }
    )
    return json.dumps(data, default=str)


def apply_v2_completed_result(
    task_or_id: Task | str,
    *,
    updated_at: float,
) -> None:
    """Apply an accepted completion to the in-memory task snapshot."""
    if isinstance(task_or_id, Task):
        task_or_id.status = TaskStatus.COMPLETED
        task_or_id.updated_at = updated_at
        task_or_id.lease_expires_at = 0.0
        task_or_id.error = ""


def v2_complete_unavailable(error: Any) -> str:
    return f"Redis unavailable during complete: {error}"
