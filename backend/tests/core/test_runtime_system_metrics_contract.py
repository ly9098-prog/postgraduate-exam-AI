"""Characterize system, storage, SSE and scheduler metrics output boundaries."""

from unittest.mock import AsyncMock, Mock

import pytest

from app import main
from tests.core.test_runtime_metrics_contract import (
    incoming,
)
from tests.core.test_runtime_metrics_contract import (
    metrics_ports as metrics_ports,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("port", ["staging", "database", "system"])
async def test_storage_and_system_error_boundaries(monkeypatch, metrics_ports, port):
    failure = RuntimeError("synthetic collector failure")
    if port == "staging":
        monkeypatch.setattr(metrics_ports.staging, "get_metrics", Mock(side_effect=failure))
    elif port == "database":
        monkeypatch.setattr(metrics_ports.database, "get_db_query_metrics", Mock(side_effect=failure))
    else:
        monkeypatch.setattr(metrics_ports.resources, "get_system_metrics", Mock(side_effect=failure))
        with pytest.raises(RuntimeError) as caught:
            await main.metrics_endpoint(incoming())
        assert caught.value is failure
        metrics_ports.ocr.get_gateway.assert_not_called()
        metrics_ports.staging.get_metrics.assert_not_called()
        return
    lines = (await main.metrics_endpoint(incoming())).body.decode().splitlines()
    if port == "staging":
        assert "staging_disk_usage_bytes 0" in lines
        assert "staging_object_count 3" not in lines
        assert lines[-1] == "staging_orphan_count 0"
        assert metrics_ports.staging.get_metrics.call_count == 2
    else:
        assert "db_query_metrics_available 0" in lines
        assert "db_query_total 12" not in lines
        assert lines[-1] == "staging_orphan_count 2"
    assert "process_uptime_seconds 125" in lines


@pytest.mark.asyncio
async def test_staging_sample_and_cleanup_sample_are_separate_reads(monkeypatch, metrics_ports):
    monkeypatch.setattr(metrics_ports.staging, "get_metrics", Mock(side_effect=[
        {"disk_usage_bytes": 1, "object_count": 2, "leased_count": 3, "orphan_count": 4},
        {"orphan_count": 9},
    ]))
    lines = (await main.metrics_endpoint(incoming())).body.decode().splitlines()
    assert "staging_disk_usage_bytes 1" in lines
    assert "staging_object_count 2" in lines
    assert "staging_leased_count 3" in lines
    assert lines[-1] == "staging_orphan_count 9"


@pytest.mark.asyncio
async def test_pool_metric_filter_keeps_existing_numeric_types(monkeypatch, metrics_ports):
    monkeypatch.setattr(main, "_get_db_pool_metrics", lambda: {
        "integer": 7, "float": 1.25, "boolean": True, "string": "private", "none": None,
    })
    lines = (await main.metrics_endpoint(incoming())).body.decode().splitlines()
    assert [line for line in lines if line.startswith("db_pool_")] == [
        "db_pool_integer 7", "db_pool_float 1.25", "db_pool_boolean True",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("port,line", [
    ("pubsub", "sse_healthy 0"), ("connections_type", "sse_active_connections 0"),
    ("connections_values", "sse_active_connections 0"), ("counters_type", None),
    ("worker", "worker_draining 0"),
    ("audit", 'scheduler_running{name="audit_cleanup"} 0'),
    ("recommendation", 'scheduler_running{name="recommendation_metrics"} 0'),
])
async def test_sse_and_scheduler_collectors_keep_independent_fallbacks(
    monkeypatch, metrics_ports, port, line
):
    from app.features import batch_image_import_service
    from app.services import (
        audit_cleanup_scheduler,
        import_sse_metrics,
        recommendation_metrics_scheduler,
        sse_pubsub,
        task_queue_worker,
    )

    class BrokenScheduler:
        @property
        def _running(self):
            raise RuntimeError("synthetic scheduler failure")

    if port == "pubsub":
        monkeypatch.setattr(sse_pubsub, "check_health", AsyncMock(side_effect=RuntimeError("private")))
    elif port.startswith("connections"):
        value = [] if port == "connections_type" else {"invalid": "value"}
        monkeypatch.setattr(batch_image_import_service, "_active_sse_connections", value)
    elif port == "counters_type":
        monkeypatch.setattr(import_sse_metrics, "counters", None)
    elif port == "worker":
        monkeypatch.setattr(task_queue_worker, "is_draining_v2", Mock(side_effect=RuntimeError("private")))
    elif port == "audit":
        monkeypatch.setattr(audit_cleanup_scheduler, "audit_log_cleanup_scheduler", BrokenScheduler())
    else:
        monkeypatch.setattr(
            recommendation_metrics_scheduler, "recommendation_metrics_scheduler", BrokenScheduler(),
        )
    lines = (await main.metrics_endpoint(incoming())).body.decode().splitlines()
    if line:
        assert line in lines
    else:
        assert "sse_connections 7" not in lines
    assert lines[-1] == "staging_orphan_count 2"
