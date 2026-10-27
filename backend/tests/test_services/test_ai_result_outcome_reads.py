"""Every selected attribute read retains its failure and cancellation boundary."""

import asyncio

import pytest

from app.services.ai import analysis_result_review as module
from tests.test_services.analysis_result_review_support import (
    ReadProbe,
    outcome_harness,
)
from tests.test_services.test_ai_result_outcome_contract import READS

CASES = [(kind, index) for kind, reads in READS.items() for index in range(len(reads))]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,index", CASES)
@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
async def test_each_attribute_read_failure_stops_at_original_point(
    monkeypatch, kind, index, failure_type
):
    h = outcome_harness(monkeypatch, kind=kind)
    reads = []
    failure = failure_type("attribute read")

    class Probe(ReadProbe):
        def __getattr__(self, name):
            value = super().__getattr__(name)
            if len(reads) == index + 1:
                raise failure
            return value

    h.review.usage = Probe(h.review.usage, reads, "usage")
    h.review.grounding = Probe(h.review.grounding, reads, "grounding")
    h.review = Probe(h.review, reads, "review")
    h.kwargs["wrong_question"] = Probe(h.kwargs["wrong_question"], reads, "question")
    with pytest.raises(failure_type) as caught:
        await module.resolve_analysis_outcome(h.db, h.review, **h.kwargs)
    assert caught.value is failure
    assert reads == READS[kind][: index + 1]
    assert [name for name, *_ in h.events] == (
        ["parse"] if kind == "parse" and READS[kind][index] == "question.id" else []
    )
