"""Export task-performance and WebSocket metrics.

Simple in-process Prometheus-style counters and histograms.
Can be extended to use the ``prometheus-client`` library when deployed.
"""

from __future__ import annotations

from threading import Lock

_lock = Lock()

# ── Counters ──
_created = 0
_completed = 0
_failed = 0
_expired = 0
_image_download_failure = 0
_formula_fallback_png = 0
_formula_fallback_text = 0
_table_fallback = 0
_redis_publish_failure = 0
_redis_subscribe_failure = 0
_poll_fallback = 0
_cleanup_success = 0
_cleanup_failure = 0
_images_downloaded = 0
_orphan_files_found = 0
_missing_files_found = 0

# ── Histograms (lists of observations) ──
_processing_seconds: list[float] = []
_queue_wait_seconds: list[float] = []
_file_size_bytes: list[float] = []

# ── Current state gauges (stored as simple ints) ──
_ws_connections = 0
_pending_tasks = 0
_processing_tasks = 0


def inc_created():
    global _created
    with _lock:
        _created += 1


def inc_completed():
    global _completed
    with _lock:
        _completed += 1


def inc_failed():
    global _failed
    with _lock:
        _failed += 1


def inc_expired():
    global _expired
    with _lock:
        _expired += 1


def inc_image_download_failure():
    global _image_download_failure
    with _lock:
        _image_download_failure += 1


def inc_formula_fallback(target: str = "png"):
    global _formula_fallback_png, _formula_fallback_text
    with _lock:
        if target == "png":
            _formula_fallback_png += 1
        else:
            _formula_fallback_text += 1


def inc_table_fallback():
    global _table_fallback
    with _lock:
        _table_fallback += 1


def inc_redis_publish_failure():
    global _redis_publish_failure
    with _lock:
        _redis_publish_failure += 1


def inc_redis_subscribe_failure():
    global _redis_subscribe_failure
    with _lock:
        _redis_subscribe_failure += 1


def inc_poll_fallback():
    global _poll_fallback
    with _lock:
        _poll_fallback += 1


def inc_cleanup_success():
    global _cleanup_success
    with _lock:
        _cleanup_success += 1


def inc_cleanup_failure():
    global _cleanup_failure
    with _lock:
        _cleanup_failure += 1


def inc_orphan_files(count: int = 1):
    global _orphan_files_found
    with _lock:
        _orphan_files_found += count


def inc_missing_files(count: int = 1):
    global _missing_files_found
    with _lock:
        _missing_files_found += count


def inc_ws_connections():
    global _ws_connections
    with _lock:
        _ws_connections += 1


def dec_ws_connections():
    global _ws_connections
    with _lock:
        _ws_connections = max(0, _ws_connections - 1)


def set_pending(n: int):
    global _pending_tasks
    with _lock:
        _pending_tasks = n


def set_processing(n: int):
    global _processing_tasks
    with _lock:
        _processing_tasks = n


def observe_processing_seconds(seconds: float):
    with _lock:
        _processing_seconds.append(seconds)
        if len(_processing_seconds) > 10_000:
            _processing_seconds[:5000] = []


def observe_queue_wait_seconds(seconds: float):
    with _lock:
        _queue_wait_seconds.append(seconds)
        if len(_queue_wait_seconds) > 10_000:
            _queue_wait_seconds[:5000] = []


def observe_file_size_bytes(size: int):
    with _lock:
        _file_size_bytes.append(float(size))
        if len(_file_size_bytes) > 10_000:
            _file_size_bytes[:5000] = []


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100.0
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def get_metrics() -> dict:
    """Return all metrics as a dict (Prometheus exposition-format compatible)."""
    total_formula_fallback = _formula_fallback_png + _formula_fallback_text
    total_created = _created
    total_completed = _completed
    total_failed = _failed
    success_rate = (
        (total_completed / total_created * 100)
        if total_created > 0
        else 100.0
    )

    with _lock:
        proc_copy = _processing_seconds.copy()
        queue_copy = _queue_wait_seconds.copy()
        size_copy = _file_size_bytes.copy()

    return {
        # Counters
        "export_created_total": total_created,
        "export_completed_total": total_completed,
        "export_failed_total": total_failed,
        "export_expired_total": _expired,
        "export_success_rate": round(success_rate, 2),
        "export_image_download_failure_total": _image_download_failure,
        "export_formula_fallback_total": total_formula_fallback,
        "export_formula_fallback_png": _formula_fallback_png,
        "export_formula_fallback_text": _formula_fallback_text,
        "export_table_fallback_total": _table_fallback,
        "export_redis_publish_failure_total": _redis_publish_failure,
        "export_redis_subscribe_failure_total": _redis_subscribe_failure,
        "export_poll_fallback_total": _poll_fallback,
        "export_cleanup_success_total": _cleanup_success,
        "export_cleanup_failure_total": _cleanup_failure,
        "export_orphan_files": _orphan_files_found,
        "export_missing_files": _missing_files_found,
        # Gauges
        "export_ws_connections": _ws_connections,
        "export_tasks_pending": _pending_tasks,
        "export_tasks_processing": _processing_tasks,
        # Histograms
        "export_processing_seconds_count": len(proc_copy),
        "export_processing_seconds_sum": sum(proc_copy),
        "export_processing_seconds_avg": (sum(proc_copy) / len(proc_copy)) if proc_copy else 0,
        "export_processing_seconds_p50": _percentile(proc_copy, 50),
        "export_processing_seconds_p95": _percentile(proc_copy, 95),
        "export_processing_seconds_p99": _percentile(proc_copy, 99),
        "export_queue_wait_seconds_count": len(queue_copy),
        "export_queue_wait_seconds_sum": sum(queue_copy),
        "export_queue_wait_seconds_avg": (sum(queue_copy) / len(queue_copy)) if queue_copy else 0,
        "export_queue_wait_seconds_p50": _percentile(queue_copy, 50),
        "export_queue_wait_seconds_p95": _percentile(queue_copy, 95),
        "export_queue_wait_seconds_p99": _percentile(queue_copy, 99),
        "export_file_size_bytes_count": len(size_copy),
        "export_file_size_bytes_sum": int(sum(size_copy)),
        "export_file_size_bytes_avg": int((sum(size_copy) / len(size_copy)) if size_copy else 0),
        "export_file_size_bytes_p50": int(_percentile(size_copy, 50)),
        "export_file_size_bytes_p95": int(_percentile(size_copy, 95)),
        "export_file_size_bytes_p99": int(_percentile(size_copy, 99)),
    }


def metrics_as_prometheus() -> str:
    """Render metrics in Prometheus exposition format (text/plain)."""
    data = get_metrics()
    lines = []
    for key, value in data.items():
        if isinstance(value, float):
            lines.append(f"{key} {value}")
        elif isinstance(value, int):
            lines.append(f"{key} {value}")
    # Add histogram buckets (simplified)
    return "# HELP export metrics from 2240AI export pipeline\n# TYPE export counter\n" + "\n".join(lines) + "\n"
