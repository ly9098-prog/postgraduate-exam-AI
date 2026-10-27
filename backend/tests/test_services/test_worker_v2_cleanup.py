"""Regression tests for cleanup failures masking tasks and leaking context."""

import asyncio

import pytest

from app.features import pipeline_checkpoint as checkpoint
from tests.worker_v2_support import WorkerHarness

PAYLOAD = {"job_id": "job-test", "staging_object_ids": ["one", "two"]}


@pytest.fixture
def harness(monkeypatch):
    token = checkpoint._fencing_ctx.set(None)
    try:
        yield WorkerHarness(monkeypatch)
    finally:
        checkpoint._fencing_ctx.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_type", [None, RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("cleanup_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("stage", ["cleanup", "clear_context"])
async def test_every_resource_is_attempted_and_first_failure_is_preserved(
    harness, primary_type, cleanup_type, stage
):
    primary = primary_type("primary-task-detail") if primary_type else None
    cleanup = cleanup_type("private-cleanup-detail")
    if primary:
        harness.faults["handler.batch_image"] = primary
    harness.faults[stage] = cleanup
    expected = primary if primary is not None else cleanup
    with pytest.raises(type(expected)) as caught:
        await harness.run("batch_image", PAYLOAD)
    assert caught.value is expected
    paths = [args[0] for event, args, _ in harness.calls if event == "cleanup"]
    assert paths == ["/synthetic/one.work", "/synthetic/two.work"]
    assert harness.events.count("clear_context") == 1
    assert "post" not in harness.events
    if stage != "clear_context":
        assert checkpoint._fencing_ctx.get() is None
    notes = getattr(expected, "__notes__", [])
    assert all("private-cleanup-detail" not in note for note in notes)
    if primary is not None:
        assert notes and all(type(cleanup).__name__ in note for note in notes)


@pytest.mark.asyncio
async def test_multiple_cleanup_failures_keep_primary_and_only_note_types(harness):
    primary = RuntimeError("primary")
    harness.faults.update(
        {
            "handler.batch_image": primary,
            "cleanup": ValueError("private-copy-detail"),
            "clear_context": asyncio.CancelledError("private-context-detail"),
        }
    )
    with pytest.raises(RuntimeError) as caught:
        await harness.run("batch_image", PAYLOAD)
    assert caught.value is primary
    assert harness.events[-3:] == ["cleanup", "cleanup", "clear_context"]
    assert len(primary.__notes__) == 3
    assert all("private-" not in note for note in primary.__notes__)
    assert "CancelledError" in primary.__notes__[-1]


@pytest.mark.asyncio
async def test_broken_error_notes_cannot_interrupt_remaining_cleanup(harness):
    primary = RuntimeError("primary")
    primary.__notes__ = ()
    harness.faults.update(
        {"handler.batch_image": primary, "cleanup": RuntimeError("cleanup")}
    )
    with pytest.raises(RuntimeError) as caught:
        await harness.run("batch_image", PAYLOAD)
    assert caught.value is primary
    assert harness.events[-3:] == ["cleanup", "cleanup", "clear_context"]
    assert checkpoint._fencing_ctx.get() is None


@pytest.mark.asyncio
async def test_real_handler_cancel_survives_cleanup_failure(monkeypatch, harness):
    entered = asyncio.Event()

    async def handler(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(harness.batch, "run_batch_job", handler)
    harness.faults["cleanup"] = RuntimeError("private-cleanup-detail")
    task = asyncio.create_task(harness.run("batch_image", PAYLOAD))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel("handler-primary-cancel")
        with pytest.raises(asyncio.CancelledError, match="handler-primary-cancel"):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    assert harness.events[-3:] == ["cleanup", "cleanup", "clear_context"]


@pytest.mark.asyncio
async def test_secondary_task_cancel_during_cleanup_keeps_primary(monkeypatch, harness):
    entered = asyncio.Event()
    paths = []
    primary = RuntimeError("handler-primary")
    harness.faults["handler.batch_image"] = primary

    async def cleanup(path):
        paths.append(path)
        if len(paths) == 1:
            entered.set()
            await asyncio.Event().wait()

    from app.services import task_queue_worker as worker

    monkeypatch.setattr(worker, "async_cleanup_work_copy", cleanup)
    task = asyncio.create_task(harness.run("batch_image", PAYLOAD))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel("secondary-cleanup-cancel")
        with pytest.raises(RuntimeError) as caught:
            await task
        assert caught.value is primary
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert paths == ["/synthetic/one.work", "/synthetic/two.work"]
    assert harness.events[-1] == "clear_context"
    assert "CancelledError" in primary.__notes__[-1]
