"""Pin live publication observation ports and argument evaluation ordering."""

import asyncio

import pytest

from app.services.ai import analysis_outcomes as outcomes
from tests.test_services.analysis_publication_support import execute, harness


@pytest.mark.asyncio
@pytest.mark.parametrize("vision", [False, True])
async def test_visual_validator_is_lazy_and_current_log_method_is_already_bound(
    monkeypatch, vision
):
    h = harness(monkeypatch)
    if not vision:
        h.images.clear()
    calls = []

    def replacement(*args):
        raise AssertionError("must retain already-bound log method")

    def validate(value):
        assert h.events == ["persist"] and value == "evidence"
        calls.append(value)
        h.logger.info = replacement
        h.parsed["review_task"] = "validator-mutated"
        h.usage.total_duration_ms = 93
        return "validator-result"

    h.validator = validate
    await execute(h, "valid")
    assert calls == (["evidence"] if vision else [])
    assert h.events == ["persist", "log", "response"]
    assert h.logs[0][6] == ("validator-result" if vision else None)
    assert h.logs[0][-2]["review_task"] is vision
    assert h.logs[0][-1] == (93 if vision else 17)
    assert h.responses[0][1]["duration_ms"] == (93 if vision else 17)


@pytest.mark.asyncio
async def test_validator_can_replace_response_builder_before_log_completes(monkeypatch):
    h = harness(monkeypatch)
    published = {"replacement": True}

    def validate(value):
        monkeypatch.setattr(
            outcomes, "valid_analysis_response", lambda *a, **k: published
        )
        return True

    h.validator = validate
    assert await execute(h, "valid") is published
    assert h.events == ["persist", "log"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_validator_error_follows_persistence_but_prevents_log_and_response(
    monkeypatch, error_type
):
    h = harness(monkeypatch)
    error = error_type("validator")

    def validate(value):
        raise error

    h.validator = validate
    with pytest.raises(error_type) as caught:
        await execute(h, "valid")
    assert caught.value is error and h.events == ["persist"]


@pytest.mark.asyncio
async def test_result_getter_keeps_log_and_response_read_order(monkeypatch):
    h = harness(monkeypatch)
    observed = []

    class Result(dict):
        def get(self, key, *args):
            observed.append(key)
            return super().get(key, *args)

    h.result = Result(h.result)
    await execute(h, "valid")
    assert observed == ["model", "compatibility_profile"]
    assert h.responses[0][0][1] is h.result


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["len", "bool", "valid_analysis_response"])
async def test_original_global_overrides_are_read_at_publication_time(
    monkeypatch, name
):
    h = harness(monkeypatch)
    observed = []

    def replacement(*args, **kwargs):
        observed.append((args, kwargs))
        if name == "len":
            return 41
        if name == "bool":
            return "truth-port"
        return {"replacement": True}

    monkeypatch.setattr(outcomes, name, replacement, raising=False)
    output = await execute(h, "valid")
    assert observed
    if name == "len":
        assert h.persisted[0][1]["image_count"] == 41 and h.logs[0][5] == 41
    elif name == "bool":
        assert len(observed) == 3
        assert set(h.logs[0][-2].values()) == {"truth-port"}
    else:
        assert output == {"replacement": True}
