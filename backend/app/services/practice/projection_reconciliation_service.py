"""Repair practice-answer projections that are explicitly left pending.

Projection completeness is represented by ``PracticeRecord.projection_state``.
The reconciler never infers intent from the presence or absence of another
business row; terminal states such as ``revision_only`` are therefore never
mistaken for missing work.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time_utils import (
    normalize_to_naive_utc,
    serialize_utc_datetime,
    unix_timestamp,
    utcnow,
)
from app.models.practice_record import PracticeRecord
from app.models.task_outbox import TaskOutbox
from app.services.outbox_service import create_outbox
from app.services.practice.answer_projection_contract import (
    ANSWER_PROJECTION_TASK_SCHEMA_VERSION,
    ANSWER_PROJECTION_TASK_TYPE,
)
from app.services.practice.projection_reconciliation_runtime import (
    ReconcileCyclePorts,
    reconciler_parameters,
    reconciliation_limits,
    run_projection_reconcile_cycles,
)

logger = logging.getLogger("postgraduate-ai.answer-projection-reconciler")

_TASK_TYPE = ANSWER_PROJECTION_TASK_TYPE
_ORIGINAL_TASK_PREFIX = "answer_projection"
_REPAIR_TASK_PREFIX = "answer_projection_repair"
_REPAIR_BUCKET_SEC = 3600
_PROJECTION_PENDING = "pending"


def _repair_task_id(practice_record_id: int, now: datetime) -> str:
    bucket = int(unix_timestamp(now)) // _REPAIR_BUCKET_SEC
    return f"{_REPAIR_TASK_PREFIX}:{practice_record_id}:{bucket}"


def _payload_request_id(outbox: TaskOutbox | None) -> str | None:
    if outbox is None or not isinstance(outbox.payload, dict):
        return None
    value = outbox.payload.get("request_id")
    return str(value) if value not in (None, "") else None


def _payload_trace(outbox: TaskOutbox | None) -> dict[str, str] | None:
    if outbox is None or not isinstance(outbox.payload, dict):
        return None
    raw = outbox.payload.get("_trace")
    if not isinstance(raw, dict):
        return None
    trace = {
        key: str(raw.get(key))
        for key in ("trace_id", "request_id")
        if raw.get(key) not in (None, "", "-")
    }
    return trace or None


async def get_projection_backlog_metrics(
    db: AsyncSession,
    *,
    grace_sec: int | None = None,
    now: datetime | None = None,
) -> dict[str, int | str | None]:
    effective_grace = max(
        0,
        int(
            grace_sec
            if grace_sec is not None
            else settings.ANSWER_PROJECTION_RECONCILE_GRACE_SEC
        ),
    )
    current = normalize_to_naive_utc(now) if now is not None else utcnow()
    cutoff = current - timedelta(seconds=effective_grace)

    aggregate = (
        await db.execute(
            select(
                func.count(PracticeRecord.id), func.min(PracticeRecord.answered_at)
            ).where(
                PracticeRecord.projection_state == _PROJECTION_PENDING,
                PracticeRecord.answered_at <= cutoff,
            )
        )
    ).one()
    count = int(aggregate[0] or 0)
    oldest = aggregate[1]
    oldest_age_sec = (
        max(0, int((current - oldest).total_seconds())) if oldest is not None else 0
    )
    return {
        "unprojected": count,
        "oldest_age_sec": oldest_age_sec,
        "oldest_answered_at": serialize_utc_datetime(oldest)
        if oldest is not None
        else None,
    }


async def _pending_projection_ids(
    db: AsyncSession,
    cutoff: datetime,
    effective_batch: int,
) -> list[int]:
    # Reconciliation only needs the durable record id.  Do not hydrate the
    # PracticeRecord ORM entity here: unrelated model columns must never become
    # an implicit dependency of the repair scheduler.
    query = (
        select(PracticeRecord.id)
        .where(
            PracticeRecord.projection_state == _PROJECTION_PENDING,
            PracticeRecord.answered_at <= cutoff,
        )
        .order_by(PracticeRecord.answered_at.asc(), PracticeRecord.id.asc())
        .limit(effective_batch)
    )
    # Do not lock practice_records while deciding whether to enqueue a repair.
    # The projection worker deliberately owns that row lock for exactly-once
    # processing. Holding the same rows here while we inspect/create outbox
    # records can delay healthy workers and turn a repair scan into contention.
    # Races are already safe: the terminal projection state is checked again by
    # the worker and task_id uniqueness below deduplicates concurrent schedulers.
    return [int(value) for value in (await db.execute(query)).scalars().all()]


async def _create_projection_repair(
    db: AsyncSession,
    record_id: int,
    repair_task_id: str,
    payload: dict[str, Any],
    stats: dict[str, int],
) -> None:
    """Isolate only the outbox insert with a savepoint; other errors escape."""
    try:
        async with db.begin_nested():
            await create_outbox(
                db,
                task_id=repair_task_id,
                task_type=_TASK_TYPE,
                payload=payload,
                schema_version=ANSWER_PROJECTION_TASK_SCHEMA_VERSION,
            )
        stats["scheduled"] += 1
    except IntegrityError:
        stats["races"] += 1
        logger.debug(
            "answer projection repair raced: record_id=%s task_id=%s",
            record_id,
            repair_task_id,
        )
    except Exception:
        stats["errors"] += 1
        logger.exception(
            "answer projection repair scheduling failed: record_id=%s", record_id
        )


async def _schedule_projection_repair(
    db: AsyncSession,
    record_id: int,
    current: datetime,
    stats: dict[str, int],
) -> None:
    original_task_id = f"{_ORIGINAL_TASK_PREFIX}:{record_id}"
    original = await db.scalar(
        select(TaskOutbox).where(TaskOutbox.task_id == original_task_id)
    )
    if original is not None and original.status in {"pending", "leased"}:
        stats["active_original"] += 1
        return

    repair_task_id = _repair_task_id(record_id, current)
    existing_repair = await db.scalar(
        select(TaskOutbox.id).where(TaskOutbox.task_id == repair_task_id)
    )
    if existing_repair is not None:
        stats["repair_already_scheduled"] += 1
        return

    payload: dict[str, Any] = {
        "practice_record_id": record_id,
        "request_id": _payload_request_id(original),
        "reconciliation": {
            "source": "practice_record_projection_pending",
            "original_task_id": original_task_id,
        },
    }
    original_trace = _payload_trace(original)
    if original_trace is not None:
        payload["_trace"] = original_trace
    await _create_projection_repair(db, record_id, repair_task_id, payload, stats)


async def reconcile_answer_projections(
    db: AsyncSession,
    *,
    batch_size: int | None = None,
    grace_sec: int | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Schedule durable repair tasks only for stale ``pending`` records."""
    effective_batch, effective_grace = reconciliation_limits(
        batch_size,
        grace_sec,
        lambda: settings,
    )
    current = normalize_to_naive_utc(now) if now is not None else utcnow()
    cutoff = current - timedelta(seconds=effective_grace)
    record_ids = await _pending_projection_ids(db, cutoff, effective_batch)
    stats = {
        "checked": len(record_ids),
        "scheduled": 0,
        "active_original": 0,
        "repair_already_scheduled": 0,
        "races": 0,
        "errors": 0,
    }

    for record_id in record_ids:
        await _schedule_projection_repair(db, record_id, current, stats)

    if record_ids:
        await db.commit()
    else:
        await db.rollback()
    return stats


def _reconcile_cycle_ports() -> ReconcileCyclePorts:
    # Resolve module ports at invocation, including changes made between cycles.
    return ReconcileCyclePorts(
        reconcile=lambda *args, **kwargs: reconcile_answer_projections(*args, **kwargs),
        sleep=lambda delay: asyncio.sleep(delay),
        log_info=lambda *args: logger.info(*args),
        log_exception=lambda *args: logger.exception(*args),
    )


async def run_answer_projection_reconciler(
    *,
    poll_interval: float | None = None,
    grace_sec: int | None = None,
    batch_size: int | None = None,
) -> None:
    from app.core.database import async_session
    from app.core.distributed_lock import DistributedLock

    interval, effective_grace, effective_batch = reconciler_parameters(
        poll_interval,
        grace_sec,
        batch_size,
        lambda: settings,
    )
    lock = DistributedLock("answer-projection-reconcile")

    logger.info(
        "Answer projection reconciler started: interval=%ss grace=%ss batch=%d",
        interval,
        effective_grace,
        effective_batch,
    )
    try:
        await asyncio.sleep(min(60.0, interval))
        await run_projection_reconcile_cycles(
            _reconcile_cycle_ports(),
            async_session,
            lock,
            interval,
            effective_grace,
            effective_batch,
        )
    except asyncio.CancelledError:
        logger.info("Answer projection reconciler cancelled")
        raise
