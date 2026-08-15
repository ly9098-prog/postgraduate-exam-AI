"""Reconcile committed practice answers with their derived learning projections.

The transactional outbox guarantees that every *new* answer creates a durable
``answer_projection`` event.  This reconciler is a second safety net for cases
outside that happy path: historical rows created before the outbox rollout,
manual data repair, Redis/task retention gaps, or a task that reached a
terminal queue state without leaving the durable ``AnswerBehavior`` receipt.

The durable receipt is ``AnswerBehavior.practice_record_id``.  Missing receipts
older than a grace period are repaired by creating a new outbox event with a
separate repair task id so Redis's idempotency key for the original task cannot
block recovery.
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
from app.core.time_utils import utcnow
from app.models.answer_behavior import AnswerBehavior
from app.models.practice_record import PracticeRecord
from app.models.task_outbox import TaskOutbox
from app.services.outbox_service import create_outbox

logger = logging.getLogger("postgraduate-ai.answer-projection-reconciler")

_TASK_TYPE = "answer_projection"
_ORIGINAL_TASK_PREFIX = "answer_projection"
_REPAIR_TASK_PREFIX = "answer_projection_repair"
_REPAIR_BUCKET_SEC = 3600


def _repair_task_id(practice_record_id: int, now: datetime) -> str:
    """Return a bounded retry id; at most one repair event is created per hour."""
    bucket = int(now.timestamp()) // _REPAIR_BUCKET_SEC
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


def _payload_wrong_question_projected(outbox: TaskOutbox | None) -> bool:
    """Preserve synchronous wrong-book projection state on repair tasks."""
    if outbox is None or not isinstance(outbox.payload, dict):
        return False
    return bool(outbox.payload.get("wrong_question_projected", False))


async def get_projection_backlog_metrics(
    db: AsyncSession,
    *,
    grace_sec: int | None = None,
    now: datetime | None = None,
) -> dict[str, int | str | None]:
    """Return the durable projection backlog measured from PostgreSQL.

    Queue length alone cannot prove that learning state is complete.  This
    metric intentionally compares the source-of-truth answer rows with the
    durable projection receipt.
    """
    effective_grace = max(
        0,
        int(
            grace_sec
            if grace_sec is not None
            else settings.ANSWER_PROJECTION_RECONCILE_GRACE_SEC
        ),
    )
    current = now or utcnow()
    cutoff = current - timedelta(seconds=effective_grace)

    aggregate = (await db.execute(
        select(
            func.count(PracticeRecord.id),
            func.min(PracticeRecord.answered_at),
        )
        .outerjoin(
            AnswerBehavior,
            AnswerBehavior.practice_record_id == PracticeRecord.id,
        )
        .where(
            AnswerBehavior.id.is_(None),
            PracticeRecord.answered_at <= cutoff,
        )
    )).one()
    count = int(aggregate[0] or 0)
    oldest = aggregate[1]
    oldest_age_sec = (
        max(0, int((current - oldest).total_seconds())) if oldest is not None else 0
    )
    return {
        "unprojected": count,
        "oldest_age_sec": oldest_age_sec,
        "oldest_answered_at": oldest.isoformat() + "Z" if oldest is not None else None,
    }


async def reconcile_answer_projections(
    db: AsyncSession,
    *,
    batch_size: int | None = None,
    grace_sec: int | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Create repair outbox events for stale answers without projection receipts.

    This function only *schedules* repair.  The normal durable queue worker still
    executes :func:`project_practice_answer`, so retries and idempotency remain
    centralized in one path.
    """
    effective_batch = max(
        1,
        int(
            batch_size
            if batch_size is not None
            else settings.ANSWER_PROJECTION_RECONCILE_BATCH_SIZE
        ),
    )
    effective_grace = max(
        0,
        int(
            grace_sec
            if grace_sec is not None
            else settings.ANSWER_PROJECTION_RECONCILE_GRACE_SEC
        ),
    )
    current = now or utcnow()
    cutoff = current - timedelta(seconds=effective_grace)

    query = (
        select(PracticeRecord)
        .outerjoin(
            AnswerBehavior,
            AnswerBehavior.practice_record_id == PracticeRecord.id,
        )
        .where(
            AnswerBehavior.id.is_(None),
            PracticeRecord.answered_at <= cutoff,
        )
        .order_by(PracticeRecord.answered_at.asc(), PracticeRecord.id.asc())
        .limit(effective_batch)
    )
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        query = query.with_for_update(of=PracticeRecord, skip_locked=True)

    records = list((await db.execute(query)).scalars().all())
    stats = {
        "checked": len(records),
        "scheduled": 0,
        "active_original": 0,
        "repair_already_scheduled": 0,
        "races": 0,
        "errors": 0,
    }

    for record in records:
        original_task_id = f"{_ORIGINAL_TASK_PREFIX}:{record.id}"
        original = await db.scalar(
            select(TaskOutbox).where(TaskOutbox.task_id == original_task_id)
        )

        # A not-yet-published original task is still under the normal outbox
        # dispatcher's ownership.  Do not create parallel work for it.
        if original is not None and original.status in {"pending", "leased"}:
            stats["active_original"] += 1
            continue

        repair_task_id = _repair_task_id(record.id, current)
        existing_repair = await db.scalar(
            select(TaskOutbox.id).where(TaskOutbox.task_id == repair_task_id)
        )
        if existing_repair is not None:
            stats["repair_already_scheduled"] += 1
            continue

        payload: dict[str, Any] = {
            "practice_record_id": int(record.id),
            "request_id": _payload_request_id(original),
            # New practice submits persist wrong-book state synchronously.
            # Preserve this marker when replacing a lost/terminal async task so
            # the repair worker does not increment WrongQuestion.review_count
            # for the same answer a second time.
            "wrong_question_projected": _payload_wrong_question_projected(original),
            "reconciliation": {
                "source": "practice_record_without_projection_receipt",
                "original_task_id": original_task_id,
            },
        }
        original_trace = _payload_trace(original)
        if original_trace is not None:
            payload["_trace"] = original_trace
        try:
            # The savepoint contains the unique-key race if two scheduler
            # instances discover the same row before either commits.
            async with db.begin_nested():
                await create_outbox(
                    db,
                    task_id=repair_task_id,
                    task_type=_TASK_TYPE,
                    payload=payload,
                )
            stats["scheduled"] += 1
        except IntegrityError:
            stats["races"] += 1
            logger.debug(
                "answer projection repair raced: record_id=%s task_id=%s",
                record.id,
                repair_task_id,
            )
        except Exception:
            stats["errors"] += 1
            logger.exception(
                "answer projection repair scheduling failed: record_id=%s",
                record.id,
            )

    if records:
        await db.commit()
    else:
        await db.rollback()

    return stats


async def run_answer_projection_reconciler(
    *,
    poll_interval: float | None = None,
    grace_sec: int | None = None,
    batch_size: int | None = None,
) -> None:
    """Periodically reconcile missing answer projections under a Redis lock."""
    from app.core.database import async_session
    from app.core.distributed_lock import DistributedLock

    interval = max(
        30.0,
        float(
            poll_interval
            if poll_interval is not None
            else settings.ANSWER_PROJECTION_RECONCILE_INTERVAL_SEC
        ),
    )
    effective_grace = (
        int(grace_sec)
        if grace_sec is not None
        else settings.ANSWER_PROJECTION_RECONCILE_GRACE_SEC
    )
    effective_batch = (
        int(batch_size)
        if batch_size is not None
        else settings.ANSWER_PROJECTION_RECONCILE_BATCH_SIZE
    )
    lock = DistributedLock("answer-projection-reconcile")

    logger.info(
        "Answer projection reconciler started: interval=%ss grace=%ss batch=%d",
        interval,
        effective_grace,
        effective_batch,
    )

    # Let dispatcher/worker processes settle before the first repair scan.
    try:
        await asyncio.sleep(min(60.0, interval))
        while True:
            try:
                lock_ttl = max(60, int(interval * 0.9))
                renew_interval = max(20, min(60, lock_ttl // 3))
                async with lock.acquire_and_renew(
                    ttl=lock_ttl,
                    renew_interval=renew_interval,
                ) as handle:
                    if handle.is_still_held():
                        async with async_session() as db:
                            stats = await reconcile_answer_projections(
                                db,
                                batch_size=effective_batch,
                                grace_sec=effective_grace,
                            )
                        if stats["checked"] or stats["errors"]:
                            logger.info("Answer projection reconcile cycle: %s", stats)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Answer projection reconcile cycle failed")

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("Answer projection reconciler cancelled")
        raise
