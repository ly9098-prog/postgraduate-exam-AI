"""Bind one outbox callback to the runtime's existing durable queue."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.task_queue_service import DurableTaskQueue


def build_outbox_enqueue(
    task_queue: DurableTaskQueue,
) -> Callable[[str, str, dict, int], Awaitable[object]]:
    async def _enqueue_from_outbox(
        task_id: str,
        task_type: str,
        payload: dict,
        schema_version: int,
    ) -> object:
        return await task_queue.enqueue_v2(
            task_type,
            payload,
            task_id=task_id,
            schema_version=schema_version,
        )

    return _enqueue_from_outbox
