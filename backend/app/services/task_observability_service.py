"""Production diagnostics for the durable async-task pipeline.

The service intentionally derives health from the systems of record instead of
maintaining another mutable metrics store:

* PostgreSQL ``task_outbox`` -> publish backlog / failures / correlation metadata
* Redis v2 task queues       -> ready/processing/retry/dead/corrupt state
* PracticeRecord receipts    -> answer-projection business completeness

This keeps the diagnostics useful even after process restarts and avoids a
second source of truth for task health.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import resolve_effective_process_role, settings
from app.core.time_utils import serialize_utc_datetime, utcnow
from app.models.answer_behavior import AnswerBehavior
from app.models.task_outbox import TaskOutbox
from app.services.task_observability_rules import evaluate_task_health
from app.services.practice.projection_reconciliation_service import (
    get_projection_backlog_metrics,
)

logger = logging.getLogger("postgraduate-ai.task-observability")

OBSERVED_TASK_TYPES: tuple[str, ...] = (
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
)


async def _collect_outbox_metrics(db: AsyncSession) -> dict[str, Any]:
    counts = {"pending": 0, "leased": 0, "published": 0, "failed": 0, "cancelled": 0}
    grouped = await db.execute(
        select(TaskOutbox.status, func.count(TaskOutbox.id)).group_by(TaskOutbox.status)
    )
    for status, count in grouped:
        counts[str(status)] = int(count or 0)

    oldest_unpublished = await db.scalar(
        select(func.min(TaskOutbox.created_at)).where(
            TaskOutbox.status.in_(["pending", "leased"])
        )
    )
    now = utcnow()
    oldest_age = (
        max(0, int((now - oldest_unpublished).total_seconds()))
        if oldest_unpublished is not None
        else 0
    )

    pending_by_type_rows = await db.execute(
        select(TaskOutbox.task_type, func.count(TaskOutbox.id))
        .where(TaskOutbox.status.in_(["pending", "leased"]))
        .group_by(TaskOutbox.task_type)
        .order_by(func.count(TaskOutbox.id).desc())
    )
    pending_by_type = {
        str(task_type): int(count or 0)
        for task_type, count in pending_by_type_rows
    }

    recent_failures_rows = await db.execute(
        select(TaskOutbox)
        .where(TaskOutbox.status == "failed")
        .order_by(TaskOutbox.updated_at.desc(), TaskOutbox.id.desc())
        .limit(10)
    )
    recent_failures: list[dict[str, Any]] = []
    for row in recent_failures_rows.scalars():
        payload = row.payload if isinstance(row.payload, dict) else {}
        trace = payload.get("_trace") if isinstance(payload.get("_trace"), dict) else {}
        recent_failures.append(
            {
                "outbox_id": int(row.id),
                "task_id": row.task_id,
                "task_type": row.task_type,
                "retry_count": int(row.retry_count or 0),
                "last_error": (row.error_message or "")[:300] or None,
                "trace_id": str(trace.get("trace_id") or "") or None,
                "request_id": str(trace.get("request_id") or "") or None,
                "updated_at": serialize_utc_datetime(row.updated_at),
            }
        )

    return {
        "counts": counts,
        "unpublished": counts.get("pending", 0) + counts.get("leased", 0),
        "oldest_unpublished_seconds": oldest_age,
        "oldest_unpublished_at": (
            serialize_utc_datetime(oldest_unpublished)
            if oldest_unpublished is not None
            else None
        ),
        "pending_by_type": pending_by_type,
        "recent_failures": recent_failures,
    }


async def _collect_queue_metrics() -> dict[str, Any]:
    """Collect one consistent-ish Redis snapshot using a pooled client.

    A single connection/pipeline avoids opening dozens of Redis clients through
    the public per-metric helpers.  The diagnostic endpoint is read-only.
    """
    from app.services.task_queue_service import (
        _v2_corrupt_key,
        _v2_dead_key,
        _v2_p_key,
        _v2_q_key,
        _v2_retry_key,
        _v2_task_hash_key,
        task_queue,
    )

    if not settings.REDIS_URL:
        return {
            "configured": False,
            "available": False,
            "error": "redis_not_configured",
            "queues": [],
            "totals": {"ready": 0, "processing": 0, "retry": 0, "dead": 0, "corrupt": 0},
            "oldest_ready_seconds": 0,
        }

    client = None
    try:
        client = await task_queue._get_script_client()
        if client is None:
            raise RuntimeError("redis_client_unavailable")
        await client.ping()

        pipe = client.pipeline(transaction=False)
        for task_type in OBSERVED_TASK_TYPES:
            pipe.llen(_v2_q_key(task_type))
            pipe.zcard(_v2_p_key(task_type))
            pipe.zcard(_v2_retry_key(task_type))
            pipe.llen(_v2_dead_key(task_type))
            pipe.zcard(_v2_corrupt_key(task_type))
            pipe.lindex(_v2_q_key(task_type), 0)
        raw = await pipe.execute()

        rows: list[dict[str, Any]] = []
        oldest_ids: list[tuple[int, str, str]] = []
        totals = {"ready": 0, "processing": 0, "retry": 0, "dead": 0, "corrupt": 0}
        for idx, task_type in enumerate(OBSERVED_TASK_TYPES):
            base = idx * 6
            ready = int(raw[base] or 0)
            processing = int(raw[base + 1] or 0)
            retry = int(raw[base + 2] or 0)
            dead = int(raw[base + 3] or 0)
            corrupt = int(raw[base + 4] or 0)
            oldest_id = raw[base + 5]
            totals["ready"] += ready
            totals["processing"] += processing
            totals["retry"] += retry
            totals["dead"] += dead
            totals["corrupt"] += corrupt
            row = {
                "task_type": task_type,
                "ready": ready,
                "processing": processing,
                "retry": retry,
                "dead": dead,
                "corrupt": corrupt,
                "oldest_ready_seconds": 0,
            }
            rows.append(row)
            if ready and oldest_id:
                oldest_ids.append((idx, task_type, str(oldest_id)))

        if oldest_ids:
            age_pipe = client.pipeline(transaction=False)
            for _, _, task_id in oldest_ids:
                age_pipe.hget(_v2_task_hash_key(task_id), "data")
            age_payloads = await age_pipe.execute()
            now_ts = time.time()
            for item, payload_raw in zip(oldest_ids, age_payloads, strict=False):
                row_index, _, _ = item
                try:
                    payload = json.loads(payload_raw) if payload_raw else {}
                    created_at = float(payload.get("created_at", 0) or 0)
                    if created_at:
                        rows[row_index]["oldest_ready_seconds"] = max(
                            0, int(now_ts - created_at)
                        )
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass

        active_rows = [
            row
            for row in rows
            if row["ready"] + row["processing"] + row["retry"] + row["dead"] + row["corrupt"] > 0
        ]
        oldest_ready = max((row["oldest_ready_seconds"] for row in rows), default=0)
        return {
            "configured": True,
            "available": True,
            "error": None,
            "queues": active_rows,
            "totals": totals,
            "oldest_ready_seconds": oldest_ready,
        }
    except Exception as exc:
        logger.debug("task diagnostics Redis snapshot failed", exc_info=True)
        return {
            "configured": True,
            "available": False,
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            "queues": [],
            "totals": {"ready": 0, "processing": 0, "retry": 0, "dead": 0, "corrupt": 0},
            "oldest_ready_seconds": 0,
        }
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


async def _collect_projection_metrics(db: AsyncSession) -> dict[str, Any]:
    backlog = await get_projection_backlog_metrics(db)
    receipt_total = int(
        await db.scalar(
            select(func.count(AnswerBehavior.id)).where(
                AnswerBehavior.practice_record_id.is_not(None)
            )
        )
        or 0
    )
    repair_since = utcnow() - timedelta(hours=24)
    repairs_24h = int(
        await db.scalar(
            select(func.count(TaskOutbox.id)).where(
                TaskOutbox.task_type == "answer_projection",
                TaskOutbox.task_id.like("answer_projection_repair:%"),
                TaskOutbox.created_at >= repair_since,
            )
        )
        or 0
    )
    return {
        **backlog,
        "projection_receipts_total": receipt_total,
        "repairs_scheduled_24h": repairs_24h,
    }


def _async_runtime_expected() -> bool:
    role = resolve_effective_process_role(
        settings.APP_ENV,
        settings.PROCESS_ROLE,
        settings.LOCAL_ASYNC_RUNTIME_ENABLED,
    )
    env = (settings.APP_ENV or "").strip().lower()
    is_local = env in {"development", "dev", "local", "test", "testing"}
    if is_local and role == "web" and not settings.LOCAL_ASYNC_RUNTIME_ENABLED:
        return False
    return True


async def collect_task_diagnostics(db: AsyncSession) -> dict[str, Any]:
    outbox = await _collect_outbox_metrics(db)
    projection = await _collect_projection_metrics(db)
    redis = await _collect_queue_metrics()
    async_runtime_expected = _async_runtime_expected()
    health = evaluate_task_health(
        outbox=outbox,
        redis=redis,
        projection=projection,
        async_runtime_expected=async_runtime_expected,
    )
    return {
        "generated_at": serialize_utc_datetime(utcnow()),
        "async_runtime_expected": async_runtime_expected,
        "health": health,
        "outbox": outbox,
        "redis": redis,
        "projection": projection,
    }


def _payload_trace(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    reserved = payload.get("_trace")
    trace = reserved if isinstance(reserved, dict) else {}
    trace_id = str(trace.get("trace_id") or payload.get("trace_id") or "") or None
    request_id = str(trace.get("request_id") or payload.get("request_id") or "") or None
    return trace_id, request_id


async def find_trace_tasks(
    db: AsyncSession,
    *,
    trace_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Resolve a trace ID into durable outbox/queue/projection lifecycle rows."""
    bind = db.get_bind()
    matches: list[TaskOutbox] = []
    if bind is not None and bind.dialect.name == "postgresql":
        # Production path: JSONB can resolve a trace directly without scanning
        # unrelated Outbox history.  ``create_outbox`` persists correlation in
        # payload._trace for every HTTP-originated task.
        result = await db.execute(
            select(TaskOutbox)
            .where(TaskOutbox.payload["_trace"]["trace_id"].astext == trace_id)
            .order_by(TaskOutbox.created_at.asc(), TaskOutbox.id.asc())
            .limit(limit)
        )
        matches = list(result.scalars().all())
    else:
        # SQLite/local compatibility: JSON path behaviour varies by driver, so
        # use a bounded recent scan instead of introducing a DB-specific query.
        scan_limit = max(200, min(2000, limit * 20))
        recent = await db.execute(
            select(TaskOutbox)
            .order_by(TaskOutbox.created_at.desc(), TaskOutbox.id.desc())
            .limit(scan_limit)
        )
        for row in recent.scalars():
            row_trace, _ = _payload_trace(row.payload)
            if row_trace == trace_id:
                matches.append(row)
                if len(matches) >= limit:
                    break
        matches.reverse()

    from app.services.task_queue_service import task_queue

    items: list[dict[str, Any]] = []
    redis_available = bool(settings.REDIS_URL)
    for row in matches:
        row_trace, request_id = _payload_trace(row.payload)
        payload = row.payload if isinstance(row.payload, dict) else {}
        practice_record_id = payload.get("practice_record_id")
        projection_receipt_at = None
        if practice_record_id is not None:
            receipt = await db.scalar(
                select(AnswerBehavior.created_at)
                .where(AnswerBehavior.practice_record_id == int(practice_record_id))
                .limit(1)
            )
            if receipt is not None:
                projection_receipt_at = serialize_utc_datetime(receipt)

        queue_state: dict[str, Any] | None = None
        if settings.REDIS_URL:
            try:
                queue_raw = await task_queue.get_task_v2(row.task_id)
                if queue_raw:
                    data = queue_raw.get("data") if isinstance(queue_raw.get("data"), dict) else {}
                    queue_state = {
                        "status": queue_raw.get("status") or data.get("status"),
                        "retry_count": int(queue_raw.get("retry_count") or data.get("retry_count") or 0),
                        "generation": int(queue_raw.get("generation") or data.get("generation") or 0),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                        "last_error": str(queue_raw.get("error") or data.get("error") or "")[:300] or None,
                    }
            except Exception:
                redis_available = False

        items.append(
            {
                "outbox_id": int(row.id),
                "task_id": row.task_id,
                "task_type": row.task_type,
                "trace_id": row_trace,
                "request_id": request_id,
                "outbox_status": row.status,
                "outbox_retry_count": int(row.retry_count or 0),
                "outbox_error": (row.error_message or "")[:300] or None,
                "created_at": serialize_utc_datetime(row.created_at),
                "published_at": serialize_utc_datetime(row.published_at) if row.published_at else None,
                "updated_at": serialize_utc_datetime(row.updated_at),
                "practice_record_id": int(practice_record_id) if practice_record_id is not None else None,
                "projection_receipt_at": projection_receipt_at,
                "queue": queue_state,
            }
        )

    return {
        "trace_id": trace_id,
        "redis_available": redis_available,
        "items": items,
        "total": len(items),
    }


async def run_task_health_monitor() -> None:
    """Emit one log/Sentry event per health-state transition, not per poll."""
    from app.core.database import async_session
    from app.utils.sentry_utils import capture_message

    interval = max(30.0, float(settings.TASK_HEALTH_MONITOR_INTERVAL_SEC))
    await asyncio.sleep(min(30.0, interval))
    last_signature: tuple[str, tuple[str, ...]] | None = None

    while True:
        try:
            async with async_session() as db:
                snapshot = await collect_task_diagnostics(db)
            health = snapshot["health"]
            codes = tuple(sorted(item["code"] for item in health["issues"]))
            signature = (str(health["severity"]), codes)
            if signature != last_signature:
                if health["severity"] == "ok":
                    if last_signature is not None and last_signature[0] != "ok":
                        logger.info("Async task health recovered")
                else:
                    summary = ",".join(codes) or "unknown"
                    log_fn = logger.error if health["severity"] == "error" else logger.warning
                    log_fn("Async task health degraded: severity=%s issues=%s", health["severity"], summary)
                    capture_message(
                        "Async task health degraded",
                        level="error" if health["severity"] == "error" else "warning",
                        tags={
                            "component": "async_tasks",
                            "severity": health["severity"],
                            "issues": summary[:200],
                        },
                    )
                last_signature = signature
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Async task health monitor cycle failed")

        await asyncio.sleep(interval)
