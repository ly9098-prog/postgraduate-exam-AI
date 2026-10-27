"""Selection precedence, precise dispatch fields, reads, and cancellation."""

import asyncio

import pytest

from app.services.ai import analysis_result_review as module
from tests.test_services.analysis_orchestration_support import assert_task_cancellation
from tests.test_services.analysis_result_review_support import (
    ReadProbe,
    expected_outcome,
    outcome_harness,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ack", "repair", "valid"])
@pytest.mark.parametrize("response", [None, {}, {"model": "selected"}])
async def test_only_selected_callback_receives_exact_original_arguments(monkeypatch, kind, response):
    h = outcome_harness(monkeypatch, kind=kind)
    h.response = response
    args, kwargs = expected_outcome(h, kind)
    originals = {key: value for key, value in h.kwargs.items() if isinstance(value, (list, dict))}
    contents = {key: value.copy() for key, value in originals.items()}
    assert await module.resolve_analysis_outcome(h.db, h.review, **h.kwargs) is response
    assert h.events == [(kind, args, kwargs)]
    for key, value in kwargs.items():
        assert h.events[0][2][key] is value
    for key, value in originals.items():
        assert h.kwargs[key] is value and value == contents[key]


@pytest.mark.asyncio
async def test_falsey_ack_failure_precedes_invalid_parse_and_grounding(monkeypatch):
    h = outcome_harness(monkeypatch, kind="ack")

    class Failure:
        def __bool__(self):
            pytest.fail("ack presence must use is not None")

    h.review.ack_failure = failure = Failure()
    h.review.parsed_valid = False
    h.review.grounding.valid = False
    assert await module.resolve_analysis_outcome(h.db, h.review, **h.kwargs) is h.response
    assert [name for name, *_ in h.events] == ["ack"]
    assert h.events[0][2]["failure"] is failure


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {}, {"model": "parse"}])
async def test_parse_failure_constructs_response_before_log(monkeypatch, response):
    h = outcome_harness(monkeypatch, kind="parse")
    h.response = response
    images = h.kwargs["image_data_urls"]
    force, logger = h.kwargs["effective_force"], h.kwargs["logger"]
    assert await module.resolve_analysis_outcome(h.db, h.review, **h.kwargs) is response
    assert h.events == [
        ("parse", (images,), {"effective_force": force}),
        ("log", ("ai.error_analysis.empty wq_id=%s force=%s model=parse_failed", 7, force), {}),
    ]
    assert h.kwargs["logger"] is logger


READS = {
    "ack": [
        "review.ack_failure", "question.id", "review.usage", "review.usage",
        "usage.visual_ack_retried", "review.ack_failure",
    ],
    "parse": ["review.ack_failure", "review.parsed_valid", "question.id"],
    "repair": [
        "review.ack_failure", "review.parsed_valid", "review.grounding", "grounding.valid",
        "review.grounding", "review.usage",
    ],
    "valid": [
        "review.ack_failure", "review.parsed_valid", "review.grounding", "grounding.valid",
        "review.parsed", "review.grounding", "review.usage",
    ],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", READS)
async def test_branch_attribute_order_avoids_unselected_properties(monkeypatch, kind):
    h = outcome_harness(monkeypatch, kind=kind)
    reads = []
    h.review.usage = ReadProbe(h.review.usage, reads, "usage")
    h.review.grounding = ReadProbe(h.review.grounding, reads, "grounding")
    h.review = ReadProbe(h.review, reads, "review")
    h.kwargs["wrong_question"] = ReadProbe(h.kwargs["wrong_question"], reads, "question")
    assert await module.resolve_analysis_outcome(h.db, h.review, **h.kwargs) is h.response
    assert reads == READS[kind]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,stage", [
    ("ack", "ack"), ("parse", "parse"), ("parse", "log"),
    ("repair", "repair"), ("valid", "valid"),
])
@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
async def test_selected_failure_and_cancellation_propagate(monkeypatch, kind, stage, failure_type):
    failure = failure_type(stage)
    h = outcome_harness(monkeypatch, kind=kind, fail_at=stage, failure=failure)
    with pytest.raises(failure_type) as caught:
        await module.resolve_analysis_outcome(h.db, h.review, **h.kwargs)
    assert caught.value is failure
    assert [name for name, *_ in h.events] == (["parse", "log"] if stage == "log" else [stage])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
async def test_actual_cancellation_during_selected_outcome(monkeypatch, kind):
    h = outcome_harness(monkeypatch, kind=kind)
    entered = asyncio.Event()

    async def selected(*_args, **_kwargs):
        entered.set()
        await asyncio.Future()

    h.kwargs["grounding_repair" if kind == "repair" else "valid_outcome"] = selected
    task = asyncio.create_task(module.resolve_analysis_outcome(h.db, h.review, **h.kwargs))
    await assert_task_cancellation(task, entered)
    assert h.events == []
