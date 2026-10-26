"""Stage success and failure ownership for a single pipeline pass."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_single_pass_checkpoint import (
    checkpoint_completed_stage,
    checkpoint_failed_stage,
)
from app.features.pipeline_single_pass_state import SinglePassState


async def complete_pass_stage(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> None:
    """Merge stage output, observe metrics and clean inputs before checkpointing."""
    state.result = await state.current_stage.run_async(**state.data)
    if ports("isinstance")(state.result, ports("dict")):
        if state.result.get("warnings"):
            state.current_stage.warnings.extend(state.result["warnings"])
        state.data.update(state.result)
        if "normalized_blocks" in state.result:
            state.data["normalized_block_count"] = ports("len")(
                state.result["normalized_blocks"]
            )
    ports("_update_stage_metrics")(state.current_stage, state.data, state.result)
    ports("complete_stage_data")(
        state.current_name,
        state.data,
        state.result,
        warning=lambda *args: ports("logger").warning(*args),
    )
    await checkpoint_completed_stage(state, ports=ports)


async def handle_stage_failure(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> bool:
    """Fail the pass, checkpoint and release early inputs; signal only early breaks."""
    state.status = "failed"
    state.errors.append(
        f"stage '{state.current_name}' failed: {state.current_stage.error}"
    )
    await checkpoint_failed_stage(state, ports=ports)
    if state.current_name in ("extract", "normalize_text", "ocr_correction"):
        state.data.pop("file_content", None)
        state.data.pop("file_path", None)
        state.data.pop("page_images", None)
        if state.current_name in ("extract", "normalize_text"):
            return True
    ports("logger").warning(
        "Stage '%s' failed, continuing with partial results", state.current_name
    )
    return False


async def execute_pass_stage(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> bool:
    """Catch ordinary execution/effect errors; let cancellation propagate."""
    try:
        await complete_pass_stage(state, ports=ports)
    except ports("Exception"):
        return await handle_stage_failure(state, ports=ports)
    return False
