"""Characterize stage ordering, failed review isolation and resume boundaries."""

from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap

import pytest

from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.single_pass_support import STAGE_NAMES, execute, make_harness


@pytest.mark.asyncio
async def test_success_runs_canonical_order_and_marks_completion_only_after_last_stage(
    monkeypatch,
):
    harness = make_harness(monkeypatch)
    result = await execute(harness)

    assert harness.calls == list(STAGE_NAMES)
    assert result["status"] == "completed"
    assert result["errors"] == []
    assert result["batch_id"] == "synthetic-batch"
    assert result["review_new_hashes"] == ["hash"]
    assert [row["current_stage"] for row in harness.checkpoints] == ["", *STAGE_NAMES]
    assert harness.checkpoints[-1]["completed_stages"] == list(STAGE_NAMES)
    assert [name for name, _ in harness.artifacts] == list(STAGE_NAMES)
    assert harness.trace[-2:] == [
        ("clear", harness.pipeline.pipeline_id),
        ("completed", harness.pipeline.pipeline_id),
    ]
    assert all(s.status == "completed" for s in harness.pipeline.stages.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_stage", STAGE_NAMES)
async def test_stage_failure_breaks_only_early_input_stages_and_never_runs_review(
    monkeypatch, failed_stage
):
    harness = make_harness(monkeypatch, failure_at=failed_stage)
    result = await execute(harness)
    expected = list(STAGE_NAMES)
    if failed_stage in {"extract", "normalize_text"}:
        expected = expected[: expected.index(failed_stage) + 1]
    elif failed_stage != "review":
        expected.remove("review")

    assert harness.calls == expected
    assert result["status"] == "failed"
    assert result["errors"] == [f"stage '{failed_stage}' failed: synthetic failure"]
    assert result["batch_id"] == ""
    assert harness.pipeline.stages[failed_stage].status == "failed"
    assert harness.trace[-1] == ("failed", harness.pipeline.pipeline_id)
    assert not any(row[0] in {"clear", "completed"} for row in harness.trace)
    failure = next(c for c in harness.checkpoints if c.get("failed_stage"))
    assert failure["failed_stage"] == failed_stage
    assert failure["error"] == "synthetic failure"
    assert failed_stage not in failure["completed_stages"]
    assert failed_stage not in [name for name, _ in harness.artifacts]
    if failed_stage not in {"extract", "normalize_text", "review"}:
        assert harness.pipeline.stages["review"].status == "skipped"
        assert harness.pipeline.stages["review"].duration_ms == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_stage", STAGE_NAMES)
async def test_stage_cancellation_propagates_without_failure_checkpoint_or_marker(
    monkeypatch, cancel_stage
):
    cancellation = asyncio.CancelledError("synthetic cancellation")
    harness = make_harness(monkeypatch, failure_at=cancel_stage, failure=cancellation)
    with pytest.raises(asyncio.CancelledError) as raised:
        await execute(harness)
    assert raised.value is cancellation
    assert harness.calls == list(STAGE_NAMES[: STAGE_NAMES.index(cancel_stage) + 1])
    assert harness.pipeline.stages[cancel_stage].status == "running"
    assert not any(c.get("failed_stage") for c in harness.checkpoints)
    assert not any(row[0] in {"clear", "completed", "failed"} for row in harness.trace)


@pytest.mark.asyncio
async def test_checkpoint_alone_reruns_stages_instead_of_assuming_outputs_exist(
    monkeypatch,
):
    harness = make_harness(monkeypatch)
    restore_calls = []

    def restore(pipeline_id, completed, data):
        restore_calls.append((pipeline_id, list(completed)))
        return None, set()

    monkeypatch.setattr(orchestrator, "_restore_from_artifacts", restore)
    await execute(
        harness, resume_from_checkpoint={"completed_stages": ["extract", "split"]}
    )
    assert harness.calls == list(STAGE_NAMES)
    assert restore_calls == [(harness.pipeline.pipeline_id, ["extract", "split"])]
    assert harness.checkpoints[1]["completed_stages"] == ["extract", "split", "extract"]


@pytest.mark.asyncio
async def test_restored_artifact_skips_stages_without_progress_checkpoint_or_artifact(
    monkeypatch,
):
    harness = make_harness(monkeypatch)
    skipped = set(STAGE_NAMES[: STAGE_NAMES.index("normalize_schema") + 1])
    progress = []

    def restore(pipeline_id, completed, data):
        data["questions"] = [{"number": 99}]
        return "normalize_schema", skipped

    async def report(stages, current, errors):
        progress.append(current)

    monkeypatch.setattr(orchestrator, "_restore_from_artifacts", restore)
    await execute(harness, resume_from_checkpoint={}, progress_callback=report)
    expected = [name for name in STAGE_NAMES if name not in skipped]
    assert harness.calls == expected
    assert harness.inputs[expected[0]]["questions"] == [{"number": 99}], (
        "restored questions reach next stage"
    )
    assert harness.final_data["questions"] == [{"number": 99}]
    assert progress == [name for name in expected for _ in range(2)]
    assert [name for name, _ in harness.artifacts] == expected
    assert harness.checkpoints[1]["completed_stages"] == [
        *STAGE_NAMES[: STAGE_NAMES.index("normalize_schema") + 1],
        expected[0],
    ]
    for name in skipped:
        assert harness.pipeline.stages[name].status == "completed"
        assert harness.pipeline.stages[name].duration_ms == 0


@pytest.mark.asyncio
async def test_restored_payload_assertions_reject_copy_instead_of_live_data(
    monkeypatch,
):
    source = inspect.getsource(orchestrator.ImportPipeline._run_single_pass)
    tree = ast.parse(textwrap.dedent(source))
    replacements = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "_restore_from_artifacts":
                assert isinstance(node.args[2], ast.Name) and node.args[2].id == "data"
                node.args[2] = ast.Call(
                    func=ast.Attribute(value=node.args[2], attr="copy", ctx=ast.Load()),
                    args=[],
                    keywords=[],
                )
                replacements += 1
    assert replacements == 1
    namespace = {}
    exec(
        compile(ast.fix_missing_locations(tree), "<restore-copy-mutation>", "exec"),
        vars(orchestrator),
        namespace,
    )
    monkeypatch.setattr(
        orchestrator.ImportPipeline, "_run_single_pass", namespace["_run_single_pass"]
    )
    with pytest.raises(AssertionError, match="restored questions reach next stage"):
        await (
            test_restored_artifact_skips_stages_without_progress_checkpoint_or_artifact(
                monkeypatch
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_at", [None, "extract", "repair"])
async def test_chunk_pass_omits_global_checkpoints_artifacts_and_terminal_markers(
    monkeypatch, failure_at
):
    harness = make_harness(monkeypatch, failure_at=failure_at)
    seen = set()
    shared = {
        "import_mode": "auto",
        "strategy": object(),
        "watermark_patterns": [],
        "hash_index": object(),
    }
    result = await execute(
        harness, chunk_seen_hashes=seen, chunk_logical_end=12, shared=shared
    )
    assert result["status"] == ("failed" if failure_at else "completed")
    assert harness.checkpoints == []
    assert harness.artifacts == []
    assert all(row[0] == "run" for row in harness.trace)
    assert harness.inputs["extract"]["_chunk_seen_hashes"] is seen
    assert harness.inputs["extract"]["hash_index"] is shared["hash_index"]
    assert harness.inputs["extract"]["_chunk_logical_end"] == 12
