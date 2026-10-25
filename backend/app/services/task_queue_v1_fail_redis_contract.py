"""Execute v1 failure Redis transitions without queue ownership."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.task_queue_contract import Task
from app.services.task_queue_keys import (
    _HEARTBEAT_PREFIX,
    _TASK_PREFIX,
    _dead_key,
    _p_key,
    _retry_key,
)
from app.services.task_queue_v1_transition_contract import build_v1_fail_dead_payload

logger = logging.getLogger("postgraduate-ai.task-queue")


async def execute_v1_fail_retry(
    get_client: Callable[[], Awaitable[Any | None]],
    load_scripts: Callable[[Any], Awaitable[None]],
    evalsha: Callable[..., Awaitable[Any]],
    task: Task,
    task_id: str,
    task_type: str,
    token: str | None,
    delay: int,
    error: str,
        metrics: dict[str, int],
) -> bool:
    """Run the retry Lua transition and return the historical boolean result."""
    client = await get_client()
    if client is None:
        return False
    try:
        await load_scripts(client)
        result = await evalsha(
            client,
            "_lua_fail_retry",
            4,
            _p_key(task_type),  # KEYS[1]: processing_key
            _retry_key(task_type),  # KEYS[2]: retry_key
            _TASK_PREFIX,  # KEYS[3]: task_hash_prefix
            _HEARTBEAT_PREFIX,  # KEYS[4]: heartbeat_prefix
            task_id,  # ARGV[1]: task_id
            str(time.time() + delay),  # ARGV[2]: retry_at
            json.dumps(task.to_dict(), default=str),  # ARGV[3]: task_json
            token,  # ARGV[4]: owner_token
            str(task.retry_count),  # ARGV[5]: retry_count
            error[:200],  # ARGV[6]: error
        )
        if result == 0:
            metrics["owner_fencing_rejected"] += 1
            logger.warning(
                "Fail/retry rejected (owner mismatch): task_id=%s",
                task_id,
            )
            return False
        return result != 0
    finally:
        await client.aclose()


async def execute_v1_fail_dead(
    get_client: Callable[[], Awaitable[Any | None]],
    load_scripts: Callable[[Any], Awaitable[None]],
    evalsha: Callable[..., Awaitable[Any]],
    task_or_id: Task | str,
    task_id: str,
    task_type: str,
    token: str | None,
    error: str,
    metrics: dict[str, int],
    *,
    dead_max: int = 1000,
) -> bool:
    """Run the dead-letter Lua transition and return the historical result."""
    client = await get_client()
    if client is None:
        return False
    try:
        await load_scripts(client)
        result = await evalsha(
            client,
            "_lua_fail_dead",
            4,
            _p_key(task_type),  # KEYS[1]: processing_key
            _dead_key(task_type),  # KEYS[2]: dead_key
            _TASK_PREFIX,  # KEYS[3]: task_hash_prefix
            _HEARTBEAT_PREFIX,  # KEYS[4]: heartbeat_prefix
            task_id,  # ARGV[1]: task_id
            build_v1_fail_dead_payload(task_or_id),  # ARGV[2]: task_json
            token,  # ARGV[3]: owner_token
            str(dead_max),  # ARGV[4]: dead_max
        )
        if result == 0:
            metrics["owner_fencing_rejected"] += 1
            logger.warning(
                "Fail/dead rejected (owner mismatch): task_id=%s",
                task_id,
            )
            return False
        return result != 0
    finally:
        await client.aclose()
