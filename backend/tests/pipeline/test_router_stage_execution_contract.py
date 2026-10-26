"""Budget and concurrent model execution preserve stage-local degradation rules."""

import asyncio
from types import SimpleNamespace

import pytest

from app.features import candidate_evaluator, token_budget
from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.router_stage_support import result_for, router_harness


def events(h, name):
    return [event for event in h.events if event[0] == name]


@pytest.mark.asyncio
async def test_budget_denial_skips_model_without_usage_and_copies_candidate(
    monkeypatch,
):
    h = router_harness(monkeypatch)
    h.allowed = False
    opts, db = {}, object()
    result = await h.pipeline._run_ocr_correction_router(h.blocks, opts, db)
    assert events(h, "config")[0][1] == (opts, db)
    assert events(h, "configure")[0][1][0] is h.config
    assert events(h, "check")[0][1] == (15, h.config)
    assert events(h, "fix") == events(h, "usage") == events(h, "evaluate") == []
    assert result["normalized_blocks"][0] == h.blocks[0]
    assert result["normalized_blocks"][0] is not h.blocks[0]
    correction = result["ocr_correction_diagnostics"]["corrections"][0]
    assert correction["reason"] == "token_limit"
    assert correction["before_preview"] == {"text": "original"}
    assert result["ocr_correction_diagnostics"]["stats"] == {
        "total_blocks": 1,
        "noisy_blocks": 1,
        "corrected_blocks": 0,
        "skipped_blocks": 0,
        "model_used": "none",
    }
    assert events(h, "record_unchanged")[0][2]["model"] == "skipped_budget"


@pytest.mark.asyncio
async def test_empty_and_unselected_blocks_keep_identity_and_classify_before_fix(
    monkeypatch,
):
    h = router_harness(monkeypatch)
    h.blocks = [
        {"normalized_text": ""},
        {"normalized_text": "skip"},
        {"normalized_text": "fix", "page": 9},
    ]
    calls = []

    def should(score, config, **kwargs):
        calls.append(kwargs)
        return len(calls) > 1

    monkeypatch.setattr(orchestrator, "_should_correct", should)
    output = await h.pipeline._run_ocr_correction_router(
        h.blocks, {}, None, page_images={9: b"image"}
    )
    assert output["normalized_blocks"][0] is h.blocks[0]
    assert output["normalized_blocks"][1] is h.blocks[1]
    assert output["normalized_blocks"][2] is not h.blocks[2]
    assert calls == [{"structure_score": 0.31, "has_image": True}] * 2
    names = [event[0] for event in h.events]
    assert names.index("record_classification") < names.index("check")
    fix = events(h, "fix")[0][2]
    assert fix == {
        "image": b"image",
        "ocr_text": "fix",
        "context": {
            "block_index": 2,
            "page": 9,
            "entry_point": "ocr_correction_router",
            "has_options": False,
        },
    }
    assert [
        item["corrected"]
        for item in output["ocr_correction_diagnostics"]["corrections"]
    ] == [False, True]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [RuntimeError("model"), asyncio.CancelledError("child")]
)
async def test_child_model_error_and_child_cancellation_degrade_to_original(
    monkeypatch, failure
):
    h = router_harness(monkeypatch)
    h.results[0] = failure
    output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert output["normalized_blocks"][0] is h.blocks[0]
    reason = "" if isinstance(failure, asyncio.CancelledError) else str(failure)
    assert (
        output["ocr_correction_diagnostics"]["corrections"][0]["reason"]
        == f"exception: {reason}"
    )
    assert events(h, "record_failure")[0][2] == {
        "model": "exception",
        "before": "original",
    }
    assert events(h, "usage") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata,tokens,expected",
    [
        ({}, 7, 7),
        ({"router_call_stats": {"tokens_used": 23}}, 7, 23),
        ({"router_call_stats": {"tokens_used": 0}}, 7, None),
        ({"router_call_stats": {"tokens_used": "11"}}, None, 11),
    ],
)
async def test_usage_prefers_router_metadata_before_processing_results(
    monkeypatch,
    metadata,
    tokens,
    expected,
):
    h = router_harness(monkeypatch)
    h.results[0] = result_for(tokens_used=tokens, metadata=metadata)
    await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert [item[1][0] for item in events(h, "usage")] == (
        [] if expected is None else [expected]
    )
    if expected is not None:
        names = [event[0] for event in h.events]
        assert names.index("usage") < names.index("evaluate")


@pytest.mark.asyncio
async def test_usage_failure_discards_candidate_after_model_execution(monkeypatch):
    h = router_harness(monkeypatch)
    error = RuntimeError("usage")

    async def fail(tokens):
        raise error

    monkeypatch.setattr(token_budget, "record_token_usage", fail)
    output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert len(events(h, "fix")) == 1 and events(h, "evaluate") == []
    assert output["normalized_blocks"][0] is h.blocks[0]
    assert (
        output["ocr_correction_diagnostics"]["corrections"][0]["reason"]
        == "exception: usage"
    )


@pytest.mark.asyncio
async def test_three_concurrent_fixes_keep_input_processing_order(monkeypatch):
    h = router_harness(monkeypatch)
    h.blocks = [{"normalized_text": f"block{i}"} for i in range(5)]
    active, peak = 0, 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fix(**kwargs):
        nonlocal active, peak
        index = kwargs["context"]["block_index"]
        active += 1
        peak = max(peak, active)
        if active == 3:
            entered.set()
        await release.wait()
        active -= 1
        return result_for(text=f"fixed{index}")

    h.router.fix = fix
    task = asyncio.create_task(
        h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert peak == 3 and len(events(h, "check")) == 3
    finally:
        release.set()
    output = await asyncio.wait_for(task, 2)
    assert peak == 3
    assert [event[2]["original_text"] for event in events(h, "evaluate")] == [
        f"block{i}" for i in range(5)
    ]
    assert len(output["normalized_blocks"]) == 5


@pytest.mark.asyncio
async def test_parent_cancellation_propagates_and_stops_queued_work(monkeypatch):
    h = router_harness(monkeypatch)
    h.blocks = [{"normalized_text": f"block{i}"} for i in range(5)]
    entered = asyncio.Event()
    cancelled = []

    async def fix(**kwargs):
        index = kwargs["context"]["block_index"]
        if index == 2:
            entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(index)
            raise

    h.router.fix = fix
    task = asyncio.create_task(
        h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    )
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sorted(cancelled) == [0, 1, 2]
    assert events(h, "flush") == events(h, "evaluate") == []


@pytest.mark.asyncio
async def test_out_of_order_completion_retains_candidate_text_layout_and_input_association(
    monkeypatch,
):
    h = router_harness(monkeypatch)
    h.blocks = [{"normalized_text": f"input{i}"} for i in range(3)]
    gates = [asyncio.Event() for _ in h.blocks]
    done = [asyncio.Event() for _ in h.blocks]
    finished = []

    async def fix(**kwargs):
        index = kwargs["context"]["block_index"]
        await gates[index].wait()
        finished.append(index)
        done[index].set()
        return result_for(
            text=f"fixed{index}",
            metadata={
                "layout_blocks": [{"type": "table", "source_index": index}],
            },
        )

    def evaluate(**kwargs):
        h.events.append(("evaluate", (), kwargs))
        return SimpleNamespace(
            **{**vars(h.decision), "accepted_text": kwargs["candidate_text"]}
        )

    h.router.fix = fix
    monkeypatch.setattr(
        candidate_evaluator, "get_evaluator", lambda: SimpleNamespace(evaluate=evaluate)
    )
    task = asyncio.create_task(
        h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    )
    try:
        for index in [2, 0, 1]:
            gates[index].set()
            await asyncio.wait_for(done[index].wait(), 2)
    finally:
        for gate in gates:
            gate.set()
    output = await asyncio.wait_for(task, 2)
    assert finished == [2, 0, 1]
    assert [
        (e[2]["original_text"], e[2]["candidate_text"]) for e in events(h, "evaluate")
    ] == [(f"input{i}", f"fixed{i}") for i in range(3)]
    for index, block in enumerate(output["normalized_blocks"]):
        assert block["normalized_text"] == f"fixed{index}"
        assert block["vl_layout_blocks"] == [{"type": "table", "source_index": index}]
