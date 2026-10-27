"""Captured task identity and work copies owned by one handler invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkerTaskState:
    task: Any
    task_type: str
    payload: Any
    pipeline_id: Any
    fence_record_id: Any
    namespace: dict[str, Any]
    fence_token: Any = None
    staging_work_copies: list[str] = field(default_factory=list)

    async def resolve_owned_staging(self, staging_id: str) -> str:
        if not staging_id:
            return ""
        work_path = await self.namespace["_resolve_staging_path"](
            staging_id, self.task.owner_token, self.task.generation
        )
        self.staging_work_copies.append(work_path)
        return work_path

    def lookup(self, name: str) -> Any:
        if name in self.namespace:
            return self.namespace[name]
        builtins = self.namespace["__builtins__"]
        return builtins[name] if isinstance(builtins, dict) else getattr(builtins, name)
