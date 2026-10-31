"""Billed AI paths (error analysis, prewarm, study advice) must honor the per-user token budget."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services import ai_service


def test_generate_advice_over_budget_skips_provider(monkeypatch):
    chat = AsyncMock()
    monkeypatch.setattr(ai_service, "resolve_llm_runtime_config", AsyncMock(return_value=object()))
    monkeypatch.setattr(ai_service, "check_token_limit", AsyncMock(return_value=False))
    monkeypatch.setattr(ai_service, "chat_with_db_model", chat)

    result = asyncio.run(ai_service.generate_advice(SimpleNamespace(), 7))

    chat.assert_not_awaited()
    assert result["from_fallback"] is True
    assert result["tokens_used"] == 0


def test_analyze_error_over_budget_skips_lease_and_is_not_retryable(monkeypatch):
    preparation = SimpleNamespace(response=None)
    lease = AsyncMock()
    monkeypatch.setattr(ai_service, "prepare_analysis", AsyncMock(return_value=preparation))
    monkeypatch.setattr(ai_service, "check_token_limit", AsyncMock(return_value=False))
    monkeypatch.setattr(ai_service, "_analyze_error_with_lease", lease)

    result = asyncio.run(ai_service.analyze_error(SimpleNamespace(), 7, 1))

    lease.assert_not_awaited()
    assert result["error_code"] == "ai_quota_exceeded"
    assert result["retryable"] is False
    assert result["from_fallback"] is True


def test_analyze_error_within_budget_proceeds(monkeypatch):
    preparation = SimpleNamespace(response=None)
    lease = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(ai_service, "prepare_analysis", AsyncMock(return_value=preparation))
    monkeypatch.setattr(ai_service, "check_token_limit", AsyncMock(return_value=True))
    monkeypatch.setattr(ai_service, "_analyze_error_with_lease", lease)

    assert asyncio.run(ai_service.analyze_error(SimpleNamespace(), 7, 1)) == {"ok": True}


def test_prewarm_quota_rejection_is_non_retryable():
    err = ai_service._prewarm_failure_from_result(
        {"model": "fallback", "error_code": "ai_quota_exceeded", "retryable": False}
    )
    assert err.retryable is False
