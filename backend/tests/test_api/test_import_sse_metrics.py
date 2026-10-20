"""Exercise real SSE admission and counter updates without Redis or database IO."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1 import admin_imports
from app.features import batch_image_import_service as batch_svc
from app.services import import_sse_metrics
from app.services.runtime_sse_metrics import append_sse_metrics


@pytest.fixture
def counters(monkeypatch):
    values = dict.fromkeys(import_sse_metrics.counters, 0)
    monkeypatch.setattr(import_sse_metrics, "counters", values)
    monkeypatch.setattr(batch_svc, "_active_sse_connections", {}, raising=False)
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize("active,admin,status,code,key", [
    ({1: 50}, {"id": 1}, 503, "SSE_GLOBAL_LIMIT", "global_rejected"),
    ({1: 45, 2: 5}, {"id": 2}, 503, "SSE_GLOBAL_LIMIT", "global_rejected"),
    ({1: 5}, {"id": 1}, 429, "SSE_LIMIT", "per_user_rejected"),
    ({1: 5}, SimpleNamespace(id=1), 429, "SSE_LIMIT", "per_user_rejected"),
])
async def test_sse_limits_increment_only_matching_counter(
    monkeypatch, counters, active, admin, status, code, key
):
    monkeypatch.setattr(batch_svc, "_active_sse_connections", active)
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=True))
    result = await admin_imports.stream_batch_image_job(
        "synthetic", request, last_event_id_query=0, last_event_id_header=None,
        admin_user=admin,
    )
    assert result.status_code == status
    assert json.loads(result.body)["code"] == code
    assert counters[key] == 1
    assert sum(counters.values()) == 1
    request.is_disconnected.assert_not_awaited()
    assert batch_svc._active_sse_connections is active
    from app.services import sse_pubsub

    monkeypatch.setattr(sse_pubsub, "check_health", AsyncMock(return_value=True))
    lines = []
    await append_sse_metrics(lines)
    assert f"sse_{key} 1" in lines
    assert lines.count(f"sse_{key} 1") == 1


@pytest.mark.asyncio
async def test_disconnect_counter_and_subscription_cleanup(monkeypatch, counters):
    observed = []

    async def disconnected():
        observed.append((dict(counters), dict(batch_svc._active_sse_connections)))
        return True

    async def subscribe(*_args):
        await asyncio.Event().wait()

    monkeypatch.setattr(admin_imports, "_run_sse_subscribe", subscribe)
    response = await admin_imports.stream_batch_image_job(
        "synthetic", SimpleNamespace(is_disconnected=disconnected),
        last_event_id_query=0, last_event_id_header=None, admin_user={"id": 7},
    )
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert [chunk async for chunk in response.body_iterator] == []
    assert observed[0][0]["active"] == 1
    assert observed[0][1] == {7: 1}
    assert counters["disconnected"] == 1
    assert batch_svc._active_sse_connections == {7: 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed,event,key", [
    (7201, "timeout", "max_duration_closed"),
    (301, "idle_timeout", "max_idle_closed"),
])
async def test_timeout_counters_keep_existing_priority(monkeypatch, counters, elapsed, event, key):
    calls = iter([100.0, 100.0 + elapsed, 100.0 + elapsed])
    monkeypatch.setattr(admin_imports, "time", SimpleNamespace(time=lambda: next(calls)))

    async def subscribe(*_args):
        await asyncio.Event().wait()

    monkeypatch.setattr(admin_imports, "_run_sse_subscribe", subscribe)
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
    response = await admin_imports.stream_batch_image_job(
        "synthetic", request, last_event_id_query=0, last_event_id_header=None,
        admin_user=SimpleNamespace(id=8),
    )
    chunks = [chunk async for chunk in response.body_iterator]
    assert len(chunks) == 1 and chunks[0].startswith(f"event: {event}\n")
    assert counters[key] == 1
    request.is_disconnected.assert_not_awaited()
    assert batch_svc._active_sse_connections == {8: 0}
