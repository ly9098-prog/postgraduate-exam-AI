"""Read-only Redis capacity telemetry and bounded per-answer key scan."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.schemas.observability import TaskRedisDiagnosticsResponse
from app.services import task_observability_service as service
from app.services.task_observability_rules import evaluate_task_health
from app.services.task_queue_service import task_queue


def _health(redis: dict) -> dict:
    return evaluate_task_health(
        outbox={"counts": {}, "oldest_unpublished_seconds": 0},
        redis={"configured": True, "available": True, "totals": {}, **redis},
        projection={"unprojected": 0},
        async_runtime_expected=True,
    )


@pytest.mark.parametrize(
    ("used", "expected"),
    [
        (49, None),
        (50, "REDIS_MEMORY_HIGH"),
        (75, "REDIS_MEMORY_CRITICAL"),
    ],
)
def test_memory_thresholds(used: int, expected: str | None):
    health = _health({"memory": {"used_bytes": used, "max_bytes": 100}})
    memory_codes = [
        i["code"] for i in health["issues"] if i["code"].startswith("REDIS_MEMORY_")
    ]
    assert memory_codes == ([expected] if expected else [])
    assert health["severity"] == (
        "error" if used >= 75 else "warning" if used >= 50 else "ok"
    )


def test_key_scan_and_unlimited_memory_raise_actionable_issues():
    health = _health(
        {
            "memory": {"used_bytes": 123, "max_bytes": 0, "evicted_keys": 2},
            "projection_keys": {
                "available": True,
                "complete": True,
                "idempotent_no_ttl": 1,
                "fencing": 3,
            },
        }
    )
    codes = {i["code"] for i in health["issues"]}
    assert codes == {
        "REDIS_MEMORY_LIMIT_UNSET",
        "REDIS_KEYS_EVICTED",
        "REDIS_PROJECTION_GUARD_NO_TTL",
    }
    assert health["severity"] == "error"


def test_incomplete_and_unavailable_scans_never_report_healthy_counts():
    partial = _health(
        {
            "memory": {"used_bytes": 1, "max_bytes": 100},
            "projection_keys": {"available": True, "complete": False},
        }
    )
    assert [i["code"] for i in partial["issues"]] == [
        "REDIS_PROJECTION_SCAN_INCOMPLETE"
    ]
    unavailable = _health(
        {
            "memory": {"used_bytes": 1, "max_bytes": 100},
            "projection_keys": {"available": False, "complete": False},
        }
    )
    assert [i["code"] for i in unavailable["issues"]] == [
        "REDIS_PROJECTION_SCAN_UNAVAILABLE"
    ]
    redis_down = evaluate_task_health(
        outbox={"counts": {}},
        redis={"configured": True, "available": False},
        projection={},
        async_runtime_expected=True,
    )
    assert [i["code"] for i in redis_down["issues"]] == ["REDIS_UNAVAILABLE"]


def test_missing_memory_telemetry_is_not_misreported_as_redis_outage():
    health = _health({"memory": None})
    assert [i["code"] for i in health["issues"]] == ["REDIS_MEMORY_METRICS_UNAVAILABLE"]


class _FakePipeline:
    def __init__(self, ttls: dict[str, int]):
        self.ttls = ttls
        self.keys: list[str] = []

    def ttl(self, key: str):
        self.keys.append(key)
        return self

    async def execute(self) -> list[int]:
        return [self.ttls[k] for k in self.keys]


class _FakeClient:
    def __init__(self, pages: list[tuple[int, list[str]]], ttls: dict[str, int]):
        self.pages = iter(pages)
        self.ttls = ttls
        self.closed = False

    async def scan(self, **kwargs):
        assert kwargs["match"] == "taskq:v2:*:answer_projection:*"
        return next(self.pages)

    def pipeline(self, *, transaction: bool):
        assert transaction is False
        return _FakePipeline(self.ttls)

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_projection_scan_counts_only_matching_keys_and_checks_guard_ttl(
    monkeypatch,
):
    prefix = "taskq:v2:"
    guard = prefix + "idempotent:answer_projection:1"
    client = _FakeClient(
        [
            (1, [guard, prefix + "fencing:answer_projection:1"]),
            (
                0,
                [
                    prefix + "task:answer_projection:1",
                    prefix + "heartbeat:answer_projection:1",
                ],
            ),
        ],
        {guard: -1},
    )
    monkeypatch.setattr(
        task_queue, "_get_script_client", AsyncMock(return_value=client)
    )
    result = await service._collect_projection_key_metrics()
    assert result == {
        "available": True,
        "complete": True,
        "idempotent": 1,
        "fencing": 1,
        "task": 1,
        "idempotent_no_ttl": 1,
    }
    assert client.closed


@pytest.mark.asyncio
async def test_projection_scan_budget_reports_partial_not_full(monkeypatch):
    client = _FakeClient(
        [(100, ["taskq:v2:idempotent:answer_projection:1"])],
        {"taskq:v2:idempotent:answer_projection:1": 3600},
    )
    monkeypatch.setattr(service, "_PROJECTION_SCAN_MAX_PAGES", 1)
    monkeypatch.setattr(
        task_queue, "_get_script_client", AsyncMock(return_value=client)
    )
    result = await service._collect_projection_key_metrics()
    assert result["available"] and not result["complete"]
    assert result["idempotent"] == 1
    assert result["idempotent_no_ttl"] == 0
    assert client.closed


@pytest.mark.asyncio
async def test_projection_scan_timeout_does_not_block_health_loop(monkeypatch):
    client = _FakeClient([], {})

    async def slow_scan(**kwargs):
        await asyncio.sleep(0.1)
        return 0, []

    client.scan = slow_scan
    monkeypatch.setattr(service, "_PROJECTION_SCAN_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(
        task_queue, "_get_script_client", AsyncMock(return_value=client)
    )
    result = await service._collect_projection_key_metrics()
    assert result["available"] is False and result["complete"] is False
    assert client.closed


@pytest.mark.asyncio
async def test_queue_snapshot_exposes_info_memory_without_scanning(monkeypatch):
    client = MagicMock()
    client.ping = AsyncMock()
    client.info = AsyncMock()
    client.aclose = AsyncMock()
    client.scan = AsyncMock()
    client.info.side_effect = [
        {"used_memory": 50, "maxmemory": 100},
        {"evicted_keys": 1},
    ]
    queue_pipe = _FakePipeline({})
    queue_pipe.llen = lambda *args: queue_pipe
    queue_pipe.zcard = lambda *args: queue_pipe
    queue_pipe.lindex = lambda *args: queue_pipe
    queue_pipe.execute = AsyncMock(
        return_value=[0] * (len(service.OBSERVED_TASK_TYPES) * 6)
    )
    client.pipeline.return_value = queue_pipe
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(
        task_queue, "_get_script_client", AsyncMock(return_value=client)
    )
    result = await service._collect_queue_metrics()
    assert result["available"] is True
    assert result["memory"] == {
        "used_bytes": 50,
        "max_bytes": 100,
        "used_percent": 50.0,
        "evicted_keys": 1,
        "warning_percent": settings.TASK_HEALTH_REDIS_MEMORY_WARN_PCT,
        "error_percent": settings.TASK_HEALTH_REDIS_MEMORY_ERROR_PCT,
    }
    client.scan.assert_not_called()
    TaskRedisDiagnosticsResponse.model_validate(result)
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_queue_commands_remain_available_if_info_is_restricted(monkeypatch):
    client = MagicMock()
    client.ping = AsyncMock()
    client.info = AsyncMock(side_effect=RuntimeError("INFO disabled"))
    client.aclose = AsyncMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[0] * (len(service.OBSERVED_TASK_TYPES) * 6))
    client.pipeline.return_value = pipe
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(
        task_queue, "_get_script_client", AsyncMock(return_value=client)
    )
    result = await service._collect_queue_metrics()
    assert result["available"] is True
    assert result["memory"] is None
    assert [i["code"] for i in _health(result)["issues"]] == [
        "REDIS_MEMORY_METRICS_UNAVAILABLE"
    ]


@pytest.mark.asyncio
async def test_collector_passes_periodic_key_sample_to_health_rules(monkeypatch):
    monkeypatch.setattr(
        service, "_collect_outbox_metrics", AsyncMock(return_value={"counts": {}})
    )
    monkeypatch.setattr(
        service,
        "_collect_projection_metrics",
        AsyncMock(return_value={"unprojected": 0}),
    )
    monkeypatch.setattr(service, "_collect_activity_trend", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        service,
        "_collect_queue_metrics",
        AsyncMock(
            return_value={
                "configured": True,
                "available": True,
                "totals": {},
                "memory": {"used_bytes": 80, "max_bytes": 100},
            }
        ),
    )
    monkeypatch.setattr(service, "_async_runtime_expected", lambda: True)
    sample = {"available": True, "complete": True, "idempotent_no_ttl": 1}
    snapshot = await service.collect_task_diagnostics(
        AsyncMock(), projection_keys=sample
    )
    assert snapshot["redis"]["projection_keys"] == sample
    assert {item["code"] for item in snapshot["health"]["issues"]} == {
        "REDIS_MEMORY_CRITICAL",
        "REDIS_PROJECTION_GUARD_NO_TTL",
    }


@pytest.mark.asyncio
async def test_recent_answer_rate_is_derived_from_durable_practice_records():
    db = AsyncMock()
    db.scalar.return_value = 17
    assert await service._count_recent_answers(db) == 17
    query = str(db.scalar.await_args.args[0])
    assert "practice_records.answered_at" in query
    assert "practice_records.projection_state" in query


@pytest.mark.asyncio
async def test_monitor_samples_projection_keys_and_answer_rate(monkeypatch):
    from app.core import database

    @asynccontextmanager
    async def fake_session():
        yield AsyncMock()

    monkeypatch.setattr(database, "async_session", fake_session)
    sample = {
        "available": True,
        "complete": True,
        "idempotent": 1,
        "fencing": 1,
        "task": 0,
        "idempotent_no_ttl": 0,
    }
    key_collector = AsyncMock(return_value=sample)
    answer_counter = AsyncMock(return_value=5)
    diagnostics = AsyncMock(return_value={"health": {"severity": "ok", "issues": []}})
    monkeypatch.setattr(service, "_collect_projection_key_metrics", key_collector)
    monkeypatch.setattr(service, "_count_recent_answers", answer_counter)
    monkeypatch.setattr(service, "collect_task_diagnostics", diagnostics)
    sleeps = 0

    async def stop_after_first_cycle(_delay):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(service.asyncio, "sleep", stop_after_first_cycle)
    with pytest.raises(asyncio.CancelledError):
        await service.run_task_health_monitor()
    key_collector.assert_awaited_once()
    answer_counter.assert_awaited_once()
    assert diagnostics.await_args.kwargs["projection_keys"] == sample
