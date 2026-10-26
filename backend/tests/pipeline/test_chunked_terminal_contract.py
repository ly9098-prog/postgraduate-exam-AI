"""Final checkpoint precedes aggregate observations and response publication."""

import asyncio
from copy import deepcopy

import pytest

from tests.pipeline.chunked_run_support import execute, fail_at, make_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_terminal_payload_and_first_nonempty_batch_keep_original_contract(monkeypatch, failed):
    h = make_harness(monkeypatch)
    if failed:
        h.outcomes[0].update(status="failed", error_message="broken", batch_id="failed-batch")
    expected_outcomes, expected_risk = deepcopy(h.outcomes), deepcopy(h.risk)
    output = await execute(h)
    status = "paused" if failed else "completed"
    errors = ["chunk 0 (pages 1-2) failed: broken"] if failed else []
    assert output == {
        "pipeline_id": "chunked-contract", "status": status,
        "batch_id": "failed-batch" if failed else "first",
        "stats": {
            "total_chunks": 2, "completed_chunks": 1 if failed else 2,
            "failed_chunks": 1 if failed else 0, "to_review": 7,
            "extracted": 4, "total": 4,
        },
        "diagnostics": {
            "chunked": True, "chunk_size": 2, "chunk_overlap": 1, "total_pages": 4,
            "risk_flag_counts": expected_risk, "chunks": expected_outcomes,
            "hash_index": {"queries": 9},
        },
        "stages": {}, "errors": errors, "started_at": "started", "finished_at": "finished",
    }
    assert output["diagnostics"]["risk_flag_counts"] is h.risk
    assert all(actual is original
               for actual, original in zip(output["diagnostics"]["chunks"], h.outcomes))
    assert output["diagnostics"]["hash_index"] is not h.index_stats
    assert h.records["final"] == [(
        h.sessions[4], "chunked-contract",
        {"status": status, "error_message": errors[0] if errors else None, "finished": True},
    )]
    event = "pipeline.chunked.paused" if failed else "pipeline.chunked.finish"
    assert h.records[event] == [(h.run_logger, {
        "level": "warning" if failed else "info", "pipeline_id": "chunked-contract",
        "total_pages": 4, "chunk_size": 2, "chunk_overlap": 1, "total_chunks": 2,
        "completed_chunks": 1 if failed else 2, "failed_chunks": 1 if failed else 0,
        "status": status, "duration_ms": 125,
    })]
    assert h.events[-9:] == [
        "final", "exit:4", "invalidate", "merge", "utc", "serialize",
        "clock", event, "index_stats",
    ]


@pytest.mark.asyncio
async def test_unknown_chunk_status_does_not_become_a_failure_and_counts_falsy_as_zero(monkeypatch):
    h = make_harness(monkeypatch)
    h.outcomes[0].update(status="skipped", question_count=None, batch_id="")
    h.outcomes[1]["question_count"] = 0
    output = await execute(h)
    assert output["status"] == "completed" and output["errors"] == []
    assert output["stats"]["completed_chunks"] == 1
    assert output["stats"]["failed_chunks"] == output["stats"]["to_review"] == 0
    assert output["batch_id"] == "second"


@pytest.mark.asyncio
async def test_multiple_failed_outcomes_continue_and_persist_only_the_first_error(monkeypatch):
    h = make_harness(monkeypatch)
    for index, outcome in enumerate(h.outcomes):
        outcome.update(status="failed", error_message=f"error-{index}", batch_id="")
    output = await execute(h)
    assert len(h.chunk_calls) == 2 and output["batch_id"] == ""
    assert output["errors"] == [
        "chunk 0 (pages 1-2) failed: error-0", "chunk 1 (pages 3-4) failed: error-1",
    ]
    assert h.records["final"][0][2]["error_message"] == output["errors"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "point",
    ["enter:4", "final", "exit:4", "invalidate", "merge", "utc", "serialize",
     "pipeline.chunked.finish", "index_stats"],
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_terminal_errors_propagate_after_index_cleanup_without_retry(monkeypatch, point, error_type):
    h = make_harness(monkeypatch)
    error = error_type(point)
    fail_at(h, point, error)
    with pytest.raises(error_type) as caught:
        await execute(h)
    assert caught.value is error
    assert h.index._question_index == h.index._import_index == {}
    assert h.events.count(point) == 1
    if point in {"enter:4", "final", "exit:4"}:
        assert "invalidate" not in h.events


@pytest.mark.asyncio
async def test_invalidation_mutation_is_visible_to_later_aggregate_and_publication(monkeypatch):
    h = make_harness(monkeypatch)

    def mutate(_):
        h.arguments["chunk_ranges"].append((5, 6))
        h.outcomes[0]["question_count"] = 8
        h.pipeline.pipeline_id = "changed-after-final"

    h.hooks["invalidate"] = mutate
    output = await execute(h)
    assert output["stats"]["total_chunks"] == 3 and output["stats"]["to_review"] == 12
    assert output["stats"]["total"] == 4
    assert output["pipeline_id"] == "changed-after-final"
    assert h.records["final"][0][1] == "chunked-contract"
