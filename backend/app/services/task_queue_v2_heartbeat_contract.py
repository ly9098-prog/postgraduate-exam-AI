"""Resolve and apply v2 heartbeat state without owning Redis transitions."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.services.task_queue_contract import Task


@dataclass(slots=True)
class V2HeartbeatIdentity:
    task_id: str
    task_type: str
    owner_token: str

    def is_valid(self) -> bool:
        return bool(self.task_id and self.task_type and self.owner_token)


def resolve_v2_heartbeat_identity(
    task_or_id: Task | str | tuple[Any, ...],
    *,
    task_type: str | None = None,
) -> V2HeartbeatIdentity:
    """Return the fenced heartbeat identity, including empty invalid fields."""
    if isinstance(task_or_id, Task):
        return V2HeartbeatIdentity(
            task_or_id.task_id,
            task_or_id.task_type,
            task_or_id.owner_token,
        )
    if isinstance(task_or_id, tuple):
        task_id, tt_hint, token = task_or_id
        return V2HeartbeatIdentity(task_id, task_type or tt_hint, token)
    return V2HeartbeatIdentity(task_or_id, task_type or "", "")


def apply_v2_heartbeat_result(
    task_or_id: Task | str | tuple[Any, ...],
    *,
    result: int,
    lease_sec: int,
    now: float | None = None,
) -> None:
    """Apply an accepted heartbeat to the best-effort in-memory lease estimate."""
    if result != 1 or not isinstance(task_or_id, Task):
        return
    # Redis TIME remains authoritative; this is only the worker-side estimate.
    task_or_id.lease_expires_at = (time.time() if now is None else now) + lease_sec


def v2_heartbeat_mismatch(result: int) -> str | None:
    """Map a rejected fencing result to its historical mismatch label."""
    if result == 0:
        return "owner"
    if result == -1:
        return "generation"
    return None
