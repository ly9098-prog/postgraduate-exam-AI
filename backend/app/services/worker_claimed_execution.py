"""Own claimed-task startup, child creation and guaranteed slot cleanup."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.worker_claimed_cleanup import (
    cleanup_claimed_resources,
    retain_claimed_cleanup_failure,
)
from app.services.worker_claimed_outcome import supervise_claimed_task
from app.services.worker_claimed_state import ClaimedTaskState


async def run_claimed_task(
    task: Any,
    lease_sec: int,
    semaphore: Any,
    *,
    namespace: dict[str, Any],
    bind_context: Callable[..., Any],
    generate_request_id: Callable[[str], str],
    generate_trace_id: Callable[[str], str],
    reset_context: Callable[..., None],
) -> None:
    state = ClaimedTaskState(task, lease_sec, semaphore, namespace)
    primary: BaseException | None = None
    try:
        bind_claimed_context(state, bind_context, generate_request_id, generate_trace_id)
        start_claimed_children(state)
        await supervise_claimed_task(state)
    except BaseException as error:
        primary = error
        raise
    finally:
        await cleanup_claimed_resources(state, reset_context, primary)


def bind_claimed_context(
    state: ClaimedTaskState,
    bind_context: Callable[..., Any],
    generate_request_id: Callable[[str], str],
    generate_trace_id: Callable[[str], str],
) -> None:
    pipeline_id = str(
        state.task.payload.get("pipeline_id")
        or state.task.payload.get("job_id")
        or state.task.task_id
    )
    trace_id = state.task.trace_id or generate_trace_id("tr_job")
    request_id = state.task.request_id or generate_request_id("req_job")
    state.log_tokens = bind_context(
        trace_id=trace_id,
        request_id=request_id,
        job_id=state.task.task_id,
        pipeline_id=pipeline_id,
    )
    state.log_bound = True


def start_claimed_children(state: ClaimedTaskState) -> None:
    ports = state.namespace
    state.owner_lost = ports["asyncio"].Event()
    state.heartbeat_task = spawn_claimed_child(
        ports["asyncio"].create_task,
        ports["_v2_heartbeat_loop_with_lease_window"](
            state.task, state.lease_sec, state.owner_lost
        ),
    )
    state.process_task = spawn_claimed_child(
        ports["asyncio"].create_task, ports["_process_task_v2"](state.task)
    )
    state.cancel_watcher = spawn_claimed_child(
        ports["asyncio"].create_task,
        ports["_cancel_on_owner_loss"](state.process_task, state.owner_lost),
    )
    state.children_ready = True


def spawn_claimed_child(create_task: Callable[..., Any], coroutine: Any) -> Any:
    try:
        return create_task(coroutine)
    except BaseException as error:
        try:
            coroutine.close()
        except BaseException as close_error:
            retain_claimed_cleanup_failure(error, close_error)
        raise
