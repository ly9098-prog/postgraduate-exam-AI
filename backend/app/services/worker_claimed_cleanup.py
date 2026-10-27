"""Settle owned children and always attempt context reset and slot release."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.worker_claimed_state import ClaimedTaskState


async def cleanup_claimed_resources(
    state: ClaimedTaskState,
    reset_context: Callable[..., None],
    primary: BaseException | None,
) -> None:
    first_error = primary
    for child, skip_done in (
        (state.cancel_watcher, False),
        (state.heartbeat_task, False),
        (state.process_task, state.children_ready),
    ):
        try:
            await settle_child(state, child, skip_done)
        except BaseException as error:
            first_error = retain_claimed_cleanup_failure(first_error, error)
    try:
        if state.log_bound:
            reset_context(state.log_tokens)
    except BaseException as error:
        first_error = retain_claimed_cleanup_failure(first_error, error)
    try:
        state.semaphore.release()
    except BaseException as error:
        first_error = retain_claimed_cleanup_failure(first_error, error)
    if primary is None and first_error is not None:
        raise first_error


async def settle_child(state: ClaimedTaskState, child: Any, skip_done: bool) -> None:
    if child is None or (skip_done and child.done()):
        return
    child.cancel()
    try:
        await child
    except (state.namespace["asyncio"].CancelledError, Exception):
        pass


def retain_claimed_cleanup_failure(
    primary: BaseException | None, error: BaseException
) -> BaseException:
    if primary is None:
        return error
    try:
        BaseException.add_note(primary, f"v2 claimed cleanup also failed ({type(error).__name__})")
    except BaseException:
        # Diagnostic annotation failures cannot abandon the owned slot.
        pass
    return primary
