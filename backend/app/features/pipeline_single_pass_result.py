"""Final single-pass statistics, diagnostics, quality and completion projection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_single_pass_state import SinglePassState


def project_pass_quality(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> None:
    """Attach performance and routing to the original quality report reference."""
    state.quality_report = ports("_build_quality_report")(state.data, state.diagnostics)
    state.perf_profile = state.diagnostics.get("performance_profile", {})
    if state.perf_profile and "_summary" in state.perf_profile:
        state.quality_report["performance_summary"] = state.perf_profile["_summary"]
    state.routing_metrics = state.data.get("routing_metrics")
    if state.routing_metrics:
        state.quality_report["routing_metrics"] = state.routing_metrics
    state.split_quality = state.data.get("split_quality")
    if state.split_quality:
        state.quality_report["split_quality_evaluation"] = state.split_quality
    if state.routing_metrics:
        ports("_log_routing_stability")(
            state.pipeline.pipeline_id, state.routing_metrics, state.split_quality
        )


def finish_single_pass(state: SinglePassState, *, ports: Callable[[str], Any]) -> dict:
    """Build final projections and completion log only after terminal effects."""
    state.stats = ports("_build_stats")(state.data, state.pipeline.stages)
    state.diagnostics = ports("_build_diagnostics")(state.data, state.pipeline.stages)
    state.finished_at = ports("serialize_utc_datetime")(ports("utcnow")())
    project_pass_quality(state, ports=ports)
    state.artifacts_list = ports("_list_artifacts")(state.pipeline.pipeline_id)
    ports("log_event")(
        state.pass_logger,
        "pipeline.single_pass.finish",
        pipeline_id=state.pipeline.pipeline_id,
        source_type=state.request.source_type,
        page_start=state.request.page_start,
        page_end=state.request.page_end,
        status=state.status,
        duration_ms=ports("round")(
            (ports("time").monotonic() - state.started_clock) * 1000
        ),
        question_count=state.data.get("stats", {}).get("to_review", 0)
        if ports("isinstance")(state.data.get("stats"), ports("dict"))
        else 0,
    )
    return {
        "pipeline_id": state.pipeline.pipeline_id,
        "status": state.status,
        "batch_id": state.data.get("batch_id", ""),
        "stats": state.stats,
        "diagnostics": state.diagnostics,
        "quality_report": state.quality_report,
        "artifacts": state.artifacts_list,
        "stages": {
            stage_name: s.to_dict() for stage_name, s in state.pipeline.stages.items()
        },
        "errors": state.errors,
        "started_at": state.request.started_at,
        "finished_at": state.finished_at,
        "review_new_hashes": state.data.get("review_new_hashes") or [],
    }
