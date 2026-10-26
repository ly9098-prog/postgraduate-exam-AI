"""Final markers, projection order and result reference contracts."""

import asyncio
from types import SimpleNamespace

import pytest

from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.single_pass_support import execute, make_harness


def observe_pass_events(monkeypatch, h):
    observed, clock = [], SimpleNamespace(value=1)
    monkeypatch.setattr(
        orchestrator, "time", SimpleNamespace(monotonic=lambda: clock.value)
    )
    original_list = orchestrator._list_artifacts

    def list_artifacts(pipeline_id):
        clock.value = 4
        h.trace.append(("list_artifacts", pipeline_id))
        return original_list(pipeline_id)

    def log(pass_logger, event, **fields):
        if not event.startswith("pipeline.single_pass."):
            return
        assert pass_logger.name == "app.pipeline"
        if event.endswith(".start"):
            assert h.pipeline.stages and h.checkpoints == [] and h.calls == []
        else:
            assert h.trace[-1] == ("list_artifacts", h.pipeline.pipeline_id)
        observed.append((event, fields))

    monkeypatch.setattr(orchestrator, "_list_artifacts", list_artifacts)
    monkeypatch.setattr(orchestrator, "log_event", log)
    return observed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "repair"])
async def test_structured_start_and_finish_events_keep_fields_and_effect_order(
    monkeypatch, failure
):
    h = make_harness(monkeypatch, failure_at=failure)
    events = observe_pass_events(monkeypatch, h)
    h.outputs["review"]["stats"] = {"to_review": 5}
    output = await execute(h, page_start=0, page_end=2)
    common = {
        "pipeline_id": h.pipeline.pipeline_id,
        "source_type": "pdf",
        "page_start": 0,
        "page_end": 2,
    }
    assert events == [
        ("pipeline.single_pass.start", common),
        (
            "pipeline.single_pass.finish",
            {
                **common,
                "status": "failed" if failure else "completed",
                "duration_ms": 3000,
                "question_count": 0 if failure else 5,
            },
        ),
    ]
    marker = "failed" if failure else "completed"
    assert h.trace.index((marker, h.pipeline.pipeline_id)) < len(h.trace) - 1
    assert output["status"] == marker


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["start", "finish"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_structured_event_error_propagates_at_its_original_boundary(
    monkeypatch, event, error_type
):
    h = make_harness(monkeypatch)
    error = error_type(event)

    def log(pass_logger, name, **fields):
        if name == f"pipeline.single_pass.{event}":
            raise error

    monkeypatch.setattr(orchestrator, "log_event", log)
    with pytest.raises(error_type) as caught:
        await execute(h)
    assert caught.value is error
    if event == "start":
        assert h.pipeline.stages and h.checkpoints == [] and h.calls == []
    else:
        assert all(s.status == "completed" for s in h.pipeline.stages.values())
        assert h.trace[-2:] == [
            ("clear", h.pipeline.pipeline_id),
            ("completed", h.pipeline.pipeline_id),
        ]


@pytest.mark.asyncio
async def test_final_projections_keep_reference_order_and_read_live_routing(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    events = []
    stats, report, artifacts = {}, {}, []
    diagnostics = {"performance_profile": {"_summary": {}}}
    routing, quality = {"route": 1}, {"quality": 2}
    h.outputs["review"].update(routing_metrics=routing, split_quality=quality)

    def stat(data, stages):
        events.append("stats")
        assert h.trace[-1] == ("completed", h.pipeline.pipeline_id)
        return stats

    def diag(data, stages):
        events.append("diagnostics")
        return diagnostics

    def quality_report(data, detail):
        events.append("quality")
        assert detail is diagnostics
        return report

    def stability(pipeline_id, metrics, score):
        events.append("stability")
        assert metrics is routing and score is quality

    monkeypatch.setattr(orchestrator, "_build_stats", stat)
    monkeypatch.setattr(orchestrator, "_build_diagnostics", diag)
    monkeypatch.setattr(orchestrator, "_build_quality_report", quality_report)
    monkeypatch.setattr(orchestrator, "_log_routing_stability", stability)
    monkeypatch.setattr(
        orchestrator,
        "_list_artifacts",
        lambda pipeline_id: (events.append("artifacts"), artifacts)[1],
    )
    output = await execute(h)
    assert events == ["stats", "diagnostics", "quality", "stability", "artifacts"]
    assert output["stats"] is stats and output["diagnostics"] is diagnostics
    assert output["quality_report"] is report and output["artifacts"] is artifacts
    assert (
        report["performance_summary"] is diagnostics["performance_profile"]["_summary"]
    )
    assert report["routing_metrics"] is routing
    assert report["split_quality_evaluation"] is quality
    assert output["review_new_hashes"] is h.outputs["review"]["review_new_hashes"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failed", ["clear", "completed", "failed", "stats", "artifacts"]
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_terminal_effects_propagate_without_rewriting_stage_statuses(
    monkeypatch,
    failed,
    error_type,
):
    h = make_harness(monkeypatch, failure_at="repair" if failed == "failed" else None)
    error = error_type(failed)

    def fail(*args, **kwargs):
        raise error

    async def fail_async(*args, **kwargs):
        raise error

    target = {
        "clear": "_clear_stage_checkpoint",
        "completed": "_save_completed_marker",
        "failed": "_save_failed_marker",
        "stats": "_build_stats",
        "artifacts": "_list_artifacts",
    }[failed]
    monkeypatch.setattr(orchestrator, target, fail_async if failed == "clear" else fail)
    with pytest.raises(error_type) as caught:
        await execute(h)
    assert caught.value is error
    if failed == "failed":
        assert h.pipeline.stages["repair"].status == "failed"
        assert h.pipeline.stages["review"].status == "skipped"
    else:
        assert all(stage.status == "completed" for stage in h.pipeline.stages.values())
    if failed == "clear":
        assert not any(row[0] == "completed" for row in h.trace)
    elif failed == "completed":
        assert h.trace[-1] == ("clear", h.pipeline.pipeline_id)
