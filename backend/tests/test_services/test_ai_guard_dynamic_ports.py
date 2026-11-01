"""Failure guards retain reads across await and branch callback boundaries."""

import asyncio
from types import SimpleNamespace

import pytest

from app.services.ai import provider_exception, revision_guard
from tests.test_services.ai_revision_guard_support import execute, make_harness, observe


@pytest.mark.asyncio
async def test_historical_inputs_are_read_after_query_but_current_inputs_before_it(
    monkeypatch,
):
    h = make_harness(monkeypatch)

    def mutate(_):
        h.wrong.wrong_answer = "C"
        h.question.question_type = "updated"
        h.revision.question_type = ""
        h.revision.content = "updated history"
        h.question.current_version_id = 91
        h.wrong.question_version_id = 92

    h.hooks["scalar"] = mutate
    await execute(h)
    assert h.records["current"][0]["user_answer"] == "A"
    assert h.records["historical"][0]["user_answer"] == "C"
    assert h.records["historical"][0]["question_type"] == "updated"
    assert h.records["historical"][0]["content"] == "updated history"
    assert h.records["warning"][0][3:5] == (7, 17)
    assert h.records["scalar"][0].compile().params == {"id_1": 7, "question_id_1": 11}


@pytest.mark.asyncio
async def test_signature_callbacks_are_resolved_separately_in_comparison_order(
    monkeypatch,
):
    h = make_harness(monkeypatch)

    def historical(value):
        observe(h, "new_signature", value)
        return "same"

    def current(value):
        observe(h, "old_signature", value)
        monkeypatch.setattr(revision_guard, "grounding_fact_signature", historical)
        return "same"

    monkeypatch.setattr(revision_guard, "grounding_fact_signature", current)
    assert await execute(h) is None
    assert h.records["old_signature"][0] is h.current
    assert h.records["new_signature"][0] is h.historical
    assert "warning" not in h.events


@pytest.mark.asyncio
async def test_historical_grounding_uses_builder_replaced_during_query(monkeypatch):
    h = make_harness(monkeypatch)

    def historical(**kwargs):
        observe(h, "new_historical", kwargs)
        return h.historical

    h.hooks["scalar"] = lambda _: monkeypatch.setattr(
        revision_guard, "build_answer_grounding", historical
    )
    await execute(h)
    assert "current" in h.events and "historical" not in h.events
    assert h.records["new_historical"][0]["correct_answer"] == "A"
    assert (
        h.records["signature"][0] is h.current
        and h.records["signature"][1] is h.historical
    )


@pytest.mark.asyncio
async def test_warning_can_replace_response_and_clock_before_their_evaluation(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    content = object()

    def mutate(_):
        monkeypatch.setattr(
            revision_guard, "build_revision_drift_analysis", lambda: content
        )
        monkeypatch.setattr(
            revision_guard,
            "datetime",
            SimpleNamespace(
                now=lambda zone: SimpleNamespace(isoformat=lambda: "after-warning")
            ),
        )

    h.hooks["warning"] = mutate
    output = await execute(h)
    assert output["content"] is content and output["generated_at"] == "after-warning"
    assert "response" not in h.events and "now" not in h.events


@pytest.mark.asyncio
async def test_falsey_revision_is_still_present_for_identity_guard(monkeypatch):
    h = make_harness(monkeypatch)

    class Revision(SimpleNamespace):
        def __bool__(self):
            pytest.fail("revision presence must use identity with None")

    h.revision = Revision(**vars(h.revision))
    await execute(h)
    assert "historical" in h.events and h.records["warning"][0][-1] is True


@pytest.mark.parametrize("point", ["error_kind", "retryable", "status_code"])
@pytest.mark.parametrize("kind", [RuntimeError, asyncio.CancelledError])
def test_metadata_reads_can_fail_even_when_auth_kind_would_short_circuit(point, kind):
    error = kind(point)

    class Error(Exception):
        error_kind = "auth"
        retryable = False
        status_code = 401

        def __getattribute__(self, name):
            if name == point:
                raise error
            return super().__getattribute__(name)

    with pytest.raises(kind) as caught:
        provider_exception.classify_ai_provider_exception(
            Error("unauthorized"), visual=False
        )
    assert caught.value is error


@pytest.mark.parametrize(
    "signals,expected",
    [
        ([True], "ai_provider_quota_exceeded"),
        ([False, True], "ai_provider_auth_failed"),
        ([False, False, True], "ai_provider_rate_limited"),
        ([False, False, False, True], "ai_provider_transient"),
        ([False, False, False, False], "ai_provider_error"),
    ],
)
def test_text_predicate_results_have_one_truth_test_per_evaluated_branch(
    monkeypatch, signals, expected
):
    events = []
    values = iter(signals)

    class Truth:
        def __init__(self, value):
            self.value = value

        def __bool__(self):
            events.append(self.value)
            return self.value

    monkeypatch.setattr(
        provider_exception, "_contains_any", lambda *_: Truth(next(values))
    )
    output = provider_exception.classify_ai_provider_exception(
        Exception("unknown"), visual=False
    )
    assert output[0] == expected and events == signals


@pytest.mark.parametrize(
    "kind,comparisons",
    [
        ("quota", ["quota"]),
        ("auth", ["quota", "auth"]),
        ("rate_limit", ["quota", "auth", "rate_limit"]),
        ("transient", ["quota", "auth", "rate_limit", "transient"]),
    ],
)
def test_typed_kind_comparison_truth_is_evaluated_once(kind, comparisons):
    events = []

    class Once:
        def __init__(self, token, value):
            self.token, self.value, self.used = token, value, False

        def __bool__(self):
            assert not self.used, (
                "classification must not repeat a comparison truth test"
            )
            self.used = True
            events.append(self.token)
            return self.value

    class Kind(str):
        def __eq__(self, other):
            return Once(other, str.__eq__(self, other))

    class KindSource:
        def __str__(self):
            return Kind(kind)

    exc = Exception("unknown")
    exc.error_kind = KindSource()
    output = provider_exception.classify_ai_provider_exception(exc, visual=False)
    assert (
        output[0]
        == {
            "quota": "ai_provider_quota_exceeded",
            "auth": "ai_provider_auth_failed",
            "rate_limit": "ai_provider_rate_limited",
            "transient": "ai_provider_transient",
        }[kind]
    )
    assert events == comparisons


@pytest.mark.asyncio
async def test_response_builder_can_replace_clock_before_its_lookup(monkeypatch):
    h = make_harness(monkeypatch)
    zone_ref = revision_guard.UTC

    def now(zone):
        observe(h, "after_builder_now", zone)
        return SimpleNamespace(isoformat=lambda: "after-builder")

    def replace(_):
        monkeypatch.setattr(revision_guard, "datetime", SimpleNamespace(now=now))

    h.hooks["response"] = replace
    output = await execute(h)
    assert output["generated_at"] == "after-builder" and output["content"] is h.content
    assert h.records["after_builder_now"] == [zone_ref]
    assert h.events[-2:] == ["response", "after_builder_now"]
    assert "now" not in h.events and "isoformat" not in h.events
