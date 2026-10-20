"""Characterize metrics access and ordered sampling before extraction."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main

TASK_TYPES = [
    "import_pipeline", "image_pipeline", "excel_pipeline", "resume_pipeline",
    "admin_resume", "batch_image", "formula_batch", "prewarm_analysis",
    "export_mistakes", "answer_projection", "error_diagnosis",
]
QUEUE_METHODS = [
    "ready_length_v2", "processing_length_v2", "retry_length_v2",
    "dead_length_v2", "corrupt_length_v2", "oldest_ready_age_v2",
]
QUEUE_LABELS = ["ready", "processing", "retry", "dead", "corrupt", "oldest_ready_age_seconds"]
COUNTERS = [
    "lease_renewal_failure", "duplicate_enqueue_prevented", "reaper_reclaimed",
    "owner_fencing_rejected", "enqueue_rejected", "dead_purge_count", "corrupt_cleaned",
]


def incoming(authorization=None):
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]
    return Request({"type": "http", "method": "GET", "path": "/health/metrics", "headers": headers})


@pytest.mark.parametrize("production,token,header,allowed", [
    (False, "", None, True), (False, "synthetic-token", "Basic ignored", True),
    (True, "", None, False), (True, "   ", "Bearer synthetic-token", False),
    (True, "synthetic-token", None, False),
    (True, "synthetic-token", "Basic synthetic-token", False),
    (True, "synthetic-token", "Bearer", False),
    (True, "synthetic-token", "Bearer ", False),
    (True, "synthetic-token", "Bearer wrong", False),
    (True, "synthetic-token", "Bearer synthetic-token ", False),
    (True, "synthetic-token", "Bearer  synthetic-token", False),
    (True, "synthetic-token", "Bearer synthetic-token", True),
    (True, " synthetic-token ", "bEaReR synthetic-token", True),
])
@pytest.mark.asyncio
async def test_metrics_access_checked_before_sampling(
    monkeypatch, production, token, header, allowed
):
    from app.core.resource_guard import resource_guard

    monkeypatch.setattr(main, "_production_mode", production)
    monkeypatch.setattr(main.settings, "OBSERVABILITY_TOKEN", token)
    sentinel = RuntimeError("sampling reached")
    sample = Mock(side_effect=sentinel)
    monkeypatch.setattr(resource_guard, "get_system_metrics", sample)
    from app.services.task_queue_service import task_queue
    for method in QUEUE_METHODS:
        monkeypatch.setattr(task_queue, method, AsyncMock(return_value=0))
    if allowed:
        with pytest.raises(RuntimeError) as caught:
            await main.metrics_endpoint(incoming(header))
        assert caught.value is sentinel
        sample.assert_called_once()
    else:
        with pytest.raises(HTTPException) as caught:
            await main.metrics_endpoint(incoming(header))
        assert caught.value.status_code == 404
        assert caught.value.detail == "Not Found"
        sample.assert_not_called()
        task_queue.ready_length_v2.assert_not_awaited()


@pytest.fixture
def metrics_ports(monkeypatch):
    from app.api.v1 import admin_imports
    from app.core import ai_runtime_guard, database, resource_guard
    from app.features import batch_image_import_service, token_budget
    from app.services import (
        audit_cleanup_scheduler,
        ocr_service,
        recommendation_metrics_scheduler,
        sse_pubsub,
        staging_storage,
        task_queue_service,
        task_queue_worker,
    )

    monkeypatch.setattr(main, "_production_mode", False)
    monkeypatch.setattr(main, "_elapsed_monitor_event_loop_lag_ms", 1.234)
    monkeypatch.setattr(main, "_startup_ts", 100.0)
    monkeypatch.setattr(main, "time", SimpleNamespace(time=lambda: 225.0))
    monkeypatch.setattr(main, "_get_db_pool_metrics", lambda: {"size": 4, "error": "private"})
    monkeypatch.setattr(
        resource_guard.resource_guard, "get_system_metrics",
        lambda: SimpleNamespace(rss_mb=12.34, available_memory_mb=567.89, active_pipelines=2),
    )
    calls = []
    queue = task_queue_service.task_queue
    for index, method in enumerate(QUEUE_METHODS):
        async def sample(task_type, index=index, method=method):
            calls.append((method, task_type))
            return index + 1
        monkeypatch.setattr(queue, method, AsyncMock(side_effect=sample))
    monkeypatch.setattr(task_queue_service, "queue_metrics", {key: i + 2 for i, key in enumerate(COUNTERS)})
    gateway = SimpleNamespace(worker_metrics={"backend": "synthetic", "accepted": 9})
    monkeypatch.setattr(ocr_service, "get_gateway", Mock(return_value=gateway))
    monkeypatch.setattr(
        ai_runtime_guard.ai_runtime_guard, "metrics_snapshot",
        Mock(return_value={"requests": 4, "tokens": 17, "queue_wait_ms_avg": 1.5}),
    )
    monkeypatch.setattr(
        token_budget, "get_shared_token_usage_snapshot",
        AsyncMock(return_value={"daily": 20, "monthly": 30, "shared": True}),
    )
    monkeypatch.setattr(staging_storage, "get_metrics", Mock(return_value={
        "disk_usage_bytes": 40, "object_count": 3, "leased_count": 1, "orphan_count": 2,
    }))
    monkeypatch.setattr(database, "get_db_query_metrics", lambda: {"total": 12})
    monkeypatch.setattr(sse_pubsub, "check_health", AsyncMock(return_value=True))
    monkeypatch.setattr(
        batch_image_import_service, "_active_sse_connections", {"a": 2, "b": 3}, raising=False,
    )
    monkeypatch.setattr(admin_imports, "_sse_metrics", {"connections": 7})
    monkeypatch.setattr(task_queue_worker, "is_draining_v2", lambda: False)
    monkeypatch.setattr(audit_cleanup_scheduler.audit_log_cleanup_scheduler, "_running", True)
    monkeypatch.setattr(
        recommendation_metrics_scheduler.recommendation_metrics_scheduler, "_running", False,
    )
    return SimpleNamespace(
        queue=queue, calls=calls, ocr=ocr_service, guard=ai_runtime_guard.ai_runtime_guard,
        budget=token_budget, staging=staging_storage,
    )


@pytest.mark.asyncio
async def test_ordered_metrics_text_and_sampling_contract(metrics_ports):
    response = await main.metrics_endpoint(incoming())
    lines = response.body.decode().splitlines()
    expected_queue = [
        f'task_queue_{label}{{type="{task_type}"}} {index + 1}'
        for task_type in TASK_TYPES for index, label in enumerate(QUEUE_LABELS)
    ]
    assert lines[:66] == expected_queue
    assert metrics_ports.calls == [
        (method, task_type) for task_type in TASK_TYPES for method in QUEUE_METHODS
    ]
    assert lines[66:73] == [f"task_queue_{key} {i + 2}" for i, key in enumerate(COUNTERS)]
    assert lines[73:77] == [
        "system_rss_mb 12.3", "system_available_memory_mb 567.9",
        "system_active_pipelines 2", "system_event_loop_lag_ms 1.23",
    ]
    assert 'ocr_circuit_state{backend="synthetic"} 1' in lines
    assert 'ocr_circuit{backend="synthetic",state="unknown"} 1' in lines
    assert "ocr_accepted_total 9" in lines
    assert "ai_requests_total 4" in lines
    assert "ai_tokens_total 17" in lines
    assert "ai_queue_wait_ms_avg 1.5" in lines
    assert "ai_pipeline_tokens_daily 20" in lines
    assert "ai_pipeline_tokens_monthly 30" in lines
    assert "ai_pipeline_token_budget_shared 1" in lines
    assert "db_pool_size 4" in lines
    assert not any("private" in line for line in lines)
    assert "process_uptime_seconds 125" in lines
    assert "sse_active_connections 5" in lines
    assert "sse_connections 7" in lines
    assert lines[-1] == "staging_orphan_count 2"
    assert response.body.endswith(b"\n")
    assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"


@pytest.mark.asyncio
@pytest.mark.parametrize("task_index", [0, 1, 10])
@pytest.mark.parametrize("method", QUEUE_METHODS)
async def test_queue_failure_keeps_prior_lines_then_appends_full_zero_fallback(
    monkeypatch, metrics_ports, task_index, method
):
    original = getattr(metrics_ports.queue, method)

    async def fail_at(task_type):
        if task_type == TASK_TYPES[task_index]:
            raise RuntimeError("synthetic sampling failure")
        return await original(task_type)

    monkeypatch.setattr(metrics_ports.queue, method, fail_at)
    response = await main.metrics_endpoint(incoming())
    lines = response.body.decode().splitlines()
    prefix = [
        f'task_queue_{label}{{type="{task_type}"}} {index + 1}'
        for task_type in TASK_TYPES[:task_index] for index, label in enumerate(QUEUE_LABELS)
    ]
    zeros = [
        f'task_queue_{label}{{type="{task_type}"}} 0'
        for task_type in TASK_TYPES for label in QUEUE_LABELS
    ]
    assert lines[:len(prefix) + 66] == prefix + zeros
    assert lines[len(prefix) + 66] == "task_queue_lease_renewal_failure 2"
    assert "system_rss_mb 12.3" in lines


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ocr_none", "ocr_failure", "ai_failure", "budget_failure"])
async def test_inference_sampling_keeps_original_fallback_boundaries(
    monkeypatch, metrics_ports, kind
):
    if kind == "ocr_none":
        monkeypatch.setattr(metrics_ports.ocr, "get_gateway", lambda: None)
    elif kind == "ocr_failure":
        monkeypatch.setattr(metrics_ports.ocr, "get_gateway", Mock(side_effect=RuntimeError("private")))
    elif kind == "ai_failure":
        monkeypatch.setattr(metrics_ports.guard, "metrics_snapshot", Mock(side_effect=RuntimeError("private")))
    else:
        monkeypatch.setattr(
            metrics_ports.budget, "get_shared_token_usage_snapshot",
            AsyncMock(side_effect=RuntimeError("private")),
        )
    response = await main.metrics_endpoint(incoming())
    lines = response.body.decode().splitlines()
    if kind == "ocr_none":
        assert not any(line.startswith("ocr_") for line in lines)
    elif kind == "ocr_failure":
        assert "ocr_circuit 0" in lines
    else:
        assert "ai_runtime_metrics_available 0" in lines
        assert ("ai_requests_total 4" in lines) is (kind == "budget_failure")
        assert "ai_pipeline_tokens_daily 20" not in lines
    assert "staging_disk_usage_bytes 40" in lines
    assert lines[-1] == "staging_orphan_count 2"


@pytest.mark.asyncio
@pytest.mark.parametrize("port", ["queue", "budget"])
async def test_sampling_cancellation_propagates_and_stops_later_collectors(
    monkeypatch, metrics_ports, port
):
    cancelled = asyncio.CancelledError()
    if port == "queue":
        monkeypatch.setattr(
            metrics_ports.queue, "ready_length_v2", AsyncMock(side_effect=cancelled),
        )
    else:
        monkeypatch.setattr(
            metrics_ports.budget, "get_shared_token_usage_snapshot",
            AsyncMock(side_effect=cancelled),
        )
    with pytest.raises(asyncio.CancelledError) as caught:
        await main.metrics_endpoint(incoming())
    assert caught.value is cancelled
    metrics_ports.staging.get_metrics.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("port", ["ocr", "ai"])
async def test_partial_inference_lines_survive_later_field_failure(
    monkeypatch, metrics_ports, port
):
    class BrokenSnapshot(dict):
        def get(self, key, default=None):
            if key in {"circuit_state", "tokens"}:
                raise RuntimeError("synthetic field failure")
            return super().get(key, default)

    if port == "ocr":
        monkeypatch.setattr(metrics_ports.ocr, "get_gateway", lambda: SimpleNamespace(
            worker_metrics=BrokenSnapshot(backend="synthetic"),
        ))
    else:
        monkeypatch.setattr(
            metrics_ports.guard, "metrics_snapshot",
            lambda: BrokenSnapshot(requests=8, success=7, failures=1),
        )
    response = await main.metrics_endpoint(incoming())
    lines = response.body.decode().splitlines()
    if port == "ocr":
        first = lines.index('ocr_circuit_state{backend="synthetic"} 1')
        assert lines[first + 1] == "ocr_circuit 0"
    else:
        first = lines.index("ai_requests_total 8")
        assert lines[first:first + 4] == [
            "ai_requests_total 8", "ai_success_total 7", "ai_failures_total 1",
            "ai_runtime_metrics_available 0",
        ]
    assert lines[-1] == "staging_orphan_count 2"
