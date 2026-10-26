"""Coordinate a single pipeline pass without changing its public entry signature."""

from __future__ import annotations

from functools import partial
from typing import Any

from app.features.pipeline_single_pass_checkpoint import (
    finalize_pass_checkpoint,
    initialize_pass_checkpoint,
    restore_pass_artifacts,
)
from app.features.pipeline_single_pass_input import (
    begin_single_pass,
    prepare_pass_data,
    resolve_pass_vision,
)
from app.features.pipeline_single_pass_loop import execute_pass_loop
from app.features.pipeline_single_pass_result import finish_single_pass
from app.features.pipeline_single_pass_state import (
    SinglePassRequest,
    SinglePassState,
    resolve_pass_port,
)


async def run_single_pass(pipeline: Any, arguments: dict, *, namespace: dict) -> dict:
    """Build typed inputs from the historical entry's keyword-only arguments."""
    request = SinglePassRequest(
        **{key: value for key, value in arguments.items() if key != "self"}
    )
    state = SinglePassState(pipeline, request)
    state.options = request.opts
    ports = partial(resolve_pass_port, namespace)
    begin_single_pass(state, ports=ports)
    await resolve_pass_vision(state, ports=ports)
    prepare_pass_data(state, ports=ports)
    await initialize_pass_checkpoint(state, ports=ports)
    restore_pass_artifacts(state, ports=ports)
    await execute_pass_loop(state, ports=ports)
    await finalize_pass_checkpoint(state, ports=ports)
    return finish_single_pass(state, ports=ports)
