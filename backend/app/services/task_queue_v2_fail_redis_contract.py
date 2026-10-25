"""Execute v2 failure Redis transitions without queue ownership."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.task_queue_contract import Task
from app.services.task_queue_keys import (
    _V2_DEAD_PREFIX,
    _V2_FENCING_PREFIX,
    _V2_HEARTBEAT_PREFIX,
    _V2_RETRY_PREFIX,
    _V2_TASK_PREFIX,
    _v2_dead_key,
    _v2_p_key,
    _v2_retry_key,
)
from app.services.task_queue_v2_fail_contract import (
    apply_v2_dead_result,
    apply_v2_retry_result,
    build_v2_dead_plan,
)

logger = logging.getLogger("postgraduate-ai.task-queue")


async def execute_v2_fail_retry(
    get_client: Callable[[], Awaitable[Any | None]],
    load_scripts: Callable[[Any], Awaitable[None]],
    evalsha: Callable[..., Awaitable[Any]],
    task: Task,
    retry_plan,
    *,
    error: str,
    retry_max: int,
    dead_max: int,
    tombstone_ttl: int,
    metrics: dict[str, int],
) -> int:
    client = await get_client()
    if client is None:
        return 0
    try:
        await load_scripts(client)
        raw = await evalsha(
            client,
            "_lua_fail_retry_v2",
            6,
            _v2_p_key(task.task_type),
            _v2_retry_key(task.task_type),
            _v2_dead_key(task.task_type),
            _V2_TASK_PREFIX,
            _V2_HEARTBEAT_PREFIX,
            _V2_FENCING_PREFIX,
            task.task_id,
            str(retry_plan.delay),
            retry_plan.task_json,
            task.owner_token,
            str(retry_plan.retry_count),
            error[:200],
            str(retry_max),
            str(dead_max),
            str(tombstone_ttl),
        )
        result = int(raw) if raw is not None else 0
        if result == 1:
            apply_v2_retry_result(task, retry_plan, error)
            logger.warning(
                "v2 Fail/retry (%d/%d, +%ds): task_id=%s",
                retry_plan.retry_count,
                retry_plan.max_retries,
                retry_plan.delay,
                task.task_id,
            )
        elif result == 2:
            dead_plan = build_v2_dead_plan(
                task,
                error,
                retry_count=retry_plan.retry_count,
                updated_at=retry_plan.updated_at,
            )
            apply_v2_dead_result(task, dead_plan, error)
            logger.warning(
                "v2 Fail/retry-full dead: task_id=%s (retry ZSET full)",
                task.task_id,
            )
        elif result in (0, -1):
            logger.warning(
                "v2 Fail/retry %s mismatch: task_id=%s",
                "owner" if result == 0 else "gen",
                task.task_id,
            )
            metrics["owner_fencing_rejected"] += 1
        return result
    finally:
        await client.aclose()


async def execute_v2_fail_dead(
    get_client: Callable[[], Awaitable[Any | None]],
    load_scripts: Callable[[Any], Awaitable[None]],
    evalsha: Callable[..., Awaitable[Any]],
    task_or_id: Task | str,
    *,
    task_id: str,
    task_type: str,
    owner_token: str,
    error: str,
    retry_count: int,
    dead_max: int,
    tombstone_ttl: int,
    metrics: dict[str, int],
) -> int:
    client = await get_client()
    if client is None:
        return 0
    try:
        await load_scripts(client)
        dead_plan = build_v2_dead_plan(
            task_or_id,
            error,
            retry_count=retry_count,
            task_type=task_type,
        )
        raw = await evalsha(
            client,
            "_lua_fail_dead_v2",
            5,
            _v2_p_key(task_type),
            _v2_dead_key(task_type),
            _V2_TASK_PREFIX,
            _V2_HEARTBEAT_PREFIX,
            _V2_FENCING_PREFIX,
            task_id,
            dead_plan.task_json,
            owner_token,
            str(dead_max),
            str(tombstone_ttl),
        )
        result = int(raw) if raw is not None else 0
        if result == 1:
            apply_v2_dead_result(task_or_id, dead_plan, error)
            logger.error("v2 Dead-letter: task_id=%s type=%s", task_id, task_type)
        elif result in (0, -1):
            logger.warning(
                "v2 Fail/dead %s mismatch: task_id=%s",
                "owner" if result == 0 else "gen",
                task_id,
            )
            metrics["owner_fencing_rejected"] += 1
        return result
    finally:
        await client.aclose()
