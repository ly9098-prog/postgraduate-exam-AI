"""Pin original handler failure, cancellation and post-fence policies."""

import asyncio

import pytest

from app.features import pipeline_checkpoint as checkpoint
from app.services import db_fencing
from app.services import task_queue_worker as worker
from tests.worker_v2_support import FENCED, WorkerHarness


@pytest.fixture
def harness(monkeypatch):
    token = checkpoint._fencing_ctx.set(None)
    try:
        yield WorkerHarness(monkeypatch)
    finally:
        checkpoint._fencing_ctx.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", [*FENCED, "formula_batch", "answer_projection", "error_diagnosis"]
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_handler_error_propagates_after_original_resource_cleanup(
    harness, kind, error_type
):
    error = error_type("synthetic handler failure")
    harness.faults[f"handler.{kind}"] = error
    payload = {
        "staging_object_id": "one",
        "staging_object_ids": ["one", "two"],
        "pipeline_id": "pipeline-test",
        "job_id": "job-test",
    }
    with pytest.raises(error_type) as caught:
        await harness.run(kind, payload)
    assert caught.value is error and "post" not in harness.events
    assert checkpoint._fencing_ctx.get() is None
    if kind in FENCED:
        assert "clear_context" in harness.events
        cleanups = [args[0] for event, args, _ in harness.calls if event == "cleanup"]
        expected = ["/synthetic/one.work"]
        if kind == "batch_image":
            expected.append("/synthetic/two.work")
        assert cleanups == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage,kind",
    [
        ("version", "import_pipeline"),
        ("initialize", "import_pipeline"),
        ("set_context", "import_pipeline"),
        ("verify", "import_pipeline"),
        ("resolve", "image_pipeline"),
        ("open", "excel_pipeline"),
        ("checkpoint", "admin_resume"),
        ("execute", "formula_batch"),
    ],
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_pre_handler_faults_keep_order_and_exception_identity(
    harness, stage, kind, error_type
):
    error = error_type("synthetic pre-handler failure")
    harness.faults[stage] = error
    with pytest.raises(error_type) as caught:
        await harness.run(kind, {"staging_object_id": "one"})
    assert caught.value is error
    assert not any(event.startswith("handler.") for event in harness.events)
    assert "post" not in harness.events
    assert checkpoint._fencing_ctx.get() is None
    assert ("clear_context" in harness.events) == (
        kind != "formula_batch"
        and stage not in {"version", "initialize", "set_context"}
    )


@pytest.mark.asyncio
async def test_admin_store_ordinary_error_warns_but_cancel_propagates(harness):
    harness.faults["store"] = RuntimeError("store unavailable")
    await harness.run("admin_resume")
    assert "post" in harness.events and harness.logger.warning.call_count == 1
    harness.events.clear()
    error = asyncio.CancelledError("store cancelled")
    harness.faults["store"] = error
    with pytest.raises(asyncio.CancelledError) as caught:
        await harness.run("admin_resume")
    assert caught.value is error and "post" not in harness.events
    assert harness.events[-1] == "clear_context"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["post", "commit", "db.enter", "db.exit"])
async def test_post_fence_ordinary_failures_remain_nonfatal(harness, stage):
    harness.faults[stage] = RuntimeError("synthetic post-fence failure")
    await harness.run("import_pipeline")
    assert harness.events.index("clear_context") < harness.events.index(stage)
    assert harness.logger.warning.call_args.args[0].startswith(
        "Post-execution fence check failed (non-fatal)"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["post", "commit", "db.enter", "db.exit"])
async def test_post_fence_cancel_propagates_after_context_is_cleared(harness, stage):
    error = asyncio.CancelledError("post-fence cancelled")
    harness.faults[stage] = error
    with pytest.raises(asyncio.CancelledError) as caught:
        await harness.run("import_pipeline")
    assert caught.value is error and checkpoint._fencing_ctx.get() is None
    assert not harness.logger.warning.called


@pytest.mark.asyncio
async def test_lost_post_fence_rolls_back_and_rejects_completion(harness):
    harness.fence_ok = False
    with pytest.raises(
        db_fencing.FencingRejectedError, match="Post-execution fence lost"
    ):
        await harness.run("import_pipeline")
    assert harness.events[-3:] == ["post", "rollback", "db.exit"]
    assert "commit" not in harness.events and checkpoint._fencing_ctx.get() is None
    assert not harness.logger.warning.called


@pytest.mark.asyncio
async def test_post_fence_table_removed_during_handler_skips_database(
    monkeypatch, harness
):
    async def handler(**kwargs):
        harness.record("handler.import_pipeline")
        monkeypatch.setattr(db_fencing, "FENCING_TABLES", {})

    from app.services import import_pipeline_service

    monkeypatch.setattr(import_pipeline_service, "_run_pipeline_with_db", handler)
    await harness.run()
    assert harness.events[-1] == "clear_context" and "db.enter" not in harness.events


@pytest.mark.asyncio
async def test_empty_record_id_preserves_explicit_value_and_skips_fencing(harness):
    await harness.run(payload={"pipeline_id": None})
    assert harness.call("handler.import_pipeline")[1]["pipeline_id"] is None
    assert harness.events == ["version", "handler.import_pipeline"]


@pytest.mark.asyncio
async def test_null_payload_still_fails_after_version_check(harness):
    task = harness.task()
    task.payload = None
    with pytest.raises(AttributeError):
        await worker._process_task_v2(task)
    assert harness.events == ["version"]
