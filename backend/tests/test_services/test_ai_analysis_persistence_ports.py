"""Projection lookup timing and errors remain owned by the original module."""

import asyncio
from datetime import UTC
from types import SimpleNamespace

import pytest

from app.services.ai import analysis_persistence as persistence
from tests.test_services.analysis_persistence_support import execute, harness


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
async def test_timestamp_order_and_original_clock_timezone_are_preserved(
    monkeypatch, kind
):
    h = harness(monkeypatch)
    events = []

    class ModelResult(dict):
        def get(self, key, default=None):
            events.append(key)
            return super().get(key, default)

    def now(timezone):
        assert timezone is UTC
        events.append("clock")
        return SimpleNamespace(isoformat=lambda: "synthetic-time")

    h.args["result"] = ModelResult(h.args["result"])
    monkeypatch.setattr(persistence, "datetime", SimpleNamespace(now=now))
    output = await execute(h, kind)
    assert events == (
        ["clock", "model", "content", "model"]
        if kind == "repair"
        else ["model", "clock", "content", "model"]
    )
    assert (output[1] if kind == "repair" else output) == "synthetic-time"


@pytest.mark.asyncio
async def test_merge_callback_can_replace_metadata_port_before_current_projection(
    monkeypatch,
):
    h = harness(monkeypatch)
    metadata, observed = {"generated_at": "callback-time"}, []

    def meta(**kwargs):
        observed.append(kwargs)
        return metadata

    def merge(*args):
        monkeypatch.setattr(persistence, "_base_meta", meta)
        return "callback-diagnosis"

    monkeypatch.setattr(persistence, "merge_grounded_diagnosis", merge)
    await execute(h, "valid")
    assert h.parsed["_meta"] is metadata
    assert metadata["grounding_guard"] == "passed"
    assert h.parsed["mistake_diagnosis"] == "callback-diagnosis"
    assert len(observed) == 1
    assert observed[0]["expected_answer_check"] is h.args["expected_answer_check"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_snapshot_failure_propagates_after_only_first_commit(
    monkeypatch, kind, error_type
):
    error = error_type("snapshot")
    h = harness(monkeypatch)

    def project(*args, **kwargs):
        assert h.db.commits == 1
        raise error

    monkeypatch.setattr(persistence, "build_context_snapshot", project)
    with pytest.raises(error_type) as caught:
        await execute(h, kind)
    assert caught.value is error
    assert [row[0] for row in h.db.trace] == ["commit"]
    assert h.wrong.ai_analysis is (h.safe if kind == "repair" else h.parsed)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["_base_meta", "datetime", "merge_grounded_diagnosis"])
async def test_missing_original_projection_global_keeps_name_error(monkeypatch, name):
    h = harness(monkeypatch)
    monkeypatch.delattr(persistence, name)
    with pytest.raises(NameError) as caught:
        await execute(h, "valid")
    assert caught.value.name == name
    assert str(caught.value) == f"name '{name}' is not defined"
    assert h.wrong.ai_analysis is None and h.db.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
async def test_snapshot_callback_can_replace_chat_class_before_current_insert(
    monkeypatch, kind
):
    h = harness(monkeypatch)
    snapshot = {"custom": []}
    actual = []

    def chat(**kwargs):
        actual.append(kwargs)
        return SimpleNamespace(**kwargs)

    def project(context, **kwargs):
        assert context is h.args["context"] and h.db.commits == 1
        monkeypatch.setattr(persistence, "AiChat", chat)
        return snapshot

    monkeypatch.setattr(persistence, "build_context_snapshot", project)
    await execute(h, kind)
    assert h.db.commits == 2 and len(actual) == 1
    assert actual[0]["context_snapshot"] is snapshot
    assert actual[0]["ai_response"] == "provider-content"


def test_context_snapshot_only_shallow_copies_without_silent_input_filtering():
    context = {"image_data_urls": ["synthetic-value"], "visual_input_count": 99}
    snapshot = persistence.build_context_snapshot(
        context,
        image_count=2,
        visual_evidence="",
        visual_ack_retried=False,
        visual_ack_retry_ms=0,
    )
    assert snapshot is not context
    assert snapshot["image_data_urls"] is context["image_data_urls"]
    assert snapshot["visual_input_count"] == 2 and context["visual_input_count"] == 99
    assert snapshot["visual_evidence"] is None
