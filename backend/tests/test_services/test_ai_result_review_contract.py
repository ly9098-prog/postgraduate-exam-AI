"""Parse/usage/visual review ordering and references before final projection."""

import asyncio

import pytest

from app.services.ai import analysis_result_review as module
from tests.test_services.analysis_orchestration_support import assert_task_cancellation
from tests.test_services.analysis_result_review_support import review_harness

STAGES = ["parse", "validate", "usage", "request", "reconcile", "ack", "constructor"]


@pytest.mark.asyncio
async def test_review_full_arguments_sequence_and_original_objects(monkeypatch):
    h = review_harness(monkeypatch)
    values = h.kwargs.copy()
    runtime = h.invocation.runtime
    reviewed = await module.review_analysis_result(h.invocation, **h.kwargs)
    assert [name for name, *_ in h.events] == STAGES
    assert h.events[0][1] == (h.raw,)
    assert h.events[0][1][0] is h.raw
    assert h.events[1][1][0] is h.parsed
    assert h.events[2][2] == dict(
        raw_content=h.raw, result=h.result, image_data_urls=values["image_data_urls"],
        extract_evidence=values["extract_evidence"],
    )
    assert h.events[2][2]["image_data_urls"] is values["image_data_urls"]
    assert h.events[2][2]["result"] is h.result
    assert h.requests == [dict(
        result=h.result, image_data_urls=values["image_data_urls"], runtime=runtime,
        wrong_question_id=values["wrong_question_id"], chat=values["chat"],
        **{key: values[key] for key in (
            "extract_evidence", "validate_answer_check", "diagnosis_contradicts_grounding",
            "evidence_is_valid", "should_retry_visual_ack", "retry_visual_ack",
        )},
    )]
    assert h.requests[0]["image_data_urls"] is values["image_data_urls"]
    assert h.requests[0]["result"] is h.result
    assert h.requests[0]["runtime"] is runtime
    args, kwargs = h.events[4][1:]
    assert args[1] is h.parsed
    assert kwargs == dict(
        parsed_valid=h.valid, expected_answer_check=values["expected_answer_check"],
        answer_grounding=values["answer_grounding"], usage=h.usage,
    )
    assert kwargs["expected_answer_check"] is values["expected_answer_check"]
    assert kwargs["answer_grounding"] is values["answer_grounding"]
    assert kwargs["usage"] is h.usage
    assert h.events[5][2]["image_data_urls"] is values["image_data_urls"]
    assert reviewed.parsed is h.parsed
    assert reviewed.parsed_valid is h.valid
    assert reviewed.usage is h.usage
    assert reviewed.grounding is h.grounding
    assert reviewed.ack_failure is h.ack


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
async def test_review_propagates_failures_without_later_phases(monkeypatch, stage, failure_type):
    failure = failure_type(stage)
    h = review_harness(monkeypatch, fail_at=stage, failure=failure)
    with pytest.raises(failure_type) as caught:
        await module.review_analysis_result(h.invocation, **h.kwargs)
    assert caught.value is failure
    assert [name for name, *_ in h.events] == STAGES[: STAGES.index(stage) + 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [None, 0, {}, [], ""])
async def test_review_passes_raw_content_without_coercion(monkeypatch, content):
    h = review_harness(monkeypatch)
    h.result["content"] = content
    await module.review_analysis_result(h.invocation, **h.kwargs)
    assert h.events[0][1][0] is content
    assert h.events[2][2]["raw_content"] is content


@pytest.mark.asyncio
async def test_missing_content_uses_empty_string_and_empty_images_still_reconcile(monkeypatch):
    h = review_harness(monkeypatch)
    h.result.clear()
    images = []
    h.kwargs["image_data_urls"] = images
    await module.review_analysis_result(h.invocation, **h.kwargs)
    assert h.events[0][1] == ("",)
    assert [name for name, *_ in h.events] == STAGES
    assert h.requests[0]["image_data_urls"] is images


@pytest.mark.asyncio
async def test_visual_reconciliation_mutations_reach_ack_and_final_review(monkeypatch):
    h = review_harness(monkeypatch)
    images = h.kwargs["image_data_urls"]

    async def reconcile(request, parsed, **kwargs):
        assert request.result is h.result
        assert request.image_data_urls is images
        assert parsed is h.parsed and kwargs["usage"] is h.usage
        h.usage.visual_evidence = "after-retry"
        h.usage.visual_ack_retried = True
        h.usage.total_tokens_used = 99
        parsed["after"] = object()
        return h.grounding

    monkeypatch.setattr(module, "reconcile_visual_evidence", reconcile)
    reviewed = await module.review_analysis_result(h.invocation, **h.kwargs)
    ack = next(kwargs for name, _, kwargs in h.events if name == "ack")
    assert ack == dict(
        image_data_urls=images, visual_evidence="after-retry",
        evidence_is_valid=h.kwargs["evidence_is_valid"],
    )
    assert reviewed.usage is h.usage
    assert reviewed.usage.total_tokens_used == 99
    assert reviewed.parsed is h.parsed


@pytest.mark.asyncio
async def test_actual_task_cancellation_in_visual_reconciliation(monkeypatch):
    h = review_harness(monkeypatch)
    entered = asyncio.Event()

    async def reconcile(*_args, **_kwargs):
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(module, "reconcile_visual_evidence", reconcile)
    task = asyncio.create_task(module.review_analysis_result(h.invocation, **h.kwargs))
    await assert_task_cancellation(task, entered)
    assert [name for name, *_ in h.events] == STAGES[:4]
