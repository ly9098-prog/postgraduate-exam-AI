"""Definition-time imports and live original-module ports retain evaluation order."""

import builtins

import pytest

from app.features import global_hash_index, pipeline_checkpoint
from app.features import pipeline_orchestrator as module
from tests.pipeline.chunked_run_support import execute, fail_at, make_harness


@pytest.mark.asyncio
async def test_inner_import_captures_hash_class_before_checkpoint_callbacks(monkeypatch):
    h = make_harness(monkeypatch)

    def replacement():
        raise AssertionError("class lookup must remain bound before parent checkpoint")

    h.hooks["parent"] = lambda _: monkeypatch.setattr(
        global_hash_index, "GlobalHashIndex", replacement
    )
    await execute(h)
    assert h.index is not None and len(h.chunk_calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("point,name,label", [
    ("watermark", "ensure_pipeline_record", "parent"),
    ("parent", "ensure_chunk_records", "chunks"),
    ("chunk:0", "update_pipeline_status", "final"),
    ("final", "invalidate_progress_cache", "invalidate"),
])
async def test_checkpoint_module_attributes_remain_live_until_each_call(
    monkeypatch, point, name, label
):
    h = make_harness(monkeypatch)
    observed = []

    async def replacement(*args, **kwargs):
        observed.append((args, kwargs))

    h.hooks[point] = lambda _: monkeypatch.setattr(pipeline_checkpoint, name, replacement)
    await execute(h)
    assert len(observed) == 1 and label not in h.events
    args, kwargs = observed[0]
    if label == "parent":
        assert args == (h.sessions[0],) and kwargs["pipeline_id"] == "chunked-contract"
    elif label == "chunks":
        assert args == (h.sessions[0], "chunked-contract", h.arguments["chunk_ranges"])
        assert args[2] is h.arguments["chunk_ranges"] and kwargs == {}
    elif label == "final":
        assert args == (h.sessions[4], "chunked-contract")
        assert kwargs == {"status": "completed", "error_message": None, "finished": True}
    else:
        assert args == ("chunked-contract",) and kwargs == {}


@pytest.mark.asyncio
async def test_configuration_and_watermark_ports_are_read_sequentially(monkeypatch):
    h = make_harness(monkeypatch)
    snapshot = [{"new": True}]
    h.hooks["size"] = lambda _: monkeypatch.setattr(module, "_resolve_chunk_overlap", lambda: 19)
    h.hooks["derive"] = lambda _: monkeypatch.setattr(
        module, "_serialize_watermark_patterns", lambda _: snapshot
    )
    output = await execute(h)
    assert output["diagnostics"]["chunk_overlap"] == 19
    assert h.records["parent"][0][1]["watermark_snapshot"] is snapshot
    assert all(call["chunk_overlap"] == 19 for call in h.chunk_calls)
    assert "overlap" not in h.events and "watermark" not in h.events


@pytest.mark.asyncio
async def test_shared_copy_occurs_after_load_and_still_shares_nested_values(monkeypatch):
    h = make_harness(monkeypatch)
    original = h.arguments["shared"]
    h.hooks["load"] = lambda _: original.update(before="visible")

    def after_copy(_):
        original["after"] = "not-copied"
        original["nested"].append("nested-change")

    h.hooks["pipeline.chunked.start"] = after_copy
    await execute(h)
    shared = h.chunk_calls[0]["shared"]
    assert shared["before"] == "visible" and "after" not in shared
    assert shared["nested"] is original["nested"] and shared["nested"] == ["nested-change"]


@pytest.mark.asyncio
async def test_utcnow_cannot_replace_the_already_bound_serializer(monkeypatch):
    h = make_harness(monkeypatch)

    def replacement(_):
        raise AssertionError("serializer must be bound before utcnow executes")

    h.hooks["utc"] = lambda _: monkeypatch.setattr(module, "serialize_utc_datetime", replacement)
    output = await execute(h)
    assert output["finished_at"] == "finished" and h.records["serialize"] == [h.stamp]


@pytest.mark.asyncio
async def test_invalidation_can_replace_the_later_aggregation_port(monkeypatch):
    h = make_harness(monkeypatch)
    risk = {}
    observed = []

    def merge(results):
        observed.extend(results)
        return risk

    h.hooks["invalidate"] = lambda _: monkeypatch.setattr(module, "_merge_risk_flag_counts", merge)
    output = await execute(h)
    assert observed == h.outcomes and observed[0] is h.outcomes[0]
    assert output["diagnostics"]["risk_flag_counts"] is risk
    assert "merge" not in h.events


@pytest.mark.asyncio
async def test_start_log_can_replace_finish_logging_and_elapsed_clock(monkeypatch):
    h = make_harness(monkeypatch)
    logs = []

    def replace(_):
        monkeypatch.setattr(module, "log_event", lambda *a, **k: logs.append((a, k)))
        monkeypatch.setattr(module.time, "monotonic", lambda: 12.5)

    h.hooks["pipeline.chunked.start"] = replace
    await execute(h)
    assert len(logs) == 1
    assert logs[0][0] == (h.run_logger, "pipeline.chunked.finish")
    assert logs[0][1]["duration_ms"] == 2500
    assert "pipeline.chunked.finish" not in h.events


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["set", "enumerate", "len", "sum", "next", "round", "dict"])
async def test_builtin_ports_can_still_be_overridden_in_the_original_module(monkeypatch, name):
    h = make_harness(monkeypatch)
    observed = []

    def override(*args):
        observed.append(args)
        if name == "next":
            return "forced-batch"
        if name == "round":
            return 987
        return getattr(builtins, name)(*args)

    monkeypatch.setattr(module, name, override, raising=False)
    output = await execute(h)
    assert observed
    if name == "set":
        assert len(observed) == 1 and observed[0] == ()
    elif name == "enumerate":
        assert observed == [(h.arguments["chunk_ranges"],)]
    elif name == "sum":
        assert len(observed) == 3
    elif name == "next":
        assert output["batch_id"] == "forced-batch"
    elif name == "round":
        assert h.records["pipeline.chunked.finish"][0][1]["duration_ms"] == 987
    elif name == "dict":
        assert observed == [(h.index_stats,)]
        assert observed[0][0] is h.index_stats


@pytest.mark.asyncio
async def test_exception_global_controls_which_load_errors_are_caught(monkeypatch):
    h = make_harness(monkeypatch)
    error = RuntimeError("not a ValueError")
    fail_at(h, "load", error)
    monkeypatch.setattr(module, "Exception", ValueError, raising=False)
    with pytest.raises(RuntimeError) as caught:
        await execute(h)
    assert caught.value is error and "load_fallback" not in h.events


@pytest.mark.asyncio
async def test_optional_subject_and_image_arguments_keep_none_defaults(monkeypatch):
    h = make_harness(monkeypatch)
    for name in ("subject_id", "page_images", "page_image_refs"):
        h.arguments.pop(name)
    await execute(h)
    assert all(
        call[name] is None
        for call in h.chunk_calls
        for name in ("subject_id", "page_images", "page_image_refs")
    )
