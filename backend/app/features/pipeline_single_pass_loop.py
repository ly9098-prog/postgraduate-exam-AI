"""Restored-stage skipping, progress callbacks and ordered execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_single_pass_execution import execute_pass_stage
from app.features.pipeline_single_pass_state import SinglePassState


def skip_pass_stage(state: SinglePassState, *, ports: Callable[[str], Any]) -> bool:
    """Skip restored output or isolate review after an earlier failure."""
    if state.current_name in state.artifact_skipped:
        ports("logger").info(
            "Skipping stage '%s' (restored from artifact)", state.current_name
        )
        state.current_stage.status = "completed"
        state.current_stage.duration_ms = 0
        if state.current_name not in state.completed_stages:
            state.completed_stages.append(state.current_name)
        return True
    if state.current_name == "review" and state.status == "failed":
        ports("logger").warning(
            "Skipping 'review' stage: pipeline already failed at prior stage (errors=%s)",
            state.errors,
        )
        state.current_stage.status = "skipped"
        state.current_stage.duration_ms = 0
        return True
    return False


async def report_pass_progress(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> None:
    """Report current statuses and original error list; ignore ordinary observer errors."""
    if state.request.progress_callback:
        try:
            await state.request.progress_callback(
                {n: s.to_dict() for n, s in state.pipeline.stages.items()},
                state.current_name,
                state.errors,
            )
        except ports("Exception"):
            pass


async def execute_pass_loop(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> None:
    """Preserve stage iteration and the missing post-callback on an early break."""
    for name, stage in state.pipeline.stages.items():
        state.current_name, state.current_stage = name, stage
        if skip_pass_stage(state, ports=ports):
            continue
        await report_pass_progress(state, ports=ports)
        if await execute_pass_stage(state, ports=ports):
            break
        await report_pass_progress(state, ports=ports)
