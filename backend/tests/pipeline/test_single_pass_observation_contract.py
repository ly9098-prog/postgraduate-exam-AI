"""Pin split observation timing before extracting completed-stage data cleanup."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.single_pass_support import execute, make_harness


@pytest.mark.asyncio
async def test_split_observers_receive_live_outputs_after_path_release(monkeypatch):
    harness = make_harness(monkeypatch)
    import app.evaluation.routing_metrics as routing
    import app.evaluation.split_quality as quality

    diagnostics, layout, score, metrics = {}, {}, {}, {}
    harness.outputs["split"]["split_diagnostics"] = diagnostics
    harness.outputs["layout_reconstruction"] = {"layout_result": layout}
    observed = []

    def split_quality(questions, detail, current_layout):
        observed.append("quality")
        assert questions is harness.outputs["split"]["raw_questions"]
        assert detail is diagnostics
        assert current_layout is layout
        return score

    def routing_metrics(data):
        observed.append("routing")
        assert "file_path" not in data
        assert data["split_quality"] is score
        return metrics

    monkeypatch.setattr(quality, "evaluate_split_quality", split_quality)
    monkeypatch.setattr(routing, "build_routing_metrics", routing_metrics)
    await execute(harness)
    assert observed == ["quality", "routing"]
    assert harness.final_data["split_quality"] is score
    assert harness.final_data["routing_metrics"] is metrics


@pytest.mark.asyncio
async def test_each_observer_warning_looks_up_current_original_logger(monkeypatch):
    harness = make_harness(monkeypatch)
    import app.evaluation.routing_metrics as routing
    import app.evaluation.split_quality as quality

    warnings = []

    def fail(*args):
        raise RuntimeError("observer")

    def second(message, error):
        warnings.append(("second", message, str(error)))

    def first(message, error):
        warnings.append(("first", message, str(error)))
        monkeypatch.setattr(orchestrator, "logger", SimpleNamespace(warning=second))

    original_logger = orchestrator.logger
    monkeypatch.setattr(
        orchestrator,
        "logger",
        SimpleNamespace(info=original_logger.info, warning=first),
    )
    monkeypatch.setattr(quality, "evaluate_split_quality", fail)
    monkeypatch.setattr(routing, "build_routing_metrics", fail)
    result = await execute(harness)
    assert result["status"] == "completed"
    assert warnings == [
        ("first", "split_quality evaluation failed: %s", "observer"),
        ("second", "routing_metrics build failed: %s", "observer"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("observer", ["quality", "routing"])
async def test_observer_cancellation_keeps_stage_completed_without_checkpoint(
    monkeypatch, observer
):
    harness = make_harness(monkeypatch)
    import app.evaluation.routing_metrics as routing
    import app.evaluation.split_quality as quality

    cancellation = asyncio.CancelledError("observer cancelled")

    def cancel(*args):
        raise cancellation

    module, name = (
        (quality, "evaluate_split_quality")
        if observer == "quality"
        else (routing, "build_routing_metrics")
    )
    monkeypatch.setattr(module, name, cancel)
    with pytest.raises(asyncio.CancelledError) as raised:
        await execute(harness)
    assert raised.value is cancellation
    assert harness.pipeline.stages["split"].status == "completed"
    assert "split" not in [row["current_stage"] for row in harness.checkpoints]
    assert "split" not in [name for name, _ in harness.artifacts]
    assert not any(row[0] in {"clear", "completed", "failed"} for row in harness.trace)
