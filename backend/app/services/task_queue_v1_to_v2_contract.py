"""Interpret v1-to-v2 migration outcomes without owning Redis state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class V1ToV2MigrationStep:
    outcome: str
    task_id: str

    @property
    def should_continue(self) -> bool:
        return bool(self.outcome) and self.outcome != "empty"

    @property
    def should_stop(self) -> bool:
        return self.outcome in {"queue_full", "conflict"}

    @property
    def is_migrated(self) -> bool:
        return self.outcome == "migrated"


def parse_v1_to_v2_result(result: Any) -> V1ToV2MigrationStep:
    """Preserve the historical empty/absent and two-element result handling."""
    if not result or result[0] == "empty":
        return V1ToV2MigrationStep(outcome="empty", task_id="")
    outcome, task_id = result
    return V1ToV2MigrationStep(outcome=outcome, task_id=task_id)
