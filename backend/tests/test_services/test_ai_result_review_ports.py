"""Live module binding and caller mutation at original expression boundaries."""

from types import SimpleNamespace

import pytest

from app.services.ai import analysis_result_review as module
from tests.test_services.analysis_result_review_support import (
    outcome_harness,
    review_harness,
)


def forbidden(*_args, **_kwargs):
    pytest.fail("port was rebound before its original expression boundary")


@pytest.mark.asyncio
async def test_review_constructor_is_bound_before_ack_callback(monkeypatch):
    h = review_harness(monkeypatch)

    def ack(**_kwargs):
        monkeypatch.setattr(module, "ReviewedAnalysis", forbidden)
        return h.ack

    monkeypatch.setattr(module, "detect_visual_ack_failure", ack)
    reviewed = await module.review_analysis_result(h.invocation, **h.kwargs)
    assert reviewed.ack_failure is h.ack
    assert h.constructed[0]["ack_failure"] is h.ack


@pytest.mark.asyncio
async def test_ack_port_is_bound_before_reading_mutable_visual_evidence(monkeypatch):
    h = review_harness(monkeypatch)

    class Usage:
        @property
        def visual_evidence(self):
            monkeypatch.setattr(module, "detect_visual_ack_failure", forbidden)
            return "late-evidence"

    usage = Usage()
    h.kwargs["build_usage"] = lambda **_kwargs: usage
    reviewed = await module.review_analysis_result(h.invocation, **h.kwargs)
    assert reviewed.usage is usage
    assert reviewed.ack_failure is h.ack
    assert next(kwargs for name, _, kwargs in h.events if name == "ack")["visual_evidence"] == (
        "late-evidence"
    )


@pytest.mark.asyncio
async def test_visual_request_and_reconcile_bind_before_runtime_property(monkeypatch):
    h = review_harness(monkeypatch)
    runtime = object()

    class Invocation:
        result = h.result

        @property
        def runtime(self):
            monkeypatch.setattr(module, "VisualValidationRequest", forbidden)
            monkeypatch.setattr(module, "reconcile_visual_evidence", forbidden)
            return runtime

    reviewed = await module.review_analysis_result(Invocation(), **h.kwargs)
    assert h.requests[0]["runtime"] is runtime
    assert reviewed.grounding is h.grounding
    assert "reconcile" in [name for name, *_ in h.events]


@pytest.mark.asyncio
async def test_parse_mutations_are_visible_but_raw_content_is_not_reread(monkeypatch):
    h = review_harness(monkeypatch)
    runtime = object()

    def parse(raw):
        assert raw is h.raw
        h.result["content"] = "new-content"
        h.invocation.runtime = runtime
        return h.parsed

    def build_usage(**kwargs):
        assert kwargs["raw_content"] is h.raw
        assert kwargs["result"] is h.result
        assert kwargs["result"]["content"] == "new-content"
        return h.usage

    h.kwargs.update(parse_content=parse, build_usage=build_usage)
    reviewed = await module.review_analysis_result(h.invocation, **h.kwargs)
    assert reviewed.parsed is h.parsed
    assert h.requests[0]["result"] is h.result
    assert h.requests[0]["runtime"] is runtime


@pytest.mark.asyncio
async def test_parse_response_precedes_logger_lookup_and_response_rebinding(monkeypatch):
    h = outcome_harness(monkeypatch, kind="parse")
    logger = h.kwargs["logger"]
    events = []

    def log(*args):
        events.append(("log", args))
        monkeypatch.setattr(module, "parse_failed_response", forbidden)

    def response(*_args, **_kwargs):
        events.append(("response",))
        logger.info = log
        h.kwargs["wrong_question"].id = 9
        return h.response

    monkeypatch.setattr(module, "parse_failed_response", response)
    assert await module.resolve_analysis_outcome(h.db, h.review, **h.kwargs) is h.response
    assert events == [
        ("response",),
        ("log", ("ai.error_analysis.empty wq_id=%s force=%s model=parse_failed",
                 9, h.kwargs["effective_force"])),
    ]


@pytest.mark.asyncio
async def test_logger_method_binds_before_question_id_property(monkeypatch):
    h = outcome_harness(monkeypatch, kind="parse")

    class Question:
        @property
        def id(self):
            h.kwargs["logger"].info = forbidden
            return 11

    h.kwargs["wrong_question"] = Question()
    assert await module.resolve_analysis_outcome(h.db, h.review, **h.kwargs) is h.response
    assert h.events[-1][0] == "log"
    assert h.events[-1][1][1] == 11


@pytest.mark.asyncio
async def test_ack_retry_property_changes_later_failure_read(monkeypatch):
    h = outcome_harness(monkeypatch, kind="ack")
    retried = object()

    class Usage:
        @property
        def visual_ack_retried(self):
            h.review.ack_failure = None
            return retried

    usage = Usage()
    h.review.usage = usage
    assert await module.resolve_analysis_outcome(h.db, h.review, **h.kwargs) is h.response
    assert h.events[0][2]["usage"] is usage
    assert h.events[0][2]["visual_ack_retried"] is retried
    assert h.events[0][2]["failure"] is None


@pytest.mark.asyncio
async def test_grounding_branch_check_is_not_reused_as_callback_argument(monkeypatch):
    h = outcome_harness(monkeypatch, kind="repair")
    replacement = object()

    class Review:
        ack_failure, parsed_valid, usage = None, True, h.review.usage
        reads = 0

        @property
        def grounding(self):
            self.reads += 1
            return SimpleNamespace(valid=False) if self.reads == 1 else replacement

    review = Review()
    assert await module.resolve_analysis_outcome(h.db, review, **h.kwargs) is h.response
    assert review.reads == 2
    assert h.events[0][0] == "repair"
    assert h.events[0][2]["grounding"] is replacement


@pytest.mark.asyncio
async def test_valid_parsed_getter_updates_later_grounding_and_usage(monkeypatch):
    h = outcome_harness(monkeypatch)
    grounding, usage = object(), object()

    class Review:
        ack_failure, parsed_valid = None, True
        grounding, usage = h.review.grounding, h.review.usage

        @property
        def parsed(self):
            self.grounding, self.usage = grounding, usage
            return h.review.parsed

    assert await module.resolve_analysis_outcome(h.db, Review(), **h.kwargs) is h.response
    assert h.events[0][2]["grounding"] is grounding
    assert h.events[0][2]["usage"] is usage
