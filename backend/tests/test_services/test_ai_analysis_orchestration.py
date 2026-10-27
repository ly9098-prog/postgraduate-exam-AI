"""Lease ownership and argument contracts at the public orchestration entry."""

import asyncio

import pytest

from app.services.ai import analysis_orchestration as module
from tests.test_services.analysis_orchestration_support import (
    assert_task_cancellation,
    expected_calls,
    harness,
)


@pytest.mark.asyncio
async def test_full_order_arguments_refreshed_signature_and_context_identity(monkeypatch):
    h = harness(monkeypatch)
    expected = expected_calls(h)
    original_fields = vars(h.request).copy()
    original_context = dict(h.inputs.context)
    assert await module.execute_locked_analysis(h.request) is h.response
    assert h.events == expected
    assert all(getattr(h.request, key) is value for key, value in original_fields.items())
    assert h.inputs.context["answer_grounding"] is h.inputs.prompt_grounding
    expected_context = {**original_context, "answer_grounding": h.inputs.prompt_grounding}
    assert h.inputs.context == expected_context
    assert h.context_snapshots == [("invoke", expected_context), ("resolve", expected_context)]
    assert h.events[1][1][1] is h.request.wrong_question
    assert h.events[2][1][1] is h.request.question
    for index in (3, 4):
        assert h.events[index][2]["context"] is h.inputs.context
        assert h.events[index][2]["image_data_urls"] is h.inputs.image_data_urls
        assert h.events[index][2]["inputs"] is h.inputs


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["cache", "inputs"])
@pytest.mark.parametrize("response", [{}, {"model": "early"}])
async def test_early_responses_keep_identity_and_still_release(monkeypatch, stage, response):
    h = harness(monkeypatch)
    getattr(h, stage).response = response
    assert await module.execute_locked_analysis(h.request) is response
    expected = ["begin", "cache"]
    if stage == "inputs":
        expected.append("inputs")
    assert [name for name, *_ in h.events] == expected + ["finish"]
    assert "answer_grounding" not in h.inputs.context


@pytest.mark.asyncio
async def test_no_lease_does_not_prepare_or_release(monkeypatch):
    h = harness(monkeypatch)
    h.results["begin"] = None
    response = object()
    monkeypatch.setattr(module, "generation_in_progress_response", lambda: response)
    assert await module.execute_locked_analysis(h.request) is response
    assert [name for name, *_ in h.events] == ["begin"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["begin", "cache", "inputs", "invoke", "resolve", "finish"])
@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
async def test_failure_and_cancellation_propagate_with_owned_lease_release(
    monkeypatch, stage, failure_type
):
    failure = failure_type(stage)
    h = harness(monkeypatch, fail_at=stage, failure=failure)
    with pytest.raises(failure_type) as caught:
        await module.execute_locked_analysis(h.request)
    assert caught.value is failure
    names = [name for name, *_ in h.events]
    assert names == ["begin", "cache", "inputs", "invoke", "resolve", "finish"][
        : names.index(stage) + 1
    ] + (["finish"] if stage not in {"begin", "finish"} else [])


@pytest.mark.asyncio
async def test_cleanup_failure_retains_original_failure_as_context(monkeypatch):
    failure, cleanup = RuntimeError("provider failed"), ValueError("release failed")
    h = harness(monkeypatch, fail_at="invoke", failure=failure)

    async def finish(**kwargs):
        h.events.append(("finish", (), kwargs))
        raise cleanup

    monkeypatch.setattr(module, "finish_analysis_generation", finish)
    with pytest.raises(ValueError) as caught:
        await module.execute_locked_analysis(h.request)
    assert caught.value is cleanup
    assert cleanup.__context__ is failure
    assert [name for name, *_ in h.events] == ["begin", "cache", "inputs", "invoke", "finish"]


@pytest.mark.asyncio
async def test_actual_task_cancellation_releases_before_propagating(monkeypatch):
    h = harness(monkeypatch)
    entered = asyncio.Event()

    async def invoke(**_kwargs):
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(module, "invoke_and_review_analysis", invoke)
    task = asyncio.create_task(module.execute_locked_analysis(h.request))
    await assert_task_cancellation(task, entered)
    assert [name for name, *_ in h.events] == ["begin", "cache", "inputs", "finish"]


@pytest.mark.asyncio
async def test_cache_callback_can_replace_input_port_and_request_values(monkeypatch):
    h = harness(monkeypatch)
    replacement = object()
    expected = expected_calls(h)
    expected[2][2]["runtime"] = replacement
    original_cache = module.review_locked_analysis_cache
    original_inputs = module.prepare_locked_analysis_inputs

    async def inputs(*args, **kwargs):
        assert kwargs["runtime"] is replacement
        return await original_inputs(*args, **kwargs)

    async def cache(*args, **kwargs):
        h.request.runtime = replacement
        monkeypatch.setattr(module, "prepare_locked_analysis_inputs", inputs)
        return await original_cache(*args, **kwargs)

    monkeypatch.setattr(module, "review_locked_analysis_cache", cache)
    assert await module.execute_locked_analysis(h.request) is h.response
    assert h.events == expected


@pytest.mark.asyncio
async def test_reading_refreshed_signature_precedes_cache_response(monkeypatch):
    h = harness(monkeypatch)
    failure = RuntimeError("signature")

    class Cache:
        response = {"model": "cached"}

        @property
        def input_signature(self):
            raise failure

    h.results["cache"] = Cache()
    with pytest.raises(RuntimeError) as caught:
        await module.execute_locked_analysis(h.request)
    assert caught.value is failure
    assert [name for name, *_ in h.events] == ["begin", "cache", "finish"]


@pytest.mark.asyncio
async def test_finally_reads_request_values_after_outcome_callback(monkeypatch):
    h = harness(monkeypatch)
    replacement_cache, replacement_generating = object(), set()

    async def resolve(**_kwargs):
        h.request.wrong_question.id = 9
        h.request.cache = replacement_cache
        h.request.generating = replacement_generating
        return h.response

    monkeypatch.setattr(module, "resolve_reviewed_analysis_outcome", resolve)
    assert await module.execute_locked_analysis(h.request) is h.response
    assert h.events[-1] == ("finish", (), dict(
        wrong_question_id=9, generating=replacement_generating,
        lease=h.lease, cache=replacement_cache,
    ))
