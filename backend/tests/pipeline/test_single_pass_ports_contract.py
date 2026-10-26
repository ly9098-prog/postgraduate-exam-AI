"""Pin stage-effect lookup timing, failure ownership and callback data identity."""

import asyncio

import pytest

from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.single_pass_support import execute, make_harness


@pytest.mark.asyncio
async def test_metrics_callback_replacement_controls_current_stage_artifact_save(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    saved = []

    def metrics(stage, data, result):
        if stage.name == "extract":
            monkeypatch.setattr(
                orchestrator,
                "_save_stage_artifact",
                lambda pipeline_id, name, actual: saved.append((name, actual)),
            )

    monkeypatch.setattr(orchestrator, "_update_stage_metrics", metrics)
    output = await execute(h)
    assert output["status"] == "completed"
    assert saved[0][0] == "extract" and len(saved) == len(h.pipeline.stages)
    assert all(actual is saved[0][1] for _, actual in saved)
    assert saved[0][1]["questions"] is h.outputs["normalize_schema"]["questions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["metrics", "completion", "artifact"])
async def test_post_run_effect_failure_keeps_stage_completed_and_isolates_review(
    monkeypatch, failure
):
    h = make_harness(monkeypatch)
    target = {
        "metrics": "_update_stage_metrics",
        "completion": "complete_stage_data",
        "artifact": "_save_stage_artifact",
    }[failure]
    original = getattr(orchestrator, target)

    def effect(*args, **kwargs):
        name = (
            args[0].name
            if failure == "metrics"
            else args[0]
            if failure == "completion"
            else args[1]
        )
        if name == "repair":
            raise RuntimeError(failure)
        return original(*args, **kwargs)

    monkeypatch.setattr(orchestrator, target, effect)
    output = await execute(h)
    assert output["status"] == "failed"
    assert output["errors"] == ["stage 'repair' failed: None"]
    assert h.pipeline.stages["repair"].status == "completed"
    assert h.pipeline.stages["review"].status == "skipped"
    failed = next(value for value in h.checkpoints if value.get("failed_stage"))
    assert ("repair" in failed["completed_stages"]) is (failure == "artifact")


@pytest.mark.asyncio
async def test_progress_uses_same_error_list_returned_to_caller(monkeypatch):
    h = make_harness(monkeypatch)
    references = []

    async def progress(stages, name, errors):
        references.append(errors)
        if name == "extract" and stages[name]["status"] == "pending":
            errors.append("observer-note")

    output = await execute(h, progress_callback=progress)
    assert all(value is output["errors"] for value in references)
    assert output["errors"] == ["observer-note"]
    assert output["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [RuntimeError("failure checkpoint"), asyncio.CancelledError("failure checkpoint")],
)
async def test_failure_checkpoint_error_propagates_before_failure_release_and_markers(
    monkeypatch, error
):
    h = make_harness(monkeypatch, failure_at="ocr_correction")
    original = orchestrator._write_stage_checkpoint

    async def checkpoint(*args, **kwargs):
        if kwargs.get("failed_stage"):
            raise error
        return await original(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "_write_stage_checkpoint", checkpoint)
    with pytest.raises(type(error)) as caught:
        await execute(h)
    assert caught.value is error
    assert h.calls[-1] == "ocr_correction"
    assert not any(event[0] in {"clear", "completed", "failed"} for event in h.trace)


@pytest.mark.asyncio
async def test_terminal_quality_reads_latest_routing_after_report_callback(monkeypatch):
    h = make_harness(monkeypatch)
    routing, quality, report = {"new-route": 1}, {"new-quality": 2}, {}

    def quality_report(data, diagnostics):
        data["routing_metrics"] = routing
        data["split_quality"] = quality
        return report

    monkeypatch.setattr(orchestrator, "_build_quality_report", quality_report)
    output = await execute(h)
    assert output["quality_report"] is report
    assert report["routing_metrics"] is routing
    assert report["split_quality_evaluation"] is quality
