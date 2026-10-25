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
