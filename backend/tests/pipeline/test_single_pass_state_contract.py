"""Characterize shared data release, callback isolation and checkpoint failures."""

from __future__ import annotations

import asyncio

import pytest

from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.single_pass_support import STAGE_NAMES, execute, make_harness


@pytest.mark.asyncio
async def test_payload_release_follows_last_consumer_and_caches_normalized_count(
    monkeypatch,
):
    harness = make_harness(monkeypatch)
    await execute(harness)
    assert harness.inputs["normalize_text"]["raw_blocks"] == [{"text": "synthetic"}]
    assert "raw_blocks" not in harness.inputs["ocr_correction"]
    for name in ("extract", "normalize_text", "ocr_correction"):
        assert harness.inputs[name]["file_content"] == b"synthetic input"
        assert harness.inputs[name]["page_images"] == {1: b"image"}
    assert "file_content" not in harness.inputs["layout_reconstruction"]
    assert "page_images" not in harness.inputs["layout_reconstruction"]
    assert harness.inputs["split"]["file_path"] == "/synthetic/input.pdf"
    assert "file_path" not in harness.inputs["question_bbox"]
    assert "normalized_blocks" in harness.inputs["match"]
    assert "normalized_blocks" not in harness.inputs["normalize_schema"]
    assert harness.inputs["normalize_schema"]["normalized_block_count"] == 2
    for name in ("raw_questions", "matched", "unmatched"):
        assert name in harness.inputs["normalize_schema"]
        assert name not in harness.inputs["code_language_noise_clean"]
    assert harness.final_data["questions"] == [{"number": 1}]
    assert harness.final_data["normalized_block_count"] == 2


@pytest.mark.asyncio
async def test_ocr_failure_releases_input_and_continues_without_review(monkeypatch):
    harness = make_harness(monkeypatch, failure_at="ocr_correction")
    result = await execute(harness)
    assert result["status"] == "failed"
    assert "ocr_correction" in harness.calls
    assert "layout_reconstruction" in harness.calls
    assert "review" not in harness.calls
    for key in ("file_content", "page_images", "file_path"):
        assert key not in harness.inputs["layout_reconstruction"]


@pytest.mark.asyncio
async def test_page_range_copies_options_and_leaves_caller_values_unchanged(
    monkeypatch,
):
    harness = make_harness(monkeypatch)
    opts = {"page_start": 9, "page_end": 20, "other": object()}
    await execute(harness, opts=opts, page_start=2, page_end=None)
    actual = harness.inputs["extract"]["options"]
    assert actual is not opts
    assert actual == {**opts, "page_start": 2, "page_end": None}
    assert opts["page_start"] == 9
    assert opts["page_end"] == 20
    assert actual["other"] is opts["other"]


@pytest.mark.asyncio
async def test_progress_regular_errors_are_ignored_before_and_after_every_stage(
    monkeypatch,
):
    harness = make_harness(monkeypatch)
    calls = []

    async def progress(stages, name, errors):
        calls.append((name, stages[name]["status"], list(errors)))
        raise RuntimeError("synthetic observer error")

    result = await execute(harness, progress_callback=progress)
    assert result["status"] == "completed"
    assert [name for name, _, _ in calls] == [n for n in STAGE_NAMES for _ in range(2)]
    assert [status for _, status, _ in calls] == ["pending", "completed"] * len(
        STAGE_NAMES
    )
    assert all(errors == [] for _, _, errors in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_at", ["extract", "normalize_text", "repair"])
async def test_progress_failure_sequence_distinguishes_early_break_from_continue(
    monkeypatch, failure_at
):
    harness = make_harness(monkeypatch, failure_at=failure_at)
    observed = []

    async def progress(stages, name, errors):
        observed.append((name, stages[name]["status"]))

    await execute(harness, progress_callback=progress)
    expected = []
    for name in harness.calls:
        expected.append((name, "pending"))
        if name not in {"extract", "normalize_text"} or name != failure_at:
            expected.append((name, "failed" if name == failure_at else "completed"))
    assert observed == expected
    assert ("review", "pending") not in observed


@pytest.mark.asyncio
@pytest.mark.parametrize("after_stage", [False, True])
async def test_progress_cancellation_propagates_without_terminal_markers(
    monkeypatch, after_stage
):
    harness = make_harness(monkeypatch)
    cancellation = asyncio.CancelledError("observer cancelled")

    async def progress(stages, name, errors):
        if (stages[name]["status"] == "completed") == after_stage:
            raise cancellation

    with pytest.raises(asyncio.CancelledError) as raised:
        await execute(harness, progress_callback=progress)
    assert raised.value is cancellation
    assert harness.calls == (["extract"] if after_stage else [])
    assert not any(row[0] in {"clear", "completed", "failed"} for row in harness.trace)


@pytest.mark.asyncio
async def test_initial_checkpoint_failure_prevents_first_stage(monkeypatch):
    harness = make_harness(monkeypatch)
    failure = RuntimeError("checkpoint unavailable")

    async def checkpoint(*args, **kwargs):
        raise failure

    monkeypatch.setattr(orchestrator, "_write_stage_checkpoint", checkpoint)
    with pytest.raises(RuntimeError) as raised:
        await execute(harness)
    assert raised.value is failure
    assert harness.calls == []
    assert harness.trace == []


@pytest.mark.asyncio
async def test_post_stage_checkpoint_failure_marks_pipeline_failed_after_stage_completed(
    monkeypatch,
):
    harness = make_harness(monkeypatch)
    original = orchestrator._write_stage_checkpoint

    async def checkpoint(pipeline_id, **values):
        if values["current_stage"] == "repair" and not values.get("failed_stage"):
            raise RuntimeError("checkpoint unavailable")
        await original(pipeline_id, **values)

    monkeypatch.setattr(orchestrator, "_write_stage_checkpoint", checkpoint)
    result = await execute(harness)
    assert result["status"] == "failed"
    assert result["errors"] == ["stage 'repair' failed: None"]
    assert harness.pipeline.stages["repair"].status == "completed"
    failure = next(c for c in harness.checkpoints if c.get("failed_stage"))
    assert failure["failed_stage"] == "repair"
    assert failure["error"] is None
    assert "repair" in failure["completed_stages"]
    assert "repair" not in [name for name, _ in harness.artifacts]
    assert "review" not in harness.calls


@pytest.mark.asyncio
async def test_split_observer_failure_keeps_stage_success_and_downstream_execution(
    monkeypatch,
):
    harness = make_harness(monkeypatch)
    import app.evaluation.routing_metrics as routing
    import app.evaluation.split_quality as quality

    def fail(*args, **kwargs):
        raise RuntimeError("observer failed")

    monkeypatch.setattr(routing, "build_routing_metrics", fail)
    monkeypatch.setattr(quality, "evaluate_split_quality", fail)
    result = await execute(harness)
    assert result["status"] == "completed"
    assert harness.calls == list(STAGE_NAMES)
    assert "split_quality" not in harness.final_data
    assert "routing_metrics" not in harness.final_data
