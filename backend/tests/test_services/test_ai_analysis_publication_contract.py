"""Publication follows successful persistence without owning transactions or retry."""

import asyncio
import inspect

import pytest

from app.services.ai import analysis_outcomes as outcomes
from tests.test_services.analysis_publication_support import (
    assert_persisted_arguments,
    execute,
    harness,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
async def test_publication_reads_objects_mutated_during_persistence(monkeypatch, kind):
    h = harness(monkeypatch)
    original = h.persist

    async def persist(*args, **kwargs):
        returned = await original(*args, **kwargs)
        h.result.update(model="changed-model", compatibility_profile="changed-profile")
        h.usage.total_tokens_used, h.usage.total_duration_ms = 23, 31
        h.usage.visual_evidence = "changed-evidence"
        h.parsed["knowledge_patch"] = {"new": []}
        h.images.append("second")
        h.grounding.guard_reason = "changed-reason"
        return returned

    h.persist = persist
    response = await execute(h, kind)
    assert h.events == ["persist", "log", "response"]
    args, values = h.responses[0]
    assert response["published"] is h.responses[0]
    assert values["tokens_used"] == 23 and values["duration_ms"] == 31
    assert values["visual_evidence"] == "changed-evidence"
    assert values["effective_force"] is True
    if kind == "repair":
        assert_persisted_arguments(h, kind)
        assert args == () and values["content"] is h.safe
        assert values["generated_at"] is h.stamp and values["visual_input_count"] == 2
        assert h.logs[0][1:] == (
            7,
            True,
            "changed-model",
            "changed-reason",
            ["B"],
            ["A"],
        )
    else:
        assert_persisted_arguments(h, kind)
        assert args[0] is h.parsed and args[1] is h.result
        assert values["image_data_urls"] is h.images
        assert h.logs[0][3] == "changed-model" and h.logs[0][8] == "changed-profile"
        assert h.logs[0][-2] == {
            "mistake_diagnosis": True,
            "knowledge_patch": True,
            "review_task": False,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
@pytest.mark.parametrize("point", ["persist", "log", "response"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_publication_failure_does_not_retry_or_reorder_effects(
    monkeypatch, kind, point, error_type
):
    h = harness(monkeypatch)
    error = error_type(point)

    def fail(*args, **kwargs):
        h.events.append(point)
        raise error

    async def fail_async(*args, **kwargs):
        fail()

    if point == "persist":
        h.persist = fail_async
    elif point == "log":
        h.logger.info = h.logger.warning = fail
    else:
        monkeypatch.setattr(outcomes, "grounding_repaired_response", fail)
        monkeypatch.setattr(outcomes, "valid_analysis_response", fail)
    with pytest.raises(error_type) as caught:
        await execute(h, kind)
    assert caught.value is error
    assert (
        h.events
        == ["persist", "log", "response"][
            : ["persist", "log", "response"].index(point) + 1
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
async def test_actual_task_cancellation_during_persistence_never_publishes(
    monkeypatch, kind
):
    h = harness(monkeypatch)
    entered = asyncio.Event()

    async def persist(*args, **kwargs):
        h.events.append("persist")
        entered.set()
        await asyncio.Event().wait()

    h.persist = persist
    task = asyncio.create_task(execute(h, kind))
    await entered.wait()
    task.cancel("cancel persistence")
    with pytest.raises(asyncio.CancelledError, match="cancel persistence"):
        await task
    assert h.events == ["persist"] and not h.logs and not h.responses


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
async def test_definition_time_default_persist_is_invoked(monkeypatch, kind):
    h = harness(monkeypatch)
    from app.services.ai import analysis_persistence

    class Session:
        async def commit(self):
            h.events.append("commit")

        def add(self, value):
            h.events.append("add")

    async def append(*args, **kwargs):
        h.events.append("append")
        await Session().commit()

    monkeypatch.setattr(analysis_persistence, "_append_analysis_chat", append)
    h.runtime = type("Runtime", (), {"provider": "test", "model_config_id": 1})()
    await execute(h, kind, default_persist=True, db=Session())
    assert h.events == ["commit", "append", "commit", "log", "response"]


@pytest.mark.parametrize(
    "kind,name",
    [("repair", "persist_repaired_analysis"), ("valid", "persist_valid_analysis")],
)
def test_default_persist_remains_definition_time_bound(monkeypatch, kind, name):
    fn = (
        outcomes.grounding_repair_outcome
        if kind == "repair"
        else outcomes.valid_analysis_outcome
    )
    original = inspect.signature(fn).parameters["persist"].default
    assert original is getattr(outcomes, name)
    replacement = object()
    monkeypatch.setattr(outcomes, name, replacement)
    assert inspect.signature(fn).parameters["persist"].default is original


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
async def test_logger_can_replace_response_builder_before_current_response(
    monkeypatch, kind
):
    h = harness(monkeypatch)
    published = {}

    def response(*args, **kwargs):
        assert h.events == ["persist", "log"]
        published.update(args=args, values=kwargs)
        return published

    def log(*args):
        h.events.append("log")
        monkeypatch.setattr(outcomes, "grounding_repaired_response", response)
        monkeypatch.setattr(outcomes, "valid_analysis_response", response)
        h.usage.total_tokens_used = 99

    h.logger.info = h.logger.warning = log
    assert await execute(h, kind) is published
    assert published["values"]["tokens_used"] == 99
    assert (
        published["values"]["content"] is h.safe
        if kind == "repair"
        else published["args"][0] is h.parsed
    )
