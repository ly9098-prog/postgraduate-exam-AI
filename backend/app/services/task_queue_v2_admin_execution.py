"""Execute administrative Lua transitions with one temporary-client lifetime."""

from __future__ import annotations

from typing import Any


async def execute_v2_mark_corrupt(
    queue: Any, task_id: str, task_type: str, error_summary: str, *, namespace: dict[str, Any]
) -> bool:
    client = await queue._get_script_client()
    if client is None:
        return False
    try:
        await queue._load_scripts(client)
        result = await queue._evalsha_or_reload(
            client,
            "_lua_mark_corrupt_v2",
            5,
            namespace["_v2_p_key"](task_type),
            namespace["_v2_corrupt_key"](task_type),
            namespace["_V2_TASK_PREFIX"],
            namespace["_V2_HEARTBEAT_PREFIX"],
            namespace["_V2_FENCING_PREFIX"],
            task_id,
            error_summary,
            str(namespace["settings"].TASK_QUEUE_CORRUPT_MAX),
            str(namespace["_FENCING_TOMBSTONE_TTL"]),
        )
    except BaseException as error:
        await _close_after_failure(client, error)
        raise
    await client.aclose()
    return namespace["v2_mark_corrupt_success"](result)


async def execute_v2_cancel(
    queue: Any, task_id: str, task_type: str, reason: str, *, namespace: dict[str, Any]
) -> int:
    client = await queue._get_script_client()
    if client is None:
        return 0
    try:
        await queue._load_scripts(client)
        result = await queue._evalsha_or_reload(
            client,
            "_lua_cancel_v2",
            7,
            namespace["_v2_q_key"](task_type),
            namespace["_v2_p_key"](task_type),
            namespace["_v2_retry_key"](task_type),
            namespace["_v2_dead_key"](task_type),
            namespace["_V2_HEARTBEAT_PREFIX"],
            namespace["_V2_TASK_PREFIX"],
            namespace["_V2_FENCING_PREFIX"],
            task_id,
            namespace["v2_cancel_reason"](reason),
            str(namespace["_FENCING_TOMBSTONE_TTL"]),
        )
    except BaseException as error:
        await _close_after_failure(client, error)
        raise
    await client.aclose()
    result = namespace["normalize_v2_admin_result"](result)
    if namespace["should_log_v2_cancel"](result):
        namespace["logger"].info(
            "v2 Cancel (code=%d): task_id=%s type=%s", result, task_id, task_type
        )
    return result


async def execute_v2_reclaim(queue: Any, task_type: str, *, namespace: dict[str, Any]) -> int:
    client = await queue._get_script_client()
    if client is None:
        return 0
    try:
        await queue._load_scripts(client)
        reclaimed = (
            await queue._evalsha_or_reload(
                client,
                "_lua_reaper_v2",
                6,
                namespace["_v2_p_key"](task_type),
                namespace["_v2_q_key"](task_type),
                namespace["_V2_HEARTBEAT_PREFIX"],
                namespace["_V2_TASK_PREFIX"],
                namespace["_v2_corrupt_key"](task_type),
                namespace["_V2_FENCING_PREFIX"],
                "100",
                str(namespace["_get_max_ready"](task_type)),
                str(namespace["settings"].TASK_QUEUE_CORRUPT_MAX),
                str(namespace["_DEAD_HASH_TTL"]),
            )
            or 0
        )
        reclaimed = namespace["normalize_v2_reaper_result"](reclaimed)
    except BaseException as error:
        await _close_after_failure(client, error)
        raise
    await client.aclose()
    if namespace["apply_v2_reaper_result"](reclaimed):
        namespace["logger"].info("v2 Reclaimed %d expired tasks for %s", reclaimed, task_type)
        namespace["queue_metrics"]["reaper_reclaimed"] += reclaimed
    return reclaimed


async def _close_after_failure(client: Any, error: BaseException) -> None:
    try:
        await client.aclose()
    except BaseException as cleanup_error:
        try:
            BaseException.add_note(
                error, f"v2 admin cleanup also failed ({type(cleanup_error).__name__})"
            )
        except BaseException:
            # Diagnostic annotations must not change the service's error policy.
            pass
