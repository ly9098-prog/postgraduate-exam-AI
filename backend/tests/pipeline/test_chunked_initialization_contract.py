"""Checkpoint setup and hash loading retain their original session boundaries."""

import asyncio

import pytest

from tests.pipeline.chunked_run_support import execute, fail_at, make_harness


@pytest.mark.asyncio
async def test_initialization_uses_two_closed_sessions_before_executing_chunks(monkeypatch):
    h = make_harness(monkeypatch)
    await execute(h)
    assert h.events[:15] == [
        "size", "overlap", "derive", "watermark", "enter:0", "parent", "chunks",
        "exit:0", "construct_index", "enter:1", "load", "exit:1",
        "get_logger", "clock", "pipeline.chunked.start",
    ]
    assert h.records["derive"] == [h.arguments["db"]]
    assert h.records["watermark"][0] is h.arguments["shared"]["watermark_patterns"]
    db, parent = h.records["parent"][0]
    assert db is h.sessions[0]
    assert parent == {
        "pipeline_id": "chunked-contract", "source_type": "pdf",
        "source_file": "input.pdf", "total_pages": 4, "chunk_size": 2,
        "created_by": "admin", "source_sha256": "sha",
        "watermark_snapshot": h.watermark,
    }
    assert parent["watermark_snapshot"] is h.watermark
    assert h.records["chunks"][0] == (
        h.sessions[0], "chunked-contract", h.arguments["chunk_ranges"],
    )
    assert h.records["chunks"][0][2] is h.arguments["chunk_ranges"]
    assert h.records["load"] == [h.sessions[1]] and not h.active
    assert h.records["pipeline.chunked.start"] == [(h.run_logger, {
        "pipeline_id": "chunked-contract", "total_pages": 4, "chunk_size": 2,
        "chunk_overlap": 1, "total_chunks": 2,
    })]


@pytest.mark.asyncio
async def test_empty_source_and_watermark_are_stored_as_none(monkeypatch):
    h = make_harness(monkeypatch)
    h.watermark.clear()
    await execute(h, source_file="", shared={})
    assert h.records["watermark"] == [[]]
    assert h.records["parent"][0][1]["source_file"] is None
    assert h.records["parent"][0][1]["watermark_snapshot"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["enter:1", "load", "exit:1"])
async def test_ordinary_hash_session_failure_falls_back_without_attaching_index(
    monkeypatch, point
):
    h = make_harness(monkeypatch)
    error = RuntimeError(point)
    fail_at(h, point, error)
    output = await execute(h)
    assert output["status"] == "completed" and output["diagnostics"]["hash_index"] is None
    assert h.records["load_fallback"] == [
        "GlobalHashIndex.load failed; chunked similarity match will fallback"
    ]
    if point != "enter:1":
        assert h.events.index("exit:1") < h.events.index("load_fallback")
        if point == "load":
            assert h.records["exit:1"] == [(RuntimeError, error)]
    assert "clear_questions" not in h.events and "clear_imports" not in h.events
    assert h.index._question_index == {"seed": 1}
    assert all(call["hash_index"] is None for call in h.chunk_calls)
    assert all(call["shared"] is h.arguments["shared"] for call in h.chunk_calls)


@pytest.mark.asyncio
async def test_hash_load_error_suppressed_by_session_keeps_index_without_fallback(monkeypatch):
    h = make_harness(monkeypatch)
    h.suppress[1] = True
    error = RuntimeError("suppressed load")
    fail_at(h, "load", error)
    output = await execute(h)
    assert h.records["exit:1"] == [(RuntimeError, error)]
    assert "load_fallback" not in h.events
    assert all(call["hash_index"] is h.index for call in h.chunk_calls)
    assert h.chunk_calls[0]["shared"]["hash_index"] is h.index
    assert output["diagnostics"]["hash_index"] == {"queries": 9}
    assert h.index._question_index == h.index._import_index == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "point",
    ["size", "overlap", "derive", "watermark", "enter:0", "parent", "chunks",
     "exit:0", "construct_index", "get_logger", "clock", "pipeline.chunked.start"],
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_setup_errors_propagate_without_broadening_cleanup_scope(
    monkeypatch, point, error_type
):
    h = make_harness(monkeypatch)
    error = error_type(point)
    fail_at(h, point, error)
    with pytest.raises(error_type) as caught:
        await execute(h)
    assert caught.value is error
    assert not h.chunk_calls and "final" not in h.events
    assert "clear_questions" not in h.events and "clear_imports" not in h.events
    if h.index is not None:
        assert h.index._question_index == {"seed": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["enter:1", "load", "exit:1"])
async def test_hash_loading_cancellation_is_not_converted_into_fallback(monkeypatch, point):
    h = make_harness(monkeypatch)
    error = asyncio.CancelledError(point)
    fail_at(h, point, error)
    with pytest.raises(asyncio.CancelledError) as caught:
        await execute(h)
    assert caught.value is error and "load_fallback" not in h.events
    assert not h.chunk_calls and "clear_questions" not in h.events


@pytest.mark.asyncio
async def test_fallback_logger_failure_propagates_before_execution(monkeypatch):
    h = make_harness(monkeypatch)
    fail_at(h, "load", RuntimeError("load"))
    error = RuntimeError("logging")
    fail_at(h, "load_fallback", error)
    with pytest.raises(RuntimeError) as caught:
        await execute(h)
    assert caught.value is error and not h.chunk_calls
    assert "clear_questions" not in h.events


@pytest.mark.asyncio
async def test_empty_ranges_fail_before_any_port_is_resolved(monkeypatch):
    h = make_harness(monkeypatch)
    with pytest.raises(IndexError):
        await execute(h, chunk_ranges=[])
    assert not h.events
