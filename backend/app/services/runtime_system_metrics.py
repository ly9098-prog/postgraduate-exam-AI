"""Prometheus system, storage, database and scheduler output; state stays at its source."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.resource_guard import SystemMetrics


def append_system_metrics(
    lines: list[str], sys_metrics: "SystemMetrics", *, event_loop_lag_ms: float,
) -> None:
    _append = lines.append
    _append(f"system_rss_mb {sys_metrics.rss_mb:.1f}")
    _append(f"system_available_memory_mb {sys_metrics.available_memory_mb:.1f}")
    _append(f"system_active_pipelines {sys_metrics.active_pipelines}")
    _append(f"system_event_loop_lag_ms {event_loop_lag_ms:.2f}")


def append_staging_metrics(lines: list[str]) -> None:
    _append = lines.append
    try:
        from app.services.staging_storage import get_metrics

        sm = get_metrics()
        _append(f"staging_disk_usage_bytes {sm.get('disk_usage_bytes', 0)}")
        _append(f"staging_object_count {sm.get('object_count', 0)}")
        _append(f"staging_leased_count {sm.get('leased_count', 0)}")
    except Exception:
        _append("staging_disk_usage_bytes 0")


def append_db_pool_metrics(lines: list[str], pool_stats: Mapping[str, object]) -> None:
    _append = lines.append
    for k, v in pool_stats.items():
        if isinstance(v, (int, float)):
            _append(f"db_pool_{k} {v}")


def append_db_query_metrics(lines: list[str]) -> None:
    _append = lines.append
    try:
        from app.core.database import get_db_query_metrics

        qm = get_db_query_metrics()
        _append(f"db_query_total {qm.get('total', 0)}")
        _append(f"db_slow_query_total {qm.get('slow', 0)}")
        _append(f"db_query_duration_ms_total {qm.get('duration_ms_total', 0)}")
        _append(f"db_query_duration_ms_avg {qm.get('duration_ms_avg', 0)}")
        _append(f"db_query_duration_ms_max {qm.get('duration_ms_max', 0)}")
    except Exception:
        _append("db_query_metrics_available 0")


def append_process_metrics(
    lines: list[str], *, role: str, environment: str, uptime_seconds: float,
) -> None:
    _append = lines.append
    _append(
        f'process_info{{role="{role}",env="{environment}"}} 1'
    )
    _append(f"process_uptime_seconds {uptime_seconds:.0f}")


def append_worker_scheduler_metrics(lines: list[str]) -> None:
    _append = lines.append
    try:
        from app.services.task_queue_worker import is_draining_v2

        _append(f"worker_draining {1 if is_draining_v2() else 0}")
    except Exception:
        _append("worker_draining 0")
    try:
        from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler

        _append(
            f'scheduler_running{{name="audit_cleanup"}} {1 if audit_log_cleanup_scheduler._running else 0}'
        )
    except Exception:
        _append('scheduler_running{name="audit_cleanup"} 0')
    try:
        from app.services.recommendation_metrics_scheduler import (
            recommendation_metrics_scheduler,
        )

        _append(
            f'scheduler_running{{name="recommendation_metrics"}} '
            f"{1 if recommendation_metrics_scheduler._running else 0}"
        )
    except Exception:
        _append('scheduler_running{name="recommendation_metrics"} 0')


def append_staging_cleanup_metrics(lines: list[str]) -> None:
    _append = lines.append
    try:
        from app.services.staging_storage import get_metrics as _staging_metrics

        _sm = _staging_metrics()
        _append(f"staging_orphan_count {_sm.get('orphan_count', 0)}")
    except Exception:
        _append("staging_orphan_count 0")
