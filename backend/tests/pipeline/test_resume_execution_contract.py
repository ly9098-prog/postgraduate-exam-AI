"""Resume failure, cancellation, terminal and independent-session boundaries."""

import asyncio

import pytest

from tests.pipeline.resume_run_support import execute, fail_at, make_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["enter:0", "load", "exit:0"])
async def test_ordinary_index_session_failure_falls_back(monkeypatch, point):
    h = make_harness(monkeypatch)
    fail_at(h, point, RuntimeError(point))
    await execute(h)
    assert "exception" in h.events and "clear_questions" not in h.events
    assert all(
        call["hash_index"] is None and "hash_index" not in call["shared"]
        for call in h.calls
    )
    assert h.index._question_index == h.index._import_index == {"seed": 1}


@pytest.mark.asyncio
async def test_empty_completed_ids_and_missing_total_and_source_fallbacks(monkeypatch):
    h = make_harness(monkeypatch)
    h.chunks[0].batch_id = ""
    h.row.total_pages, h.row.source_type, h.row.source_file = 0, None, None
    await execute(h)
    assert h.records["load"][0][1] == {"batch_ids": None}
    assert h.calls[0]["total_pages"] == 90
    assert h.calls[0]["source_type"] == "pdf" and h.calls[0]["source_file"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "point",
    [
        "derive",
        "query_pipeline",
        "pending",
        "query_chunks",
        "overlap",
        "strategy",
        "construct_index",
        "seen",
        "status:running",
        "invalidate",
        "construct_pipeline",
        "utc",
        "serialize",
    ],
)
@pytest.mark.parametrize("kind", [RuntimeError, asyncio.CancelledError])
async def test_preloop_failure_keeps_index_without_expanding_cleanup(
    monkeypatch, point, kind
):
    h = make_harness(monkeypatch)
    error = kind(point)
    fail_at(h, point, error)
    with pytest.raises(kind) as caught:
        await execute(h)
    assert caught.value is error and not h.calls
    assert "clear_questions" not in h.events and "progress" not in h.events


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["enter:0", "load", "exit:0"])
async def test_index_cancellation_is_not_fallback(monkeypatch, point):
    h = make_harness(monkeypatch)
    error = asyncio.CancelledError(point)
    fail_at(h, point, error)
    with pytest.raises(asyncio.CancelledError) as caught:
        await execute(h)
    assert caught.value is error and "exception" not in h.events and not h.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["enter:3", "chunk:0", "exit:3", "chunk:1"])
@pytest.mark.parametrize("kind", [RuntimeError, asyncio.CancelledError])
async def test_replay_errors_clear_both_maps_and_skip_terminal(
    monkeypatch, point, kind
):
    h = make_harness(monkeypatch)
    error = kind(point)
    fail_at(h, point, error)
    with pytest.raises(kind) as caught:
        await execute(h)
    assert caught.value is error and h.events[-2:] == [
        "clear_questions",
        "clear_imports",
    ]
    assert h.index._question_index == h.index._import_index == {}
    assert "progress" not in h.events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,progress,want",
    [
        ("completed", None, "completed"),
        ("completed", {}, "completed"),
        ("completed", {"failed_chunks": 1}, "paused"),
        ("failed", {"failed_chunks": 0}, "paused"),
        ("unknown", {"failed_chunks": 0}, "completed"),
    ],
)
async def test_terminal_uses_both_exact_replay_status_and_uncached_persisted_failures(
    monkeypatch, status, progress, want
):
    h = make_harness(monkeypatch)
    h.outcomes[0]["status"], h.progress = status, progress
    await execute(h)
    assert len(h.calls) == 2
    assert h.records["progress"] == [
        (h.sessions[5], "resume-contract", {"use_cache": False})
    ]
    assert h.records["status:" + want][-1] == (
        h.sessions[5],
        "resume-contract",
        {
            "status": want,
            "finished": want == "completed",
        },
    )
    assert h.events[-1] == "invalidate"


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["enter:5", "progress", "status:completed", "exit:5"])
async def test_terminal_failure_occurs_after_cleanup_before_final_invalidation(
    monkeypatch, point
):
    h = make_harness(monkeypatch)
    error = RuntimeError(point)
    fail_at(h, point, error)
    with pytest.raises(RuntimeError) as caught:
        await execute(h)
    assert caught.value is error and h.index._question_index == {}
    assert h.events.count("invalidate") == 1


@pytest.mark.asyncio
async def test_cleanup_failure_replaces_chunk_failure_and_stops_second_clear(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    original, replacement = RuntimeError("chunk"), RuntimeError("clear")
    fail_at(h, "chunk:0", original)
    fail_at(h, "clear_questions", replacement)
    with pytest.raises(RuntimeError) as caught:
        await execute(h)
    assert caught.value is replacement and replacement.__context__ is original
    assert "clear_imports" not in h.events and "progress" not in h.events


@pytest.mark.asyncio
async def test_suppressed_hash_load_retains_index(monkeypatch):
    h = make_harness(monkeypatch)
    h.suppress[0] = True
    fail_at(h, "load", RuntimeError("load"))
    await execute(h)
    assert "exception" not in h.events and h.calls[0]["hash_index"] is h.index


@pytest.mark.asyncio
async def test_suppressed_seen_assignment_fails_only_at_first_chunk_expression(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    h.suppress[1] = True
    fail_at(h, "seen", RuntimeError("seen"))
    with pytest.raises(UnboundLocalError, match="seen_hashes"):
        await execute(h)
    assert "construct_pipeline" in h.events and "enter:3" in h.events and not h.calls
    assert h.events[-2:] == ["clear_questions", "clear_imports"]


@pytest.mark.asyncio
@pytest.mark.parametrize("number", [3, 4])
async def test_suppressed_chunk_error_keeps_historical_outcome_scope(
    monkeypatch, number
):
    h = make_harness(monkeypatch)
    h.suppress[number] = True
    fail_at(h, f"chunk:{number - 3}", RuntimeError("chunk"))
    if number == 3:
        with pytest.raises(UnboundLocalError, match="outcome"):
            await execute(h)
        assert "progress" not in h.events
    else:
        await execute(h)
        assert len(h.calls) == 1 and "status:completed" in h.events
    assert h.index._question_index == h.index._import_index == {}


@pytest.mark.asyncio
async def test_suppressed_final_progress_error_skips_status_but_invalidates_cache(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    h.suppress[5] = True
    error = RuntimeError("suppressed progress")
    fail_at(h, "progress", error)
    assert await execute(h) is None
    assert h.records["exit:5"] == [(RuntimeError, error)]
    assert h.events.count("invalidate") == 2 and "status:completed" not in h.events
    assert h.events[-3:] == ["progress", "exit:5", "invalidate"]
    assert h.index._question_index == h.index._import_index == {}
