"""Chunks share dedup state and close each session before inspecting outcomes."""

import asyncio
from copy import deepcopy

import pytest

from tests.pipeline.chunked_run_support import execute, fail_at, make_harness


def assert_chunk_arguments(h, call, index, expected_shared):
    start, end = h.arguments["chunk_ranges"][index]
    assert call == {
        "chunk_index": index, "page_start": start, "logical_end": end,
        "total_pages": 4, "is_last_chunk": index == 1, "chunk_overlap": 1,
        "file_content": h.arguments["file_content"],
        "file_path": h.arguments["file_path"], "source_type": "pdf",
        "source_file": "input.pdf", "subject": "math", "subject_id": 7,
        "opts": h.arguments["opts"], "db": h.sessions[index + 2],
        "shared": expected_shared,
        "progress_callback": h.arguments["progress_callback"], "started_at": "started",
        "seen_hashes": {"seen:0", "seen:1"}, "hash_index": h.index,
        "page_images": h.arguments["page_images"],
        "page_image_refs": h.arguments["page_image_refs"],
    }
    for name in ("opts", "page_images", "page_image_refs", "progress_callback"):
        assert call[name] is h.arguments[name]
    assert call["db"] is h.sessions[index + 2]
    assert call["hash_index"] is h.index


@pytest.mark.asyncio
async def test_each_chunk_gets_its_own_session_and_the_same_live_dedup_state(monkeypatch):
    h = make_harness(monkeypatch)
    h.arguments["shared"]["strategy"] = {"mode": "literal"}
    original_refs = dict(h.arguments["shared"])
    expected_shared = deepcopy(h.arguments["shared"])
    snapshots = []
    for index in range(2):
        h.hooks[f"chunk:{index}"] = lambda call: snapshots.append(set(call["seen_hashes"]))
    output = await execute(h)
    assert len(h.sessions) == 5 and not h.active
    assert snapshots == [set(), {"seen:0"}]
    expected_shared["hash_index"] = h.index
    for index, call in enumerate(h.chunk_calls):
        assert_chunk_arguments(h, call, index, expected_shared)
    first, second = h.chunk_calls
    assert first["seen_hashes"] is second["seen_hashes"]
    assert first["shared"] is second["shared"]
    assert first["shared"] is not h.arguments["shared"]
    for name, value in original_refs.items():
        assert first["shared"][name] is value
    assert first["shared"]["nested"] is h.arguments["shared"]["nested"]
    assert first["shared"]["hash_index"] is h.index
    assert "hash_index" not in h.arguments["shared"]
    assert output["diagnostics"]["chunks"][0] is h.outcomes[0]
    assert output["diagnostics"]["chunks"][1] is h.outcomes[1]
    assert h.events.index("exit:3") < h.events.index("clear_questions")
    assert h.events.index("clear_imports") < h.events.index("enter:4")


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["enter:2", "chunk:0", "exit:2", "chunk:1", "exit:3"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_uncaught_chunk_boundary_error_cleans_index_and_does_not_finalize(
    monkeypatch, point, error_type
):
    h = make_harness(monkeypatch)
    error = error_type(point)
    fail_at(h, point, error)
    with pytest.raises(error_type) as caught:
        await execute(h)
    assert caught.value is error
    assert h.events[-2:] == ["clear_questions", "clear_imports"]
    assert h.index._question_index == h.index._import_index == {}
    assert "final" not in h.events and "invalidate" not in h.events


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["clear_questions", "clear_imports"])
async def test_cleanup_error_masks_chunk_error_without_attempting_finalization(monkeypatch, point):
    h = make_harness(monkeypatch)
    original = RuntimeError("chunk")
    cleanup = ValueError("cleanup")
    fail_at(h, "chunk:0", original)
    fail_at(h, point, cleanup)
    with pytest.raises(ValueError) as caught:
        await execute(h)
    assert caught.value is cleanup and cleanup.__context__ is original
    assert h.events[-1] == point and "final" not in h.events


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["load", "chunk"])
async def test_real_task_cancellation_retains_original_cleanup_extent(monkeypatch, phase):
    h = make_harness(monkeypatch)
    entered = asyncio.Event()

    async def wait(*_):
        entered.set()
        await asyncio.Event().wait()

    if phase == "load":
        h.load_wait = wait
    else:
        h.chunk_wait = wait
    task = asyncio.create_task(execute(h))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    except BaseException:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    task.cancel("cancel chunked")
    with pytest.raises(asyncio.CancelledError, match="cancel chunked"):
        await task
    assert ("clear_questions" in h.events) is (phase == "chunk")
    assert "final" not in h.events and not h.active


@pytest.mark.asyncio
async def test_session_exit_precedes_outcome_status_read(monkeypatch):
    h = make_harness(monkeypatch)

    class Outcome(dict):
        def __getitem__(self, key):
            if key == "status":
                assert "exit:2" in h.events and not h.active
            return super().__getitem__(key)

    h.outcomes[0] = Outcome(h.outcomes[0])
    await execute(h)


@pytest.mark.asyncio
async def test_suppressed_first_chunk_exception_retains_unbound_outcome_error(monkeypatch):
    h = make_harness(monkeypatch)
    h.suppress[2] = True
    fail_at(h, "chunk:0", RuntimeError("suppressed"))
    with pytest.raises(UnboundLocalError, match="outcome"):
        await execute(h)
    assert h.events[-2:] == ["clear_questions", "clear_imports"]


@pytest.mark.asyncio
async def test_suppressed_later_chunk_exception_reuses_previous_outcome_reference(monkeypatch):
    h = make_harness(monkeypatch)
    h.suppress[3] = True
    error = RuntimeError("suppressed second chunk")
    fail_at(h, "chunk:1", error)
    output = await execute(h)
    assert h.records["exit:3"] == [(RuntimeError, error)]
    first, second = output["diagnostics"]["chunks"]
    assert first is second is h.outcomes[0]
    assert output["stats"]["to_review"] == 6
    assert output["stats"]["completed_chunks"] == 2
    assert output["status"] == "completed" and output["errors"] == []
