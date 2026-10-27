"""Preserve owned terminal policies while separating business and wall-clock timeouts."""

from __future__ import annotations

from app.services.worker_claimed_state import ClaimedTaskState


async def supervise_claimed_task(state: ClaimedTaskState) -> None:
    try:
        await wait_for_claimed_business(state)
        was_cancelled = state.process_task.cancelled()
        if was_cancelled or state.owner_lost.is_set():
            if was_cancelled:
                state.namespace["logger"].warning(
                    "v2 Owner lost, skipping complete/fail: task_id=%s", state.task.task_id
                )
        else:
            await complete_claimed_task(state)
    except state.namespace["asyncio"].CancelledError:
        raise
    except state.namespace["FencingRejectedError"]:
        state.namespace["logger"].warning(
            "v2 DB fencing rejected (stale worker): task_id=%s type=%s gen=%d",
            state.task.task_id,
            state.task.task_type,
            state.task.generation,
        )
        state.namespace["queue_metrics"]["owner_fencing_rejected"] += 1
    except Exception as e:
        state.namespace["logger"].exception(
            "v2 Task failed: task_id=%s type=%s", state.task.task_id, state.task.task_type
        )
        if state.owner_lost.is_set():
            state.namespace["queue_metrics"]["owner_fencing_rejected"] += 1
        else:
            try:
                await state.namespace["_fail_with_retry_v2"](state.task, str(e)[:500])
            except Exception as fe:
                state.namespace["logger"].warning(
                    "v2 Fail error: task_id=%s error=%s", state.task.task_id, fe
                )


async def wait_for_claimed_business(state: ClaimedTaskState) -> None:
    try:
        await state.namespace["asyncio"].wait_for(
            state.process_task, timeout=state.namespace["_PROCESS_HARD_DEADLINE_SEC"]
        )
    except state.namespace["asyncio"].CancelledError:
        state.namespace["logger"].warning(
            "v2 Processing cancelled (owner lost): task_id=%s", state.task.task_id
        )
        state.namespace["queue_metrics"]["owner_fencing_rejected"] += 1
    except state.namespace["asyncio"].TimeoutError:
        if state.process_task.done() and (not state.process_task.cancelled()):
            raise
        state.namespace["logger"].critical(
            "v2 Processing exceeded hard deadline (%ds): task_id=%s type=%s — marking failed",
            state.namespace["_PROCESS_HARD_DEADLINE_SEC"],
            state.task.task_id,
            state.task.task_type,
        )
        state.namespace["queue_metrics"]["hard_deadline_exceeded"] += 1
        try:
            await state.namespace["_fail_with_retry_v2"](
                state.task, "hard wall-clock deadline exceeded"
            )
        except Exception as fe:
            state.namespace["logger"].warning(
                "v2 Fail after hard deadline error: task_id=%s error=%s", state.task.task_id, fe
            )


async def complete_claimed_task(state: ClaimedTaskState) -> None:
    try:
        ok = await state.namespace["_complete_with_retry_v2"](state.task)
        if ok == 1:
            state.namespace["logger"].info("v2 Task completed: task_id=%s", state.task.task_id)
        elif ok == 0:
            state.namespace["logger"].warning(
                "v2 Complete owner mismatch: task_id=%s", state.task.task_id
            )
            state.namespace["queue_metrics"]["owner_fencing_rejected"] += 1
        elif ok == -1:
            state.namespace["logger"].warning(
                "v2 Complete generation mismatch: task_id=%s", state.task.task_id
            )
            state.namespace["queue_metrics"]["owner_fencing_rejected"] += 1
    except Exception as e:
        state.namespace["logger"].warning(
            "v2 Complete error: task_id=%s error=%s", state.task.task_id, e
        )
