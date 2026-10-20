"""Prometheus queue sampling, preserving the existing partial-failure fallback."""

from collections.abc import Mapping


async def append_queue_depth_metrics(lines: list[str]) -> None:
    _append = lines.append
    task_types = [
        "import_pipeline",
        "image_pipeline",
        "excel_pipeline",
        "resume_pipeline",
        "admin_resume",
        "batch_image",
        "formula_batch",
        "prewarm_analysis",
        "export_mistakes",
        "answer_projection",
        "error_diagnosis",
    ]
    try:
        from app.services.task_queue_service import task_queue

        for tt in task_types:
            ready = await task_queue.ready_length_v2(tt)
            processing = await task_queue.processing_length_v2(tt)
            retry_count = await task_queue.retry_length_v2(tt)
            dead = await task_queue.dead_length_v2(tt)
            corrupt = await task_queue.corrupt_length_v2(tt)
            oldest_age = await task_queue.oldest_ready_age_v2(tt)
            _append(f'task_queue_ready{{type="{tt}"}} {ready}')
            _append(f'task_queue_processing{{type="{tt}"}} {processing}')
            _append(f'task_queue_retry{{type="{tt}"}} {retry_count}')
            _append(f'task_queue_dead{{type="{tt}"}} {dead}')
            _append(f'task_queue_corrupt{{type="{tt}"}} {corrupt}')
            _append(f'task_queue_oldest_ready_age_seconds{{type="{tt}"}} {oldest_age}')
    except Exception:
        for tt in task_types:
            _append(f'task_queue_ready{{type="{tt}"}} 0')
            _append(f'task_queue_processing{{type="{tt}"}} 0')
            _append(f'task_queue_retry{{type="{tt}"}} 0')
            _append(f'task_queue_dead{{type="{tt}"}} 0')
            _append(f'task_queue_corrupt{{type="{tt}"}} 0')
            _append(f'task_queue_oldest_ready_age_seconds{{type="{tt}"}} 0')


def append_queue_counters(lines: list[str], queue_metrics: Mapping[str, int]) -> None:
    _append = lines.append
    for key in (
        "lease_renewal_failure",
        "duplicate_enqueue_prevented",
        "reaper_reclaimed",
        "owner_fencing_rejected",
        "enqueue_rejected",
        "dead_purge_count",
        "corrupt_cleaned",
    ):
        _append(f"task_queue_{key} {queue_metrics.get(key, 0)}")
