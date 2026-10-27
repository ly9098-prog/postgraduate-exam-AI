"""Resources owned by one already-acquired dispatcher slot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ClaimedTaskState:
    task: Any
    lease_sec: int
    semaphore: Any
    namespace: dict[str, Any]
    log_tokens: Any = None
    log_bound: bool = False
    owner_lost: Any = None
    heartbeat_task: Any = None
    process_task: Any = None
    cancel_watcher: Any = None
    children_ready: bool = False
