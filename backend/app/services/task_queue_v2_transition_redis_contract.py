"""Execute v2 enqueue/complete Redis transitions without queue ownership."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.task_queue_contract import EnqueueResult, Task
from app.services.task_queue_keys import (
    _V2_FENCING_PREFIX,
    _V2_HEARTBEAT_PREFIX,
    _V2_IDEMPOTENCY_PREFIX,
    _V2_RETRY_PREFIX,
    _V2_TASK_PREFIX,
    _v2_retry_key,
    _v2_p_key,
    _v2_q_key,
    _v2_task_hash_key,
)
from app.services.task_queue_v2_completion_contract import (
    apply_v2_completed_result,
    build_v2_completed_payload,
)
from app.services.task_queue_v2_enqueue_contract import (
    v2_enqueue_duplicate,
    v2_enqueue_internal_error,
    v2_enqueue_queue_full,
)

logger = logging.getLogger("postgraduate-ai.task-queue")


async def execute_v2_enqueue(
    get_client: Callable[[], Awaitable[Any | None]],
    load_scripts: Callable[[Any], Awaitable[None]],
    evalsha: Callable[..., Awaitable[Any]],
    *,
    task_id: str,
    task_type: str,
    task_json: str,
    idempotent: bool,
    max_ready: int,
    idempotent_ttl: int,
    metrics: dict[str, int],
) -> EnqueueResult | None:
    """Return the enqueue result, or None when Redis becomes unavailable."""
    client = await get_client()
    if client is None:
        return None
    try:
        await load_scripts(client)
        if idempotent:
            result = await evalsha(
                client,
                "_lua_enqueue_v2",
                3,
                _v2_q_key(task_type),
                _V2_TASK_PREFIX,
                _V2_IDEMPOTENCY_PREFIX,
                task_id,
                task_json,
                str(idempotent_ttl),
                str(max_ready),
            )
        else:
            result = await evalsha(
                client,
                "_lua_enqueue_non_idempotent_v2",
                2,
                _v2_q_key(task_type),
                _V2_TASK_PREFIX,
                task_id,
                task_json,
                str(max_ready),
            )
        return interpret_v2_enqueue_result(
            result, task_id=task_id, task_type=task_type, metrics=metrics
        )
    finally:
        await client.aclose()


def interpret_v2_enqueue_result(
    result: Any,
    *,
    task_id: str,
    task_type: str,
    metrics: dict[str, int],
) -> EnqueueResult:
    if result == "__duplicate__":
        logger.info("v2 Duplicate task: task_id=%s", task_id)
        metrics["duplicate_enqueue_prevented"] += 1
        return v2_enqueue_duplicate(task_id)
    if result == "__queue_full__":
        logger.warning("v2 Queue full: task_id=%s type=%s", task_id, task_type)
        metrics["enqueue_rejected"] += 1
        return v2_enqueue_queue_full()
    if result is None:
        logger.error("v2 Enqueue nil: task_id=%s type=%s", task_id, task_type)
        return v2_enqueue_internal_error()
    return EnqueueResult(accepted=True, task_id=task_id)


async def execute_v2_complete(
    get_client: Callable[[], Awaitable[Any | None]],
    load_scripts: Callable[[Any], Awaitable[None]],
    evalsha: Callable[..., Awaitable[Any]],
    task_or_id: Task | str,
    *,
    task_id: str,
    task_type: str,
    owner_token: str,
    completed_ttl: int,
    tombstone_ttl: int,
    metrics: dict[str, int],
) -> int:
    client = await get_client()
    if client is None:
        return 0
    try:
        await load_scripts(client)
        updated_at = _completed_updated_at()
        task_json = await _build_v2_complete_payload(
            client,
            task_or_id,
            task_id=task_id,
            task_type=task_type,
            updated_at=updated_at,
        )
        raw = await _run_v2_complete_script(
            client,
            evalsha,
            task_id=task_id,
            task_type=task_type,
            owner_token=owner_token,
            task_json=task_json,
            completed_ttl=completed_ttl,
            tombstone_ttl=tombstone_ttl,
        )
        return _interpret_v2_complete_result(
            raw,
            task_or_id,
            task_id=task_id,
            updated_at=updated_at,
            metrics=metrics,
        )
    finally:
        await client.aclose()


async def _run_v2_complete_script(
    client,
    evalsha,
    *,
    task_id: str,
    task_type: str,
    owner_token: str,
    task_json: str,
    completed_ttl: int,
    tombstone_ttl: int,
):
    """Run the fenced complete script with the historical key/ARGV layout."""
    return await evalsha(
        client,
        "_lua_complete_v2",
        5,
        _v2_p_key(task_type),
        _v2_retry_key(task_type),
        _V2_TASK_PREFIX,
        _V2_HEARTBEAT_PREFIX,
        _V2_FENCING_PREFIX,
        task_id,
        owner_token,
        task_json,
        str(completed_ttl),
        str(tombstone_ttl),
    )


async def _build_v2_complete_payload(
    client,
    task_or_id: Task | str,
    *,
    task_id: str,
    task_type: str,
    updated_at: float,
) -> str:
    """Build the completed payload, reading the hash only for bare ids."""
    if isinstance(task_or_id, Task):
        return build_v2_completed_payload(
            task_or_id,
            updated_at=updated_at,
        )
    current = await client.hget(_v2_task_hash_key(task_id), "data")
    return build_v2_completed_payload(
        task_id,
        task_type=task_type,
        current_payload=current,
        updated_at=updated_at,
    )


def _interpret_v2_complete_result(
    raw,
    task_or_id: Task | str,
    *,
    task_id: str,
    updated_at: float,
    metrics: dict[str, int],
) -> int:
    """Map the Lua result onto history, logging, and metrics."""
    result = int(raw) if raw is not None else 0
    if result == 0:
        logger.warning("v2 Complete owner mismatch: task_id=%s", task_id)
        metrics["owner_fencing_rejected"] += 1
    elif result == -1:
        logger.warning("v2 Complete generation mismatch: task_id=%s", task_id)
        metrics["owner_fencing_rejected"] += 1
    else:
        apply_v2_completed_result(task_or_id, updated_at=updated_at)
        logger.info("v2 Task completed: task_id=%s", task_id)
    return result


def _completed_updated_at() -> float:
    import time

    return time.time()
