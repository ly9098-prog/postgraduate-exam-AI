"""Resume retains historical module capture and live lookup timing."""

from types import SimpleNamespace

import pytest

from app.features import global_hash_index, pipeline_checkpoint
from app.features import pipeline_orchestrator as module
from tests.pipeline.chunked_run_support import observe
from tests.pipeline.resume_run_support import execute, make_harness


@pytest.mark.asyncio
async def test_pipeline_class_and_loader_are_looked_up_after_index_load(monkeypatch):
    h = make_harness(monkeypatch)
    old = module.ImportPipeline

    def replace(_):
        async def seen(db, pipeline_id):
            observe(h, "new_seen", (db, pipeline_id))
            return h.seen

        monkeypatch.setattr(module, "_load_seen_hashes_for_resume", seen)
        monkeypatch.setattr(
            module,
            "ImportPipeline",
            lambda **kw: observe(h, "new_pipeline", kw) or old(**kw),
        )

    h.hooks["load"] = replace
    await execute(h)
    assert "new_seen" in h.events and "new_pipeline" in h.events
    assert "seen" not in h.events


@pytest.mark.asyncio
async def test_checkpoint_attrs_remain_live_but_index_class_was_captured_at_entry(
    monkeypatch,
):
    h = make_harness(monkeypatch)

    def replace(_):
        async def pending(db, pipeline_id):
            observe(h, "new_pending", (db, pipeline_id))
            return h.pending

        monkeypatch.setattr(pipeline_checkpoint, "get_pending_chunks", pending)
        monkeypatch.setattr(
            global_hash_index, "GlobalHashIndex", lambda: pytest.fail("late class")
        )

    h.hooks["query_pipeline"] = replace
    await execute(h)
    assert "new_pending" in h.events and "construct_index" in h.events
    assert "pending" not in h.events


@pytest.mark.asyncio
async def test_source_attributes_and_checkpoint_status_are_read_each_iteration(
    monkeypatch,
):
    h = make_harness(monkeypatch)

    def replace(_):
        h.row.source_type, h.row.source_file = "image", "changed.png"

        async def status(db, pipeline_id, **kwargs):
            observe(h, "new_status", (db, pipeline_id, kwargs))

        monkeypatch.setattr(pipeline_checkpoint, "update_pipeline_status", status)

    h.hooks["exit:3"] = replace
    await execute(h)
    assert h.calls[0]["source_file"] == "original.pdf"
    assert (
        h.calls[1]["source_type"] == "image"
        and h.calls[1]["source_file"] == "changed.png"
    )
    assert h.records["new_status"] == [
        (
            h.sessions[5],
            "resume-contract",
            {
                "status": "completed",
                "finished": True,
            },
        )
    ]


@pytest.mark.asyncio
async def test_global_builtin_dict_port_and_logger_remain_live(monkeypatch):
    h = make_harness(monkeypatch)
    options = h.arguments["options"]
    monkeypatch.setattr(
        module, "dict", lambda obj: {**obj, "extra": "copied"}, raising=False
    )

    def replace(_):
        monkeypatch.setattr(
            module,
            "logger",
            SimpleNamespace(warning=lambda *args: observe(h, "new_warning", args)),
        )

    h.hooks["strategy"] = replace
    h.row.watermark_snapshot = None
    await execute(h)
    assert h.calls[0]["opts"] == {**options, "extra": "copied"}
    assert "new_warning" in h.events and "warning" not in h.events


@pytest.mark.asyncio
async def test_missing_checkpoint_attribute_remains_best_effort(monkeypatch):
    h = make_harness(monkeypatch)
    monkeypatch.delattr(pipeline_checkpoint, "get_stage_checkpoint")
    await execute(h)
    assert h.calls[0]["subject_id"] is None and "debug" in h.events


@pytest.mark.asyncio
async def test_progress_and_both_cache_invalidations_resolve_late_module_attributes(
    monkeypatch,
):
    h = make_harness(monkeypatch)

    async def invalidate_running(pipeline_id):
        observe(h, "invalidate_running", pipeline_id)

    async def invalidate_final(pipeline_id):
        observe(h, "invalidate_final", pipeline_id)

    async def progress(db, pipeline_id, **kwargs):
        observe(h, "late_progress", (db, pipeline_id, kwargs))
        return {"failed_chunks": 1}

    def running_exit(_):
        monkeypatch.setattr(
            pipeline_checkpoint, "invalidate_progress_cache", invalidate_running
        )

    def last_chunk_exit(_):
        monkeypatch.setattr(pipeline_checkpoint, "get_pipeline_progress", progress)
        monkeypatch.setattr(
            pipeline_checkpoint, "invalidate_progress_cache", invalidate_final
        )

    h.hooks["exit:2"], h.hooks["exit:4"] = running_exit, last_chunk_exit
    await execute(h)
    assert h.records["late_progress"] == [
        (h.sessions[5], "resume-contract", {"use_cache": False})
    ]
    assert (
        h.records["invalidate_running"]
        == h.records["invalidate_final"]
        == ["resume-contract"]
    )
    assert "progress" not in h.events and "invalidate" not in h.events
    assert h.events[-1] == "invalidate_final" and "status:paused" in h.events
    assert "status:completed" not in h.events


@pytest.mark.asyncio
async def test_final_session_ports_resolve_at_their_actual_expression_sites(
    monkeypatch,
):
    h = make_harness(monkeypatch)

    async def invalidate(pipeline_id):
        observe(h, "after_final_exit", pipeline_id)

    async def status(db, pipeline_id, **kwargs):
        observe(h, "late_final_status", (db, pipeline_id, kwargs))

    async def progress(db, pipeline_id, **kwargs):
        observe(h, "inside_final_progress", (db, pipeline_id, kwargs))
        monkeypatch.setattr(pipeline_checkpoint, "update_pipeline_status", status)
        return {"failed_chunks": 1}

    def enter(_):
        monkeypatch.setattr(pipeline_checkpoint, "get_pipeline_progress", progress)

    def exit_session(_):
        monkeypatch.setattr(
            pipeline_checkpoint, "invalidate_progress_cache", invalidate
        )

    h.hooks["enter:5"], h.hooks["exit:5"] = enter, exit_session
    await execute(h)
    assert h.records["inside_final_progress"] == [
        (h.sessions[5], "resume-contract", {"use_cache": False})
    ]
    assert h.records["late_final_status"] == [
        (h.sessions[5], "resume-contract", {"status": "paused", "finished": False})
    ]
    assert h.records["after_final_exit"] == ["resume-contract"]
    assert h.events[-4:] == [
        "inside_final_progress",
        "late_final_status",
        "exit:5",
        "after_final_exit",
    ]
    assert h.events.count("invalidate") == 1 and "progress" not in h.events
    assert "status:paused" not in h.events and "status:completed" not in h.events
