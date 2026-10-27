"""Service-entry assembly contract for smart practice orchestration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.practice.smart_entry import SmartEntryRequest, run_smart_entry


def request(**overrides):
    values = dict(
        db="db",
        user_id=8,
        subject_code="DS",
        count=3,
        exclude_answered=True,
        no_repeat_days=2,
        use_leitner=False,
        request_id="request",
        smart_strategy="path",
        skip_finalize=True,
        subject_ids=None,
        logger=SimpleNamespace(),
        resolve_subject_ids=AsyncMock(return_value=[7]),
        resolve_experiment=AsyncMock(
            return_value={
                "source": "experiment",
                "strategy": "scored",
                "experiment_id": 1,
                "variant_key": "v",
            }
        ),
        load_scored=AsyncMock(return_value=([SimpleNamespace(id=1)], {})),
        load_fallback=AsyncMock(return_value=([], {})),
        merge_results=lambda scored, metadata, _fallback, _fallback_meta: (
            scored,
            metadata,
        ),
        finalize=AsyncMock(
            side_effect=lambda _db, questions, metadata: (questions, metadata)
        ),
        build_conditions=lambda **_kwargs: [],
        load_path=AsyncMock(return_value=([], {})),
        run_weakness=AsyncMock(return_value=([], {})),
    )
    values.update(overrides)
    return SmartEntryRequest(**values)


@pytest.mark.asyncio
async def test_entry_resolves_scope_once_and_delegates_to_smart_orchestrator(
    monkeypatch,
):
    item = request(subject_ids=[9])
    captured = {}

    async def run_smart_practice(payload):
        captured["payload"] = payload
        return (["question"], {"meta": True})

    monkeypatch.setattr(
        "app.services.practice.smart_entry.run_smart_practice", run_smart_practice
    )
    result = await run_smart_entry(item)

    assert result == (["question"], {"meta": True})
    item.resolve_subject_ids.assert_not_awaited()
    payload = captured["payload"]
    assert payload.subject_ids == [9]
    assert payload.smart_strategy == "path"
    assert payload.run_scored is not None
    assert payload.run_path is not None
    assert payload.run_weakness is not item.load_fallback
    assert payload.run_weakness is not item.run_weakness


@pytest.mark.asyncio
async def test_entry_without_explicit_scope_resolves_service_subject_ids(monkeypatch):
    item = request()

    async def run_smart_practice(_payload):
        return [], {}

    monkeypatch.setattr(
        "app.services.practice.smart_entry.run_smart_practice", run_smart_practice
    )
    await run_smart_entry(item)
    item.resolve_subject_ids.assert_awaited_once_with("db", "DS")


@pytest.mark.asyncio
async def test_entry_assembles_exact_branch_request_and_providers(monkeypatch):
    item = request(subject_ids=[9])
    captured = {}

    class BranchRequest(SimpleNamespace):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured["branch"] = self

    class BranchProviders(SimpleNamespace):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured["providers"] = self

    async def run_smart_practice(payload):
        captured["payload"] = payload
        return [], {}

    monkeypatch.setattr(
        "app.services.practice.smart_entry.create_smart_branches",
        lambda request, providers: captured.setdefault(
            "callbacks", (object(), object(), object())
        ),
    )
    monkeypatch.setattr(
        "app.services.practice.smart_entry.SmartBranchRequest", BranchRequest
    )
    monkeypatch.setattr(
        "app.services.practice.smart_entry.SmartBranchProviders", BranchProviders
    )
    monkeypatch.setattr(
        "app.services.practice.smart_entry.run_smart_practice", run_smart_practice
    )
    await run_smart_entry(item)

    branch = captured["branch"]
    assert (branch.db, branch.user_id, branch.subject_code, branch.count) == (
        "db",
        8,
        "DS",
        3,
    )
    assert (branch.exclude_answered, branch.no_repeat_days, branch.use_leitner) == (
        True,
        2,
        False,
    )
    assert (branch.request_id, branch.skip_finalize) == ("request", True)
    assert branch.load_path is item.load_path
    assert branch.load_fallback is item.load_fallback
    assert branch.merge_results is item.merge_results
    assert branch.finalize is item.finalize
    assert branch.build_conditions is item.build_conditions

    provider = captured["providers"]
    assert provider.load_scored is item.load_scored
    assert provider.load_fallback is item.load_fallback
    assert provider.merge_results is item.merge_results
    assert provider.finalize_scored is item.finalize
    assert provider.finalize_path is item.finalize
    assert provider.build_path_conditions is item.build_conditions
    assert provider.load_path is item.load_path
    assert provider.run_weakness is item.run_weakness

    payload = captured["payload"]
    callbacks = captured["callbacks"]
    assert (payload.db, payload.user_id, payload.subject_code, payload.count) == (
        "db",
        8,
        "DS",
        3,
    )
    assert (payload.exclude_answered, payload.no_repeat_days, payload.use_leitner) == (
        True,
        2,
        False,
    )
    assert payload.smart_strategy == "path"
    assert payload.subject_ids == [9]
    assert payload.logger is item.logger
    assert payload.resolve_experiment is item.resolve_experiment
    assert payload.resolve_scope_ids is item.resolve_subject_ids
    assert (payload.run_scored, payload.run_path, payload.run_weakness) == callbacks
