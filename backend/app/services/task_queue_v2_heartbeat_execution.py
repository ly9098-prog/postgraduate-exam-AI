"""Own the v2 heartbeat script-client lifetime and post-close result handling."""

from __future__ import annotations

from typing import Any


async def execute_v2_heartbeat(
    queue: Any,
    task_or_id: Any,
    *,
    task_id: str,
    task_type: str,
    owner_token: str,
    lease_sec: int,
    namespace: dict[str, Any],
) -> int:
    client = await queue._get_script_client()
    if client is None:
        return 0
    try:
        await queue._load_scripts(client)
        result = await queue._evalsha_or_reload(
            client,
            "_lua_heartbeat_v2",
            4,
            namespace["_v2_p_key"](task_type),
            namespace["_V2_HEARTBEAT_PREFIX"],
            namespace["_V2_TASK_PREFIX"],
            namespace["_V2_FENCING_PREFIX"],
            task_id,
            str(lease_sec),
            owner_token,
        )
    except BaseException as error:
        await _close_after_failure(client, error)
        raise
    await client.aclose()
    return _apply_result(
        result, task_or_id, task_id=task_id, lease_sec=lease_sec, namespace=namespace
    )


async def _close_after_failure(client: Any, error: BaseException) -> None:
    try:
        await client.aclose()
    except BaseException as cleanup_error:
        try:
            BaseException.add_note(
                error, f"v2 heartbeat cleanup also failed ({type(cleanup_error).__name__})"
            )
        except BaseException:
            # A diagnostic annotation must not replace the original queue failure.
            pass


def _apply_result(
    result: Any,
    task_or_id: Any,
    *,
    task_id: str,
    lease_sec: int,
    namespace: dict[str, Any],
) -> int:
    result = int(result) if result is not None else 0
    mismatch = namespace["v2_heartbeat_mismatch"](result)
    if mismatch is not None:
        namespace["logger"].warning(
            "v2 Heartbeat %s mismatch: task_id=%s",
            mismatch,
            task_id,
        )
        namespace["queue_metrics"]["owner_fencing_rejected"] += 1
    else:
        namespace["apply_v2_heartbeat_result"](task_or_id, result=result, lease_sec=lease_sec)
    return result
