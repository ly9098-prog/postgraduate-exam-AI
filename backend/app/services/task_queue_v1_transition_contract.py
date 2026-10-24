"""Prepare v1 complete/fail transitions without Redis ownership."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from app.services.task_queue_contract import Task, TaskStatus


@dataclass(slots=True)
class V1TransitionIdentity:
    task_id: str
    task_type: str
    owner_token: str

    def is_valid(self) -> bool:
        return bool(self.task_id and self.task_type)


def resolve_v1_transition_identity(
    task_or_id: Task | str,
    *,
    task_type: str | None = None,
) -> V1TransitionIdentity:
    """Return the fenced identity, including empty fields for invalid input."""
    if isinstance(task_or_id, Task):
        return V1TransitionIdentity(
            task_or_id.task_id,
            task_or_id.task_type,
            task_or_id.owner_token,
        )
    return V1TransitionIdentity(task_or_id, task_type or "", "")


def apply_v1_failure_attempt(
    task_or_id: Task | str,
    error: str,
    *,
    now: float | None = None,
) -> bool:
    """Apply the first mutation of a v1 failure attempt; return Task ownership."""
    if not isinstance(task_or_id, Task):
        return False
    task_or_id.retry_count += 1
    task_or_id.error = error
    task_or_id.updated_at = time.time() if now is None else now
    return True


def should_v1_retry(task_or_id: Task | str) -> bool:
    """Only Task objects own retry state and can enter the retry path."""
    return isinstance(task_or_id, Task) and (
        task_or_id.retry_count < task_or_id.max_retries
    )


def prepare_v1_retry_task(task: Task, *, now: float | None = None) -> None:
    task.status = TaskStatus.FAILED
    task.updated_at = time.time() if now is None else now


def build_v1_fail_dead_payload(task_or_id: Task | str) -> str:
    """Preserve the historical Task/full-object and string minimal payloads."""
    data = task_or_id.to_dict() if isinstance(task_or_id, Task) else {
        "task_id": task_or_id
    }
    return json.dumps(data, default=str)


def apply_v1_local_retry(task: Task, *, allow_local_fallback: bool) -> None:
    if allow_local_fallback:
        task.status = TaskStatus.PENDING
        task.lease_expires_at = 0
