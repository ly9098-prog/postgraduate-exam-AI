"""Execute the one-at-a-time v1-to-v2 Redis drain transition."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.task_queue_keys import (
    _TASK_PREFIX,
    _V2_IDEMPOTENCY_PREFIX,
    _V2_TASK_PREFIX,
    _q_key,
    _v2_corrupt_key,
    _v2_q_key,
)
from app.services.task_queue_v1_to_v2_contract import parse_v1_to_v2_result

logger = logging.getLogger("postgraduate-ai.task-queue")


async def execute_v1_to_v2_drain(
    get_client: Callable[[], Awaitable[Any | None]],
    load_scripts: Callable[[Any], Awaitable[None]],
    evalsha: Callable[..., Awaitable[Any]],
    *,
    task_type: str,
    batch_size: int,
    max_ready: int,
    idempotent_ttl: int,
    corrupt_max: int,
    tombstone_ttl: int,
) -> int:
    client = await get_client()
    if client is None:
        return 0
    migrated = 0
    try:
        await load_scripts(client)
        for _ in range(batch_size):
            raw = await evalsha(
                client,
                "_lua_drain_one_v1_to_v2",
                6,
                _q_key(task_type),
                _TASK_PREFIX,
                _v2_q_key(task_type),
                _V2_TASK_PREFIX,
                _V2_IDEMPOTENCY_PREFIX,
                _v2_corrupt_key(task_type),
                task_type,
                str(idempotent_ttl),
                str(max_ready),
                str(corrupt_max),
                str(tombstone_ttl),
            )
            step = parse_v1_to_v2_result(raw)
            if not step.should_continue or step.should_stop:
                _log_drain_stop(step, task_type)
                break
            if step.is_migrated:
                migrated += 1
            elif step.outcome == "duplicate":
                logger.info(
                    "v1→v2 drain: task %s already in v2, skipping", step.task_id
                )
            elif step.outcome == "corrupt":
                logger.warning(
                    "v1→v2 drain: task %s preserved as corrupt", step.task_id
                )
        return migrated
    finally:
        await client.aclose()


def _log_drain_stop(step, task_type: str) -> None:
    if step.outcome == "queue_full":
        logger.warning(
            "v1→v2 drain paused: v2 ready queue full for %s",
            task_type,
        )
    elif step.should_stop:
        logger.warning(
            "v1→v2 drain paused: task %s has v2 state without guard",
            step.task_id,
        )
