"""Probe admission, shared failure state and revision isolation without real providers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.ai import gateway
from app.ai.client import OpenAICompatibleAPIError, _classify_http_error_kind
from app.core import background_tasks
from app.core.cache import CacheClient, CacheUnavailableError
from app.services.ai import (
    analysis_admin_health,
    analysis_availability,
    connection_probe,
    model_health,
)
from app.services.ai.analysis_preparation import AnalysisPreparation
from app.services.ai.provider_exception import classify_ai_provider_exception


@pytest.fixture
def runtime():
    return gateway.LLMRuntimeConfig(
        api_key="synthetic-secret",
        base_url="https://model.invalid/v1",
        model_name="synthetic",
        provider="openai_compatible",
        model_config_id=11,
        capabilities=frozenset({"analysis"}),
        config_fingerprint="revision-a",
    )


@pytest_asyncio.fixture(autouse=True)
async def isolated_health(monkeypatch, runtime):
    store = CacheClient()
    store._enabled = False
    monkeypatch.setattr(model_health, "cache", store)
    monkeypatch.setattr(
        analysis_availability,
        "list_analysis_candidates",
        AsyncMock(return_value=[runtime]),
    )
    yield store
    tasks = [
        task
        for task in background_tasks._background_tasks
        if task.get_name() == "analysis-model-probe"
    ]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def finish(runtime, *, success=True, status="ok"):
    _, token = await model_health.claim_probe(runtime, force=True)
    assert token
    return await model_health.finish_probe(
        runtime,
        token,
        {"success": success, "status": status, "latency_ms": 1},
    )


@pytest.mark.asyncio
async def test_concurrent_page_checks_share_one_probe(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def probe(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"success": True, "status": "ok"}

    mock = AsyncMock(side_effect=probe)
    monkeypatch.setattr(
        "app.services.ai.connection_probe.probe_chat_connection",
        mock,
    )
    checks = await asyncio.gather(
        *[analysis_availability.resolve_available_runtime("db") for _ in range(40)]
    )
    await entered.wait()
    assert all(
        runtime is None and state["status"] == "checking" for runtime, state in checks
    )
    assert mock.await_count == 1
    release.set()
    await asyncio.gather(
        *[
            task
            for task in background_tasks._background_tasks
            if task.get_name() == "analysis-model-probe"
        ]
    )
    selected, state = await analysis_availability.resolve_available_runtime("db")
    assert selected is not None and state["enabled"]
    assert mock.await_count == 1


@pytest.mark.asyncio
async def test_success_expires_after_30_seconds(monkeypatch, runtime):
    monkeypatch.setattr(model_health.time, "time", lambda: 1000.0)
    await finish(runtime)
    record = await model_health.read_health(runtime)
    assert model_health.public_state(record, now=1029)["enabled"]
    state = model_health.public_state(record, now=1030)
    assert state["enabled"] is False and state["status"] == "checking"


@pytest.mark.asyncio
async def test_real_failure_supersedes_running_probe(runtime):
    _, token = await model_health.claim_probe(runtime)
    await model_health.record_failure(
        runtime,
        OpenAICompatibleAPIError(401, retryable=False, error_kind="auth"),
    )
    assert await model_health.finish_probe(runtime, token, {"success": True}) is False
    state = model_health.public_state(await model_health.read_health(runtime))
    assert not state["enabled"] and state["reason"] == "configuration"


@pytest.mark.asyncio
async def test_real_model_not_found_enters_configuration_cooldown(monkeypatch, runtime):
    monkeypatch.setattr(model_health.time, "time", lambda: 1000.0)
    await finish(runtime)
    await model_health.record_failure(
        runtime,
        OpenAICompatibleAPIError(404, retryable=False, error_kind="model_not_found"),
    )

    record = await model_health.read_health(runtime)
    assert record["reason"] == "configuration"
    assert record["next_probe_at"] == 1300
    assert not model_health.public_state(record)["enabled"]


@pytest.mark.asyncio
async def test_configuration_revision_never_inherits_previous_success(runtime):
    await finish(runtime)
    updated = replace(runtime, config_fingerprint="revision-b")
    assert await model_health.read_health(updated) is None
    assert model_health.public_state(await model_health.read_health(runtime))["enabled"]


@pytest.mark.asyncio
async def test_old_revision_probe_cannot_enable_new_revision(runtime):
    _, token = await model_health.claim_probe(runtime)
    updated = replace(runtime, config_fingerprint="revision-b")
    await finish(updated, success=False, status="auth_error")
    await model_health.finish_probe(runtime, token, {"success": True})
    state = model_health.public_state(await model_health.read_health(updated))
    assert not state["enabled"]


@pytest.mark.asyncio
async def test_transient_backoff_and_success_reset(monkeypatch, runtime):
    clock = [1000.0]
    monkeypatch.setattr(model_health.time, "time", lambda: clock[0])
    for delay in (30, 60, 120, 300, 300):
        await finish(runtime, success=False, status="timeout")
        record = await model_health.read_health(runtime)
        assert record["next_probe_at"] == clock[0] + delay
        clock[0] += delay + 1
    await finish(runtime)
    clock[0] += 31
    await finish(runtime, success=False, status="timeout")
    assert (await model_health.read_health(runtime))["failures"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,reason",
    [
        ("auth_error", "configuration"),
        ("quota_error", "quota"),
        ("model_not_found", "configuration"),
    ],
)
async def test_hard_failures_cool_down_five_minutes(
    monkeypatch, runtime, status, reason
):
    monkeypatch.setattr(model_health.time, "time", lambda: 1000.0)
    await finish(runtime, success=False, status=status)
    record = await model_health.read_health(runtime)
    assert record["reason"] == reason and record["next_probe_at"] == 1300
    _, token = await model_health.claim_probe(runtime)
    assert token is None
    _, token = await model_health.claim_probe(runtime, force=True)
    assert token


@pytest.mark.asyncio
async def test_healthy_fallback_is_reused_without_probing_failed_primary(
    monkeypatch, runtime
):
    fallback = replace(runtime, model_config_id=12, config_fingerprint="fallback")
    monkeypatch.setattr(
        analysis_availability,
        "list_analysis_candidates",
        AsyncMock(return_value=[runtime, fallback]),
    )
    await finish(runtime, success=False, status="quota_error")
    await finish(fallback)
    probe = AsyncMock()
    monkeypatch.setattr(analysis_availability, "request_probe", probe)
    selected, state = await analysis_availability.resolve_available_runtime("db")
    assert selected == fallback and state["enabled"]
    probe.assert_not_called()


@pytest.mark.asyncio
async def test_cache_outage_fails_closed_without_starting_provider(monkeypatch):
    monkeypatch.setattr(
        model_health,
        "read_health",
        AsyncMock(side_effect=CacheUnavailableError()),
    )
    probe = AsyncMock()
    monkeypatch.setattr(analysis_availability, "request_probe", probe)
    selected, state = await analysis_availability.resolve_available_runtime("db")
    assert selected is None and state["reason"] == "status_unavailable"
    probe.assert_not_called()


@pytest.mark.asyncio
async def test_user_quota_does_not_change_global_health_or_start_probe(
    monkeypatch, runtime
):
    await finish(runtime)
    monkeypatch.setattr(
        "app.services.ai_learning_service.check_token_limit",
        AsyncMock(return_value=False),
    )
    probe = AsyncMock()
    monkeypatch.setattr(analysis_availability, "request_probe", probe)
    state = await analysis_availability.availability_for_user("db", 7)
    assert state["reason"] == "user_quota"
    assert model_health.public_state(await model_health.read_health(runtime))["enabled"]
    probe.assert_not_called()


@pytest.mark.asyncio
async def test_runtime_guard_refuses_unverified_model_without_business_call(runtime):
    await finish(runtime, success=False, status="auth_error")
    with pytest.raises(analysis_availability.AnalysisUnavailableError):
        await analysis_availability.require_runtime_verified(runtime)


@pytest.mark.asyncio
async def test_question_specific_request_failure_does_not_quarantine(runtime):
    await finish(runtime)
    await model_health.record_failure(
        runtime,
        OpenAICompatibleAPIError(400, retryable=False, error_kind="invalid_request"),
    )
    assert model_health.public_state(await model_health.read_health(runtime))["enabled"]


@pytest.mark.asyncio
async def test_probe_invalid_json_keeps_the_format_error_contract(monkeypatch, runtime):
    monkeypatch.setattr(
        connection_probe,
        "_probe_chat",
        AsyncMock(
            side_effect=json.JSONDecodeError("synthetic invalid response", "", 0)
        ),
    )

    result = await connection_probe.probe_chat_connection(
        runtime.base_url, runtime.api_key, runtime.model_name
    )

    assert result["success"] is False
    assert result["status"] == "format_error"


@pytest.mark.parametrize(
    "status,body,kind",
    [
        (429, '{"error":{"code":"insufficient_quota"}}', "quota"),
        (403, '{"code":"Arrearage"}', "quota"),
        (400, '{"error":"余额不足"}', "quota"),
        (429, '{"code":"Throttling.RateQuota"}', "rate_limit"),
        (403, '{"code":"AccessDenied"}', "auth"),
    ],
)
def test_quota_is_distinguished_from_rate_limit(status, body, kind):
    assert _classify_http_error_kind(status, body) == kind
    exc = OpenAICompatibleAPIError(status, retryable=False, error_kind=kind)
    code, _, _ = classify_ai_provider_exception(exc, visual=False)
    if kind == "quota":
        assert code == "ai_provider_quota_exceeded"


@pytest.mark.asyncio
async def test_unsaved_admin_test_never_changes_current_health(monkeypatch, runtime):
    await finish(runtime, success=False, status="auth_error")
    monkeypatch.setattr(
        analysis_admin_health, "saved_runtime", AsyncMock(return_value=runtime)
    )
    result = await analysis_admin_health.test_matching_saved_model(
        "db",
        11,
        base_url=runtime.base_url,
        api_key="unsaved-secret",
        model_name=runtime.model_name,
        provider=runtime.provider,
        features=["analysis"],
    )
    assert result is None
    assert not model_health.public_state(await model_health.read_health(runtime))[
        "enabled"
    ]


@pytest.mark.asyncio
async def test_saved_admin_test_bypasses_cooldown_and_restores_health(
    monkeypatch, runtime
):
    await finish(runtime, success=False, status="quota_error")
    monkeypatch.setattr(
        analysis_admin_health, "saved_runtime", AsyncMock(return_value=runtime)
    )
    probe = AsyncMock(return_value={"success": True, "status": "ok", "latency_ms": 2})
    monkeypatch.setattr("app.services.ai.connection_probe.probe_chat_connection", probe)
    result = await analysis_admin_health.test_matching_saved_model(
        "db",
        11,
        base_url=runtime.base_url,
        api_key=runtime.api_key,
        model_name=runtime.model_name,
        provider=runtime.provider,
        features=["analysis"],
    )
    assert result["success"]
    assert model_health.public_state(await model_health.read_health(runtime))["enabled"]
    probe.assert_awaited_once()


@pytest.mark.asyncio
async def test_saved_admin_edit_forces_a_revision_probe(monkeypatch, runtime):
    await finish(runtime, success=False, status="quota_error")
    monkeypatch.setattr(
        analysis_admin_health, "saved_runtime", AsyncMock(return_value=runtime)
    )
    probe = AsyncMock(return_value={})
    monkeypatch.setattr(analysis_availability, "request_probe", probe)

    await analysis_admin_health.probe_saved_model("db", 11)

    probe.assert_awaited_once_with(runtime, force=True)


@pytest.mark.asyncio
async def test_admin_probe_reuses_the_analysis_candidate_resolution(
    monkeypatch, runtime
):
    fallback = replace(runtime, model_config_id=12, config_fingerprint="fallback")
    candidates = AsyncMock(return_value=[runtime, fallback])
    monkeypatch.setattr(analysis_availability, "list_analysis_candidates", candidates)
    assert await analysis_admin_health.saved_runtime("db", 12) == fallback
    assert await analysis_admin_health.saved_runtime("db", 99) is None
    candidates.assert_awaited_with("db")


@pytest.mark.asyncio
async def test_teacher_gate_blocks_failed_shared_state_before_business_call(
    monkeypatch, runtime
):
    await finish(runtime, success=False, status="auth_error")
    business_call = AsyncMock()
    monkeypatch.setattr(gateway.llm, "chat", business_call)
    with pytest.raises(analysis_availability.AnalysisUnavailableError):
        await analysis_availability.require_available_runtime("db")
    business_call.assert_not_called()


@pytest.mark.asyncio
async def test_teacher_real_failure_updates_shared_state(runtime):
    await finish(runtime)
    await analysis_availability.note_failure(
        runtime,
        OpenAICompatibleAPIError(
            429,
            retryable=False,
            error_kind="quota",
        ),
    )
    state = model_health.public_state(await model_health.read_health(runtime))
    assert state["reason"] == "quota" and not state["enabled"]


@pytest.mark.asyncio
async def test_unavailable_regeneration_preserves_cached_content(monkeypatch, runtime):
    from app.services import ai_service

    await finish(runtime, success=False, status="auth_error")
    cached = {"content": {"mistake_diagnosis": "old"}, "from_cache": True}
    monkeypatch.setattr(
        ai_service, "build_any_cached_error_analysis_response", lambda _: cached
    )
    result = await ai_service._analyze_error_with_lease(
        "db",
        7,
        AnalysisPreparation(
            wrong_question=object(),
            question=None,
            answer_grounding=None,
            visual_sources=[],
            requires_visual=False,
            knowledge_points=[],
            runtime=None,
            input_signature="",
            model_signature=None,
            force=False,
        ),
    )
    assert result["content"] == cached["content"]
    assert result["cache_preserved"] and not result["availability"]["enabled"]
