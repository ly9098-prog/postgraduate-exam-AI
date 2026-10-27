"""Input preparation preserves callback order, identity, and cancellation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai import analysis_preparation as module
from tests.test_services.analysis_orchestration_support import assert_task_cancellation
from tests.test_services.test_ai_analysis_preparation import harness

STAGES = [
    "revision_guard", "collect_visual_sources", "has_visual_slot", "load_knowledge_points",
    "load_runtime", "build_grounding", "input_signature", "model_signature",
    "cached_response", "stale_reason",
]
ASYNC = {"revision_guard", "load_knowledge_points", "load_runtime"}


def traced_request(*, fail_at=None, failure=None, **overrides):
    h = harness(**overrides)
    events = []

    def trace(name, original):
        def call(*args, **kwargs):
            events.append((name, args, kwargs))
            if name == fail_at:
                raise failure
            return original(*args, **kwargs)

        return call

    def trace_async(name, original):
        async def call(*args, **kwargs):
            events.append((name, args, kwargs))
            if name == fail_at:
                raise failure
            return await original(*args, **kwargs)

        return call

    for name in STAGES:
        original = getattr(h.request, name)
        setattr(h.request, name, (trace_async if name in ASYNC else trace)(name, original))
    return h, events


@pytest.mark.asyncio
async def test_preparation_sequence_and_input_object_references():
    runtime, grounding = object(), object()
    h, events = traced_request(
        load_runtime=AsyncMock(return_value=runtime),
        build_grounding=MagicMock(return_value=grounding),
    )
    original_points = h.load_knowledge_points.return_value[3]
    prepared = await module.prepare_analysis(h.request)
    assert [name for name, *_ in events] == STAGES
    assert prepared.question is h.question
    assert prepared.wrong_question is h.wrong
    assert prepared.knowledge_points is original_points
    assert prepared.runtime is runtime
    assert prepared.answer_grounding is grounding
    calls = {name: (args, kwargs) for name, args, kwargs in events}
    assert calls["build_grounding"] == ((), dict(
        question_type="single_choice", content=h.question.content, options=h.question.options,
        correct_answer="A", user_answer="B",
    ))
    assert calls["input_signature"][0] == (h.wrong, h.question, prepared.knowledge_points)
    assert calls["input_signature"][0][2] is original_points
    assert calls["build_grounding"][1]["content"] is h.question.content
    assert calls["build_grounding"][1]["options"] is h.question.options
    assert calls["input_signature"][1]["visual_sources"] is prepared.visual_sources
    assert calls["model_signature"] == ((runtime,), {})
    assert calls["cached_response"][1] == dict(
        requires_visual=False, expected_input_signature="input", expected_model_signature="model",
    )
    assert calls["stale_reason"][0][0] is h.wrong.ai_analysis


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
async def test_preparation_failure_propagates_without_later_callbacks(stage, failure_type):
    failure = failure_type(stage)
    h, events = traced_request(fail_at=stage, failure=failure)
    with pytest.raises(failure_type) as caught:
        await module.prepare_analysis(h.request)
    assert caught.value is failure
    assert [name for name, *_ in events] == STAGES[: STAGES.index(stage) + 1]
    h.logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_visual_sources_short_circuit_slot_check_and_keep_reference():
    h, events = traced_request()
    sources = [object()]
    h.request.collect_visual_sources = lambda _question: sources
    prepared = await module.prepare_analysis(h.request)
    assert prepared.visual_sources is sources
    assert prepared.requires_visual is True
    assert "has_visual_slot" not in [name for name, *_ in events]


@pytest.mark.asyncio
async def test_runtime_callback_replaces_later_grounding_port_before_use():
    h, events = traced_request()
    grounding = object()
    original = h.request.load_runtime

    async def runtime(*args, **kwargs):
        h.request.build_grounding = lambda **_kwargs: grounding
        return await original(*args, **kwargs)

    h.request.load_runtime = runtime
    prepared = await module.prepare_analysis(h.request)
    assert prepared.answer_grounding is grounding
    assert "build_grounding" not in [name for name, *_ in events]


@pytest.mark.asyncio
@pytest.mark.parametrize("force", [False, True])
async def test_cache_response_and_force_truth_are_observed_after_cache_callback(force):
    h, _ = traced_request()
    cached = {}

    def cache(*_args, **_kwargs):
        h.request.force_regenerate = force
        return cached

    h.request.cached_response = cache
    prepared = await module.prepare_analysis(h.request)
    assert prepared.response is cached
    assert prepared.force is force


@pytest.mark.asyncio
async def test_falsey_revision_response_stops_before_visual_and_material_callbacks():
    h, events = traced_request()
    response = {}
    h.request.revision_guard = AsyncMock(return_value=response)
    prepared = await module.prepare_analysis(h.request)
    assert prepared.response is response
    assert events == []
    assert prepared.answer_grounding is None
    assert prepared.knowledge_points == []
    assert prepared.runtime is None


@pytest.mark.asyncio
async def test_actual_cancellation_during_material_loading_stops_preparation():
    h, events = traced_request()
    entered = asyncio.Event()

    async def runtime(_db):
        entered.set()
        await asyncio.Future()

    h.request.load_runtime = runtime
    task = asyncio.create_task(module.prepare_analysis(h.request))
    await assert_task_cancellation(task, entered)
    assert [name for name, *_ in events] == STAGES[:4]
    h.logger.info.assert_not_called()
