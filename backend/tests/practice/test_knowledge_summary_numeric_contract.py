"""Original facade lookup and numeric exception boundaries."""

import pytest

from app.services.practice import knowledge_session_summary as svc
from tests.practice.knowledge_summary_support import (
    Database,
    legacy,
    read,
    record,
    root_port,
    session,
    state,
)


def test_delta_keeps_both_number_lookups_even_when_first_is_none(monkeypatch):
    calls = []

    def number(value, *, digits):
        calls.append((value, digits))
        return None if value == "before" else 2.0

    monkeypatch.setattr(svc, "_number_or_none", number)
    assert svc._delta("before", "after") is None
    assert calls == [("before", 4), ("after", 4)]


def test_delta_second_lookup_observes_replacement_during_first_call(monkeypatch):
    calls = []

    def second(value, *, digits):
        calls.append(("second", value, digits))
        return 3.0

    def first(value, *, digits):
        calls.append(("first", value, digits))
        monkeypatch.setattr(svc, "_number_or_none", second)
        return 1.0

    monkeypatch.setattr(svc, "_number_or_none", first)
    assert svc._delta(10, 20) == 2.0
    assert calls == [("first", 10, 4), ("second", 20, 4)]


def test_delta_propagates_original_second_conversion_failure(monkeypatch):
    error = RuntimeError("second number")
    calls = []

    def number(value, *, digits):
        calls.append(value)
        if value == "after":
            raise error
        return 1.0

    monkeypatch.setattr(svc, "_number_or_none", number)
    with pytest.raises(RuntimeError) as caught:
        svc._delta("before", "after")
    assert caught.value is error
    assert calls == ["before", "after"]


def test_compact_and_status_do_not_gain_dependencies_on_number_or_delta(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("new numeric dependency")

    monkeypatch.setattr(svc, "_number_or_none", unexpected)
    monkeypatch.setattr(svc, "_delta", unexpected)
    current = state(12, 72.456, 0.87654)
    assert svc._compact_point_baseline(current, 12) == [12, 72.46, 0.8765, 3]
    assert svc._state_status(current) == "developing"


def test_persisted_payload_still_looks_up_public_projection_on_original_facade(
    monkeypatch,
):
    seen = []
    monkeypatch.setattr(
        svc,
        "public_knowledge_session",
        lambda context: seen.append(context) or {"custom": True},
    )
    context = {"v": 8, "baseline": {"points": []}}
    assert svc.persisted_knowledge_session(context) == {
        "custom": True,
        "_baseline": {"points": []},
        "_context_version": 8,
    }
    assert seen == [context]


@pytest.mark.asyncio
async def test_point_projection_keeps_number_delta_status_lookup_order(monkeypatch):
    db = Database(
        session=session(legacy([[12, 5, 0.1, 1]]), results=[{"record_id": 1}]),
        scalars=[[record(1)], [state(12)]],
        execute=[[(101, 12, "point")]],
    )
    root_port(monkeypatch, db)
    calls = []

    def number(value, **kwargs):
        calls.append("number")
        monkeypatch.setattr(svc, "_delta", lambda *args: calls.append("delta") or -7)
        monkeypatch.setattr(
            svc, "_state_status", lambda *args: calls.append("status") or "patched"
        )
        return 123.0

    monkeypatch.setattr(svc, "_number_or_none", number)
    point = (await read(db))["points"][0]
    assert point["mastery_before"] == 123
    assert point["mastery_delta"] == -7 and point["status_after"] == "patched"
    assert calls == ["number", "delta", "status"]
