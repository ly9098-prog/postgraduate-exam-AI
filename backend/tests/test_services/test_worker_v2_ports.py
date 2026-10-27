"""Pin live worker ports and branch-local import capture timing."""

import pytest

from app.features import pipeline_checkpoint as checkpoint
from app.services import task_queue_worker as worker
from tests.worker_v2_support import WorkerHarness


@pytest.fixture
def harness(monkeypatch):
    token = checkpoint._fencing_ctx.set(None)
    try:
        yield WorkerHarness(monkeypatch)
    finally:
        checkpoint._fencing_ctx.reset(token)


@pytest.mark.asyncio
async def test_context_callbacks_are_imported_before_version_check(
    monkeypatch, harness
):
    def forbidden(*args, **kwargs):
        raise AssertionError("context callback rebound after version check")

    async def version(task):
        monkeypatch.setattr(checkpoint, "set_fencing_context", forbidden)
        monkeypatch.setattr(checkpoint, "clear_fencing_context", forbidden)
        harness.record("version")

    monkeypatch.setattr(worker, "_check_worker_version_compatibility", version)
    await harness.run()
    assert harness.events.count("set_context") == 1
    assert harness.events.count("clear_context") == 1
    assert checkpoint._fencing_ctx.get() is None


@pytest.mark.asyncio
async def test_initialization_can_change_fencing_membership(monkeypatch, harness):
    async def initialize(*args):
        harness.record("initialize", *args)
        monkeypatch.setattr(worker, "_FENCING_TASK_TYPES", frozenset())

    monkeypatch.setattr(worker, "_init_fencing_for_task", initialize)
    await harness.run()
    assert harness.events == [
        "version",
        "initialize",
        "verify",
        "handler.import_pipeline",
    ]


@pytest.mark.asyncio
async def test_import_handler_is_bound_before_verify_but_resolver_is_live(
    monkeypatch, harness
):
    from app.services import import_pipeline_service

    def forbidden(**kwargs):
        raise AssertionError("handler rebound during verification")

    async def resolve(*args):
        harness.record("live_resolve", *args)
        return "/synthetic/live.work"

    async def verify(*args):
        harness.record("verify", *args)
        monkeypatch.setattr(import_pipeline_service, "_run_pipeline_with_db", forbidden)
        monkeypatch.setattr(worker, "_resolve_staging_path", resolve)

    monkeypatch.setattr(worker, "_verify_fencing_or_cancel", verify)
    await harness.run(payload={"staging_object_id": "one"})
    assert (
        harness.call("handler.import_pipeline")[1]["file_path"]
        == "/synthetic/live.work"
    )
    assert harness.call("cleanup")[0] == ("/synthetic/live.work",)


@pytest.mark.asyncio
async def test_batch_options_are_captured_before_verify_but_sources_after_resolve(
    monkeypatch, harness
):
    payload = {
        "job_id": "job-test",
        "subject": "old",
        "subject_id": 8,
        "options": {"old": True},
        "staging_object_ids": ["one"],
    }
    options = payload["options"]
    source_factory = harness.batch.BatchImageSource
    made = []
    original_resolve = harness.resolve

    def source(**kwargs):
        made.append(kwargs)
        return source_factory(**kwargs)

    async def verify(*args):
        payload["subject"] = "new"
        payload["options"] = {}
        payload["staging_object_ids"].append("two")

    async def resolve(*args):
        monkeypatch.setattr(harness.batch, "BatchImageSource", source)
        return await original_resolve(*args)

    monkeypatch.setattr(worker, "_verify_fencing_or_cancel", verify)
    monkeypatch.setattr(worker, "_resolve_staging_path", resolve)
    await harness.run("batch_image", payload)
    kwargs = harness.call("handler.batch_image")[1]
    assert kwargs["subject"] == "old" and kwargs["options"] is options
    assert len(made) == len(kwargs["sources"]) == 2


@pytest.mark.asyncio
async def test_task_owner_is_live_but_pipeline_record_id_is_captured(
    monkeypatch, harness
):
    task = harness.task(payload={"pipeline_id": "before", "staging_object_id": "one"})

    async def initialize(*args):
        task.payload["pipeline_id"] = "after"
        task.owner_token, task.generation = "new-owner", 8

    monkeypatch.setattr(worker, "_init_fencing_for_task", initialize)
    await worker._process_task_v2(task)
    assert harness.call("set_context")[1] == dict(
        task_id="task-test", owner_token="new-owner", generation=8
    )
    assert harness.call("resolve")[0] == ("one", "new-owner", 8)
    assert harness.call("handler.import_pipeline")[1]["pipeline_id"] == "before"
    assert harness.call("post")[1]["record_id"] == "before"
    assert harness.call("post")[1]["expected_generation"] == 8


@pytest.mark.asyncio
async def test_admin_checkpoint_and_store_are_bound_before_staging(
    monkeypatch, harness
):
    resolve = harness.resolve

    def forbidden(*args, **kwargs):
        raise AssertionError("admin callback rebound after branch import")

    async def changing(*args):
        monkeypatch.setattr(harness.pipeline, "_get_stage_checkpoint", forbidden)
        monkeypatch.setattr(harness.pipeline, "_set_pipeline_store", forbidden)
        return await resolve(*args)

    monkeypatch.setattr(worker, "_resolve_staging_path", changing)
    await harness.run("admin_resume", {"staging_object_id": "one"})
    assert "checkpoint" in harness.events and "store" in harness.events


@pytest.mark.asyncio
async def test_cleanup_port_is_read_for_each_work_copy(monkeypatch, harness):
    calls = []

    async def second(path):
        calls.append(("second", path))

    async def first(path):
        calls.append(("first", path))
        monkeypatch.setattr(worker, "async_cleanup_work_copy", second)

    monkeypatch.setattr(worker, "async_cleanup_work_copy", first)
    await harness.run(
        "batch_image", {"job_id": "job", "staging_object_ids": ["one", "two"]}
    )
    assert calls == [
        ("first", "/synthetic/one.work"),
        ("second", "/synthetic/two.work"),
    ]


@pytest.mark.asyncio
async def test_partial_staging_failure_cleans_only_completed_work_copies(
    monkeypatch, harness
):
    original = harness.resolve
    error = RuntimeError("second staging failed")

    async def resolve(identity, *args):
        if identity == "two":
            raise error
        return await original(identity, *args)

    monkeypatch.setattr(worker, "_resolve_staging_path", resolve)
    with pytest.raises(RuntimeError) as caught:
        await harness.run(
            "batch_image", {"job_id": "job", "staging_object_ids": ["one", "two"]}
        )
    assert caught.value is error
    assert harness.call("cleanup")[0] == ("/synthetic/one.work",)
    assert harness.events.count("cleanup") == 1
    assert harness.events[-1] == "clear_context"
    assert "handler.batch_image" not in harness.events and "post" not in harness.events


@pytest.mark.asyncio
async def test_previous_context_is_restored_instead_of_cleared(harness):
    outer = checkpoint._fencing_ctx.set({"outer": True})
    try:
        await harness.run()
        assert checkpoint._fencing_ctx.get() == {"outer": True}
    finally:
        checkpoint._fencing_ctx.reset(outer)


@pytest.mark.asyncio
async def test_empty_resolved_work_path_is_tracked_before_image_rejection(harness):
    harness.paths["one"] = ""
    with pytest.raises(FileNotFoundError):
        await harness.run("image_pipeline", {"staging_object_id": "one"})
    assert harness.call("cleanup")[0] == ("",)
    assert harness.events[-1] == "clear_context"
    assert "verify" not in harness.events and "post" not in harness.events
