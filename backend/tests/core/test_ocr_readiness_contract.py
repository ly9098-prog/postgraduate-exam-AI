"""Characterize OCR readiness state transitions and health transport."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import main
from app.core import log_context
from app.services import ocr_readiness


@pytest.fixture
def ocr_probe(monkeypatch):
    monkeypatch.setattr(main.ocr_readiness_state, "consecutive_failures", 0)
    monkeypatch.setattr(main, "settings", SimpleNamespace(
        OCR_ENABLED=True, OCR_EXECUTION_BACKEND="paddlex_http", OCR_USE_GPU=False,
        OCR_REMOTE_TOKEN="synthetic-token", OCR_REMOTE_URL="https://ocr.example/ocr/",
        OCR_REMOTE_AUTH_HEADER="Authorization", OCR_REMOTE_AUTH_SCHEME="Bearer",
        OCR_REMOTE_HEALTH_TIMEOUT_SEC=2.5,
    ))
    monkeypatch.setattr("app.core.ocr_isolation.is_restricted_ocr_environment", lambda: False)
    monkeypatch.setattr("app.core.ocr_isolation.loaded_local_ocr_modules", lambda: [])
    log_context.clear_log_context()
    yield SimpleNamespace(
        config=main.settings,
        check=lambda: ocr_readiness.check_ocr_config(main.settings, main.ocr_readiness_state),
        connect=lambda: ocr_readiness.check_ocr_remote_connectivity(main.settings),
    )
    log_context.clear_log_context()


@pytest.mark.asyncio
async def test_consecutive_failures_recovery_and_new_failure_keep_threshold(monkeypatch, ocr_probe):
    remote = AsyncMock(side_effect=[False, False, False, False, True, False])
    monkeypatch.setattr(ocr_readiness, "check_ocr_remote_connectivity", remote)
    statuses = []
    counts = []
    for _ in range(6):
        statuses.append(await ocr_probe.check())
        counts.append(main.ocr_readiness_state.consecutive_failures)
    assert statuses == ["ok", "ok", "degraded", "degraded", "ok", "ok"]
    assert counts == [1, 2, 3, 4, 0, 1]
    assert remote.await_count == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [
    ("disabled", None), ("local", "degraded"), ("gpu", "degraded"),
    ("missing_token", "degraded"), ("non_remote", "ok"),
])
async def test_skipped_or_invalid_config_does_not_reset_existing_failures(
    monkeypatch, ocr_probe, mode, expected
):
    monkeypatch.setattr(main.ocr_readiness_state, "consecutive_failures", 3)
    remote = AsyncMock()
    monkeypatch.setattr(ocr_readiness, "check_ocr_remote_connectivity", remote)
    if mode == "disabled":
        ocr_probe.config.OCR_ENABLED = False
    elif mode == "local":
        ocr_probe.config.OCR_EXECUTION_BACKEND = "local_process"
    elif mode == "gpu":
        ocr_probe.config.OCR_USE_GPU = True
    elif mode == "missing_token":
        ocr_probe.config.OCR_REMOTE_TOKEN = ""
    else:
        ocr_probe.config.OCR_EXECUTION_BACKEND = "disabled"
    assert await ocr_probe.check() == expected
    assert main.ocr_readiness_state.consecutive_failures == 3
    remote.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [
    (200, True), (399, True), (400, True), (499, True), (500, False), (503, False),
])
@pytest.mark.parametrize("auth", ["default", "custom", "no_token"])
async def test_health_request_preserves_url_timeout_auth_and_trace(
    monkeypatch, ocr_probe, status, expected, auth
):
    import httpx

    log_context.bind_log_context(trace_id="synthetic-trace", request_id="synthetic-request")
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = SimpleNamespace(status_code=status)
    factory = Mock(return_value=client)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    headers = {"X-Trace-ID": "synthetic-trace", "X-Request-ID": "synthetic-request"}
    if auth == "custom":
        ocr_probe.config.OCR_REMOTE_AUTH_HEADER = "X-Synthetic-Token"
        ocr_probe.config.OCR_REMOTE_AUTH_SCHEME = "Token"
        headers["X-Synthetic-Token"] = "Token synthetic-token"
    elif auth == "no_token":
        ocr_probe.config.OCR_REMOTE_TOKEN = ""
    else:
        headers["Authorization"] = "Bearer synthetic-token"
    assert await ocr_probe.connect() is expected
    client.get.assert_awaited_once_with("https://ocr.example/ocr/health", headers=headers)
    assert factory.call_args.kwargs["timeout"].read == 2.5
    assert main.ocr_readiness_state.consecutive_failures == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["error", "cancel"])
async def test_transport_error_and_cancellation_preserve_state(monkeypatch, ocr_probe, kind):
    import httpx

    monkeypatch.setattr(main.ocr_readiness_state, "consecutive_failures", 2)
    client = AsyncMock()
    client.__aenter__.return_value = client
    error = asyncio.CancelledError() if kind == "cancel" else OSError("synthetic")
    client.get.side_effect = error
    monkeypatch.setattr(httpx, "AsyncClient", Mock(return_value=client))
    if kind == "cancel":
        with pytest.raises(asyncio.CancelledError) as caught:
            await ocr_probe.check()
        assert caught.value is error
        assert main.ocr_readiness_state.consecutive_failures == 2
    else:
        assert await ocr_probe.check() == "degraded"
        assert main.ocr_readiness_state.consecutive_failures == 3


@pytest.mark.asyncio
async def test_failure_state_is_isolated_between_explicit_owners(monkeypatch, ocr_probe):
    first = ocr_readiness.OcrReadinessState()
    second = ocr_readiness.OcrReadinessState()
    remote = AsyncMock(return_value=False)
    monkeypatch.setattr(ocr_readiness, "check_ocr_remote_connectivity", remote)
    for _ in range(3):
        await ocr_readiness.check_ocr_config(ocr_probe.config, first)
    assert first.consecutive_failures == 3
    assert second.consecutive_failures == 0
    assert await ocr_readiness.check_ocr_config(ocr_probe.config, second) == "ok"
    assert second.consecutive_failures == 1
