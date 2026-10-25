"""Branch adapter contracts for smart-practice orchestration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.practice.smart_branches import (
    SmartBranchProviders,
    SmartBranchRequest,
    create_smart_branches,
)


def providers(**overrides):
    async def load_scored(**_kwargs):
        return [SimpleNamespace(id=1)], {}

    async def load_path(**_kwargs):
        return {
            "recommended_question_ids": [1],
            "nodes": [
                {
                    "name": "node",
                    "reason": "reason",
                    "priority": 2,
                    "recommended_question_ids": [1],
                }
            ],
        }

    def merge_results(scored, _metadata, _fallback, _fallback_metadata, **_kwargs):
        return scored, {}

    fields = {
        "load_scored": AsyncMock(side_effect=load_scored),
        "load_fallback": AsyncMock(return_value=([], {})),
        "merge_results": merge_results,
        "finalize_scored": AsyncMock(return_value=([], {})),
        "finalize_path": AsyncMock(return_value=([], {})),
        "build_path_conditions": lambda **_kwargs: [],
        "load_path": AsyncMock(side_effect=load_path),
        "run_weakness": AsyncMock(return_value=([], {})),
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def request():
    defaults = providers()
    return SmartBranchRequest(
        db="db",
        user_id=8,
        subject_code="DS",
        count=3,
        exclude_answered=True,
        no_repeat_days=2,
        use_leitner=False,
        request_id="request-1",
        skip_finalize=True,
        load_path=defaults.load_path,
        load_fallback=AsyncMock(return_value=([], {})),
        merge_results=defaults.merge_results,
        finalize=AsyncMock(return_value=([], {})),
        build_conditions=lambda **_kwargs: [],
    )


@pytest.mark.asyncio
async def test_scored_branch_passes_exact_provider_and_request_ports(monkeypatch):
    provider = providers()
    import app.services.practice.smart_scored_supplement as supplement

    monkeypatch.setattr(supplement, "ScoredSupplementRequest", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        supplement, "run_scored_supplement", AsyncMock(return_value=([], {}))
    )
    scored, _path, _weakness = create_smart_branches(request(), provider)

    result = await scored({"experiment_id": 1, "variant_key": "v"}, "scored", [7])

    assert result == ([], {})
    fields = supplement.run_scored_supplement.call_args.args[0]
    supplement.run_scored_supplement.assert_awaited_once_with(
        {
            "db": "db",
            "user_id": 8,
            "subject_code": "DS",
            "count": 3,
            "exclude_answered": True,
            "no_repeat_days": 2,
            "use_leitner": False,
            "request_id": "request-1",
            "scope_ids": [7],
            "skip_finalize": True,
            "experiment_id": 1,
            "variant_key": "v",
            "logger": fields["logger"],
            "load_scored": provider.load_scored,
            "load_fallback": provider.load_fallback,
            "merge_results": provider.merge_results,
            "finalize": provider.finalize_scored,
        }
    )


@pytest.mark.asyncio
async def test_path_branch_passes_exact_provider_and_request_ports(monkeypatch):
    provider = providers()
    import app.services.practice.smart_path_supplement as supplement

    monkeypatch.setattr(supplement, "SmartPathRequest", lambda **kwargs: kwargs)
    monkeypatch.setattr(supplement, "run_smart_path", AsyncMock(return_value=([], {})))
    _scored, path, _weakness = create_smart_branches(request(), provider)

    result = await path({"experiment_id": None, "variant_key": None}, "path", [9])

    assert result == ([], {})
    fields = supplement.run_smart_path.call_args.args[0]
    assert {key: fields[key] for key in fields if key != "logger"} == {
        "db": "db",
        "user_id": 8,
        "subject_code": "DS",
        "count": 3,
        "exclude_answered": True,
        "no_repeat_days": 2,
        "use_leitner": False,
        "scope_ids": [9],
        "skip_finalize": True,
        "experiment_id": None,
        "variant_key": None,
        "request_id": "request-1",
        "load_path": provider.load_path,
        "load_fallback": provider.load_fallback,
        "merge_results": provider.merge_results,
        "finalize": provider.finalize_path,
        "build_conditions": provider.build_path_conditions,
    }


@pytest.mark.asyncio
async def test_weakness_branch_delegates_keywords_to_service_fallback():
    provider = providers()
    _scored, _path, weakness = create_smart_branches(request(), provider)
    await weakness(db="db", user_id=8, subject_code="DS")
    provider.load_fallback.assert_not_awaited()
    provider.run_weakness.assert_awaited_once_with(
        db="db", user_id=8, subject_code="DS"
    )
