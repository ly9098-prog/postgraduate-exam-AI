"""Resolve and apply v1 heartbeat state without Redis ownership."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.services.task_queue_contract import Task


@dataclass(slots=True)
class V1HeartbeatIdentity:
    task_id: str
    task_type: str
    owner_token: str

    def is_valid(self) -> bool:
        return bool(self.task_id and self.task_type)

    @property
    def fenced(self) -> bool:
        return bool(self.owner_token)


def resolve_v1_heartbeat_identity(
    task_or_id: Task | str | tuple[Any, ...],
    *,
    task_type: str | None = None,
) -> V1HeartbeatIdentity:
    """Return the historical Task/tuple/string identity shape."""
    if isinstance(task_or_id, Task):
        return V1HeartbeatIdentity(
            task_or_id.task_id,
            task_or_id.task_type,
            task_or_id.owner_token,
        )
    if isinstance(task_or_id, tuple):
        task_id, tt_hint, token = task_or_id
        return V1HeartbeatIdentity(task_id, task_type or tt_hint, token)
    return V1HeartbeatIdentity(task_or_id, task_type or "", "")


def apply_v1_heartbeat_result(
    task_or_id: Task | str | tuple[Any, ...],
    *,
    result: int,
    lease_expires_at: float,
) -> bool:
    """Apply an accepted heartbeat and return the historical boolean outcome."""
    if result == 0:
        return False
    if isinstance(task_or_id, Task):
        task_or_id.lease_expires_at = lease_expires_at
    return True


def v1_heartbeat_expiry(lease_sec: int, *, now: float | None = None) -> float:
    return (time.time() if now is None else now) + lease_sec
