"""Checkpoint and artifact effects around the single-pass stage loop."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_single_pass_state import SinglePassState


async def initialize_pass_checkpoint(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> None:
    """Record resume progress and initial metadata before artifact restoration."""
    state.errors = []
    state.status = "completed"
    state.chunked = state.request.chunk_seen_hashes is not None
    state.completed_stages = []
    state.has_resume = state.request.resume_from_checkpoint is not None
    if state.has_resume:
        state.completed_stages = ports("list")(
            state.request.resume_from_checkpoint.get("completed_stages") or []
        )
        ports("logger").info(
            "Resuming pipeline %s from checkpoint: %d stages completed",
            state.pipeline.pipeline_id,
            ports("len")(state.completed_stages),
        )
    if not state.chunked:
        await ports("_write_stage_checkpoint")(
            state.pipeline.pipeline_id,
            completed_stages=ports("list")(state.completed_stages),
            current_stage="",
            stage_statuses={},
            source_type=state.request.source_type,
            source_file=state.request.source_file,
            subject=state.request.subject,
            options=state.options,
        )


def restore_pass_artifacts(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> None:
    """Restore artifacts into the same payload subsequently passed to stages."""
    state.artifact_skipped = ports("set")()
    if state.has_resume:
        restored_stage, state.artifact_skipped = ports("_restore_from_artifacts")(
            state.pipeline.pipeline_id, state.completed_stages, state.data
        )
        if restored_stage:
            ports("logger").info(
                "True resume from artifact: restored=%s skipped_stages=%s",
                restored_stage,
                ports("sorted")(state.artifact_skipped),
            )


async def checkpoint_completed_stage(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> None:
    """Append completion before writing checkpoint and then saving its artifact."""
    if not state.chunked:
        state.completed_stages.append(state.current_name)
        await ports("_write_stage_checkpoint")(
            state.pipeline.pipeline_id,
            completed_stages=ports("list")(state.completed_stages),
            current_stage=state.current_name,
            stage_statuses={n: s.to_dict() for n, s in state.pipeline.stages.items()},
            source_type=state.request.source_type,
            source_file=state.request.source_file,
            subject=state.request.subject,
            options=state.options,
        )
        ports("_save_stage_artifact")(
            state.pipeline.pipeline_id, state.current_name, state.data
        )


async def checkpoint_failed_stage(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> None:
    """Write the existing error and completion list without rolling back progress."""
    if not state.chunked:
        await ports("_write_stage_checkpoint")(
            state.pipeline.pipeline_id,
            completed_stages=ports("list")(state.completed_stages),
            current_stage=state.current_name,
            stage_statuses={n: s.to_dict() for n, s in state.pipeline.stages.items()},
            failed_stage=state.current_name,
            error=state.current_stage.error,
            source_type=state.request.source_type,
            source_file=state.request.source_file,
            subject=state.request.subject,
            options=state.options,
        )


async def finalize_pass_checkpoint(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> None:
    """Clear/mark completed or mark failed only for single-pass mode."""
    if not state.chunked and state.status == "completed":
        await ports("_clear_stage_checkpoint")(state.pipeline.pipeline_id)
        ports("_save_completed_marker")(state.pipeline.pipeline_id)
    if not state.chunked and state.status == "failed":
        ports("_save_failed_marker")(state.pipeline.pipeline_id)
