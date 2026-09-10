"""Transactional outbox service — DB→Redis task consistency.

This service implements the transactional outbox pattern:

1. **Write phase**: Business logic creates a ``TaskOutbox`` row in the same
   PostgreSQL transaction as the business record (import batch, pipeline, etc.).
   The outbox row is only visible if the transaction commits.

2. **Dispatch phase**: A background dispatcher selects pending outbox rows using
   ``FOR UPDATE SKIP LOCKED``, enqueues them to Redis v2 queue, and marks them
   as ``published``.

3. **Reconciliation phase**: A periodic reconciler detects drift between DB
   outbox state and Redis task state, fixing inconsistencies.

Semantics
---------
- At-least-once delivery to Redis (idempotent keys prevent duplicates)
- Effectively-once business side effects via fencing + unique constraints
- Outbox is the authoritative source of "tasks that should exist"
- Redis is the authoritative source of "task execution state"
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.task_outbox import TaskOutbox
from app.services.outbox_runtime import (
    REDIS_BACKOFF_INITIAL_SEC,
    is_redis_infrastructure_exception,
    next_redis_backoff,
)

logger = logging.getLogger("postgraduate-ai.outbox")

# ── Constants ──

_OUTBOX_LEASE_SEC = 120  # 2 min lease for dispatcher claim
_OUTBOX_RETRY_DELAY_SEC = 60  # retry failed publishes after 60s
_OUTBOX_BATCH_SIZE = 20  # max outbox records per claim batch
_OUTBOX_RETENTION_DAYS = 7  # purge published rows after 7 days
_OUTBOX_MAX_RETRIES = 10  # max publish attempts before permanent failure
_RECONCILE_BATCH_SIZE = 50  # max records to reconcile per cycle


class OutboxContractError(ValueError):
    """Deterministic task-envelope error that retrying cannot repair."""


def _normalize_outbox_contract(
    task_type: str,
    payload: dict[str, Any],
    schema_version: int | None,
) -> int:
    """Validate an Outbox task contract and return its persisted schema version.

    The generic Outbox historically defaulted to schema v1.  Answer projection
    moved to a stricter v2 worker contract, but a short-lived producer version
    still emitted the current per-answer payload under a v1 envelope.  Upgrade
    only that validated payload shape; never reinterpret retired batch payloads.
    """
    try:
        version = 1 if schema_version is None else int(schema_version)
    except (TypeError, ValueError) as exc:
        raise OutboxContractError("schema_version must be an integer") from exc
    if version <= 0:
        raise OutboxContractError("schema_version must be positive")

    if task_type == "answer_projection":
        from app.services.practice.answer_projection_contract import (
            normalize_answer_projection_outbox_schema,
        )

        try:
            return normalize_answer_projection_outbox_schema(payload, version)
        except ValueError as exc:
            raise OutboxContractError(str(exc)) from exc
    return version


# ── Outbox Service ──


async def create_outbox(
    db: AsyncSession,
    task_id: str,
    task_type: str,
    payload: dict[str, Any],
    schema_version: int | None = None,
) -> TaskOutbox:
    """Create a pending outbox record.

    Call this **within the same DB transaction** as the business record
    creation. If the transaction rolls back, the outbox record is also
    rolled back — guaranteeing consistency.

    Raises:
        ValueError: If the task contract is invalid or a non-terminal outbox
            record already exists for this task_id.
    """
    effective_schema_version = _normalize_outbox_contract(
        task_type, payload, schema_version,
    )

    # Idempotent check: skip if already published
    existing = await db.execute(
        select(TaskOutbox).where(
            and_(
                TaskOutbox.task_id == task_id,
                TaskOutbox.status.in_(["pending", "leased", "published"]),
            )
        )
    )
    existing_row = existing.scalar_one_or_none()
    if existing_row is not None:
        if existing_row.status == "published":
            logger.debug(
                "Outbox already published, skipping: task_id=%s", task_id,
            )
            return existing_row
        raise ValueError(
            f"Non-terminal outbox record exists for task_id={task_id} "
            f"status={existing_row.status}"
        )

    # Persist correlation metadata with the transactional outbox record. The
    # dispatcher runs in another background task/process, so ContextVar state
    # from the originating HTTP request is otherwise unavailable at publish time.
    persisted_payload = dict(payload)
    try:
        from app.core.log_context import get_log_context

        ctx = get_log_context()
        trace_meta = {
            key: str(ctx.get(key))
            for key in ("trace_id", "request_id")
            if ctx.get(key) not in (None, "", "-")
        }
        if trace_meta and "_trace" not in persisted_payload:
            persisted_payload["_trace"] = trace_meta
    except Exception:
        pass

    outbox = TaskOutbox(
        task_id=task_id,
        task_type=task_type,
        payload=persisted_payload,
        schema_version=effective_schema_version,
        status="pending",
    )
    db.add(outbox)
    await db.flush()  # Get the ID assigned but caller still controls commit
    logger.info("Outbox created: task_id=%s type=%s id=%d", task_id, task_type, outbox.id)
    return outbox


async def claim_pending(
    db: AsyncSession,
    batch_size: int = _OUTBOX_BATCH_SIZE,
    task_types: list[str] | None = None,
    lease_sec: int = _OUTBOX_LEASE_SEC,
) -> list[TaskOutbox]:
    """Claim pending outbox records using FOR UPDATE SKIP LOCKED.

    This is safe for multiple dispatcher processes — SKIP LOCKED ensures
    each record is claimed by at most one dispatcher.

    Args:
        db: DB session (autocommit must be False — we do our own commit)
        batch_size: Max records to claim.
        task_types: Optional filter by task type.
        lease_sec: Lease duration in seconds.

    Returns:
        List of claimed outbox records (status set to ``leased``).
    """
    now = utcnow()
    retry_cutoff = now - timedelta(seconds=_OUTBOX_RETRY_DELAY_SEC)
    claimable_state = or_(
        TaskOutbox.status == "pending",
        and_(
            TaskOutbox.status == "leased",
            or_(
                TaskOutbox.lease_expires_at.is_(None),
                TaskOutbox.lease_expires_at < now,
            ),
        ),
    )
    retry_ready = or_(
        TaskOutbox.retry_count == 0,
        TaskOutbox.updated_at <= retry_cutoff,
    )

    # Filter claimability in SQL *before* LIMIT.  The previous query selected
    # unexpired leased rows and discarded them in Python, so enough old active
    # leases could starve newer pending work for an entire lease window.
    query = (
        select(TaskOutbox)
        .where(
            and_(
                claimable_state,
                TaskOutbox.retry_count < _OUTBOX_MAX_RETRIES,
                retry_ready,
            )
        )
        .order_by(TaskOutbox.created_at.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )

    if task_types:
        query = query.where(TaskOutbox.task_type.in_(task_types))

    result = await db.execute(query)
    rows = list(result.scalars().all())

    lease_expiry = now + timedelta(seconds=lease_sec)

    claimed: list[TaskOutbox] = []
    for row in rows:
        # Only claim pending OR expired-lease records
        if row.status == "pending":
            row.status = "leased"
            row.lease_token = f"lease_{row.id}_{uuid4().hex}"
            row.lease_expires_at = lease_expiry
            claimed.append(row)
        elif row.status == "leased" and (
            row.lease_expires_at is None or row.lease_expires_at < now
        ):
            # Lease expiry is a dispatcher/process failure, not a business
            # publish rejection.  Reclaim it without consuming finite retry
            # budget; Redis task IDs make a post-crash re-publish idempotent.
            row.lease_token = f"lease_{row.id}_{uuid4().hex}"
            row.lease_expires_at = lease_expiry
            row.error_message = "lease expired, reclaimed"
            claimed.append(row)

    if claimed:
        await db.commit()
        logger.debug("Outbox claimed: %d records", len(claimed))
    else:
        await db.rollback()

    return claimed


async def mark_published(
    db: AsyncSession,
    outbox_id: int,
    task_id: str,
    lease_token: str,
) -> bool:
    """Mark the currently leased outbox record as published.

    The lease token is a fencing token.  A dispatcher that finishes after its
    lease expired must not overwrite a row already reclaimed by another worker.
    """
    now = utcnow()
    result = await db.execute(
        update(TaskOutbox)
        .where(
            TaskOutbox.id == outbox_id,
            TaskOutbox.task_id == task_id,
            TaskOutbox.status == "leased",
            TaskOutbox.lease_token == lease_token,
        )
        .values(
            status="published",
            published_at=now,
            lease_token=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    await db.commit()
    updated = bool(result.rowcount)
    if updated:
        logger.debug("Outbox published: id=%d task_id=%s", outbox_id, task_id)
    else:
        logger.info(
            "Outbox publish result ignored after lease loss: id=%d task_id=%s",
            outbox_id, task_id,
        )
    return updated


async def mark_failed(
    db: AsyncSession,
    outbox_id: int,
    task_id: str,
    error: str,
    lease_token: str,
) -> bool:
    """Mark the currently leased outbox record as permanently failed."""
    now = utcnow()
    result = await db.execute(
        update(TaskOutbox)
        .where(
            TaskOutbox.id == outbox_id,
            TaskOutbox.task_id == task_id,
            TaskOutbox.status == "leased",
            TaskOutbox.lease_token == lease_token,
        )
        .values(
            status="failed",
            error_message=error[:500],
            lease_token=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    await db.commit()
    updated = bool(result.rowcount)
    if updated:
        logger.warning(
            "Outbox failed: id=%d task_id=%s error=%s",
            outbox_id, task_id, error[:200],
        )
    else:
        logger.info(
            "Outbox failure result ignored after lease loss: id=%d task_id=%s",
            outbox_id, task_id,
        )
    return updated


async def mark_retryable(
    db: AsyncSession,
    outbox_id: int,
    task_id: str,
    error: str,
    lease_token: str,
) -> bool:
    """Return a transient publish failure to ``pending`` for later dispatch.

    Only the dispatcher that still owns ``lease_token`` may mutate the row.
    Redis/infrastructure failures use :func:`release_infrastructure_failure` and
    do not consume this finite retry budget.  The return value is ``True`` only
    when the matching lease was updated and another publish attempt is allowed.
    """
    row = await db.scalar(
        select(TaskOutbox)
        .where(
            TaskOutbox.id == outbox_id,
            TaskOutbox.task_id == task_id,
            TaskOutbox.status == "leased",
            TaskOutbox.lease_token == lease_token,
        )
        .with_for_update()
    )
    if row is None:
        await db.rollback()
        logger.info(
            "Outbox retry result ignored after lease loss: id=%d task_id=%s",
            outbox_id, task_id,
        )
        return False

    row.retry_count = int(row.retry_count or 0) + 1
    row.error_message = error[:500]
    row.lease_token = None
    row.lease_expires_at = None
    row.updated_at = utcnow()
    retryable = row.retry_count < _OUTBOX_MAX_RETRIES
    row.status = "pending" if retryable else "failed"
    await db.commit()

    if retryable:
        logger.warning(
            "Outbox publish retry scheduled: id=%d task_id=%s retry=%d/%d error=%s",
            outbox_id, task_id, row.retry_count, _OUTBOX_MAX_RETRIES, error[:200],
        )
    else:
        logger.error(
            "Outbox publish retries exhausted: id=%d task_id=%s retries=%d error=%s",
            outbox_id, task_id, row.retry_count, error[:200],
        )
    return retryable


async def release_infrastructure_failure(
    db: AsyncSession,
    claimed_rows: list[tuple[int, str, str]],
    error: str,
) -> int:
    """Release still-owned leases after Redis/infrastructure unavailability.

    Each tuple is ``(outbox_id, task_id, lease_token)``.  Fencing all three
    fields prevents a slow dispatcher from releasing a lease that has already
    expired and been reclaimed by another dispatcher.  Infrastructure downtime
    does not consume the finite publish retry budget.
    """
    claims = [
        (int(outbox_id), str(task_id), str(lease_token))
        for outbox_id, task_id, lease_token in claimed_rows
        if lease_token
    ]
    if not claims:
        return 0

    conditions = [
        and_(
            TaskOutbox.id == outbox_id,
            TaskOutbox.task_id == task_id,
            TaskOutbox.status == "leased",
            TaskOutbox.lease_token == lease_token,
        )
        for outbox_id, task_id, lease_token in claims
    ]
    result = await db.execute(
        update(TaskOutbox)
        .where(or_(*conditions))
        .values(
            status="pending",
            lease_token=None,
            lease_expires_at=None,
            error_message=error[:500],
            updated_at=utcnow(),
        )
    )
    await db.commit()
    return int(result.rowcount or 0)


async def retry_failed_outbox(db: AsyncSession, outbox_id: int) -> TaskOutbox | None:
    """Reset a permanently failed Outbox row back to ``pending`` for admin repair.

    This does not enqueue directly; the normal dispatcher owns publication so
    Redis idempotency and infrastructure backoff semantics remain unchanged.
    """
    row = await db.scalar(
        select(TaskOutbox)
        .where(TaskOutbox.id == outbox_id)
        .with_for_update()
    )
    if row is None or row.status != "failed":
        await db.rollback()
        return None

    row.status = "pending"
    row.retry_count = 0
    row.error_message = None
    row.lease_token = None
    row.lease_expires_at = None
    row.updated_at = utcnow()
    await db.commit()
    logger.info("Outbox admin retry scheduled: id=%d task_id=%s", row.id, row.task_id)
    return row


async def _persist_schema_upgrade(
    db: AsyncSession,
    *,
    outbox_id: int,
    task_id: str,
    schema_version: int,
    lease_token: str,
) -> bool:
    """Persist a safe envelope upcast while the dispatcher owns the lease."""
    result = await db.execute(
        update(TaskOutbox)
        .where(
            TaskOutbox.id == outbox_id,
            TaskOutbox.task_id == task_id,
            TaskOutbox.status == "leased",
            TaskOutbox.lease_token == lease_token,
        )
        .values(schema_version=schema_version, updated_at=utcnow())
    )
    await db.commit()
    return bool(result.rowcount)


async def recover_legacy_answer_projection_outbox(
    db: AsyncSession,
    *,
    limit: int = _RECONCILE_BATCH_SIZE,
) -> int:
    """Recover answer projections poisoned by the historical v1 publisher.

    Usually these rows still carry ``schema_version=1``. During a rolling deploy,
    however, a migration can safely upcast the durable row while an older
    dispatcher still holds an in-memory v1 snapshot; that stale owner may then
    write the old deterministic failure after the durable envelope is already v2.
    Both states are repaired here. Active leases are never stolen. Retired batch
    payloads remain terminal and are regenerated from ``practice_records`` by the
    business projection reconciler instead of being guessed.
    """
    rows = list((await db.execute(
        select(TaskOutbox)
        .where(
            TaskOutbox.task_type == "answer_projection",
            TaskOutbox.schema_version.in_([1, 2]),
            or_(
                TaskOutbox.status.in_(["failed", "pending"]),
                and_(
                    TaskOutbox.status == "leased",
                    or_(
                        TaskOutbox.lease_expires_at.is_(None),
                        TaskOutbox.lease_expires_at < utcnow(),
                    ),
                ),
            ),
            TaskOutbox.error_message.is_not(None),
            func.lower(TaskOutbox.error_message).like(
                "%unsupported answer_projection schema_version=%"
            ),
        )
        .order_by(TaskOutbox.updated_at.asc(), TaskOutbox.id.asc())
        .limit(max(1, int(limit)))
        .with_for_update(skip_locked=True)
    )).scalars().all())

    if not rows:
        await db.rollback()
        return 0

    now = utcnow()
    recovered = 0
    for row in rows:
        try:
            schema_version = _normalize_outbox_contract(
                row.task_type, row.payload, int(row.schema_version or 1),
            )
        except OutboxContractError:
            logger.error(
                "Legacy answer_projection Outbox payload is not upgradeable: id=%d task_id=%s",
                row.id, row.task_id,
            )
            continue
        # Reset the poisoned state even when the durable row was already
        # upcast to v2 by a migration before a stale v1 lease owner failed it.
        row.schema_version = schema_version
        row.status = "pending"
        row.retry_count = 0
        row.error_message = None
        row.lease_token = None
        row.lease_expires_at = None
        row.updated_at = now
        recovered += 1

    if recovered:
        await db.commit()
        logger.warning(
            "Recovered %d legacy answer_projection Outbox rows by safe schema upcast",
            recovered,
        )
    else:
        await db.rollback()
    return recovered


async def finalize_exhausted_nonterminal_outbox(
    db: AsyncSession,
    *,
    limit: int = _RECONCILE_BATCH_SIZE,
) -> int:
    """Terminalize legacy rows that can no longer be claimed.

    Older dispatcher versions could leave ``pending``/``leased`` rows at or
    above the retry ceiling. ``claim_pending`` correctly refuses to execute
    them, but without this invariant repair they remain permanently
    *unpublished* and keep the task health monitor in a stalled state forever.
    """
    rows = list((await db.execute(
        select(TaskOutbox)
        .where(
            or_(
                TaskOutbox.status == "pending",
                and_(
                    TaskOutbox.status == "leased",
                    or_(
                        TaskOutbox.lease_expires_at.is_(None),
                        TaskOutbox.lease_expires_at < utcnow(),
                    ),
                ),
            ),
            TaskOutbox.retry_count >= _OUTBOX_MAX_RETRIES,
        )
        .order_by(TaskOutbox.updated_at.asc(), TaskOutbox.id.asc())
        .limit(max(1, int(limit)))
        .with_for_update(skip_locked=True)
    )).scalars().all())

    if not rows:
        await db.rollback()
        return 0

    now = utcnow()
    for row in rows:
        previous_error = str(row.error_message or "").strip()
        suffix = f"retry budget exhausted ({int(row.retry_count or 0)}/{_OUTBOX_MAX_RETRIES})"
        row.status = "failed"
        row.error_message = (
            f"{previous_error}; {suffix}" if previous_error else suffix
        )[:500]
        row.lease_token = None
        row.lease_expires_at = None
        row.updated_at = now

    await db.commit()
    logger.error(
        "Terminalized %d exhausted non-terminal Outbox rows",
        len(rows),
    )
    return len(rows)


async def recover_infrastructure_failed_outbox(
    db: AsyncSession,
    *,
    limit: int = _RECONCILE_BATCH_SIZE,
) -> int:
    """Recover legacy rows that were permanently failed only by a Redis outage.

    Current dispatcher code already treats ``redis_unavailable`` as an
    infrastructure pause and returns claimed rows to ``pending`` without
    consuming retry budget.  Older deployments may still contain ``failed``
    rows whose last error is only ``enqueue rejected: redis_unavailable`` (or
    the equivalent Redis-unavailable exception text).  Once Redis is healthy,
    these rows are safe to re-publish because task IDs are idempotent and
    business consumers are designed for at-least-once delivery.

    The caller must only invoke this after a successful Redis health probe.
    """
    rows = list((await db.execute(
        select(TaskOutbox)
        .where(
            TaskOutbox.status == "failed",
            TaskOutbox.error_message.is_not(None),
            or_(
                func.lower(TaskOutbox.error_message).like("%redis_unavailable%"),
                func.lower(TaskOutbox.error_message).like("%redis unavailable%"),
            ),
        )
        .order_by(TaskOutbox.updated_at.asc(), TaskOutbox.id.asc())
        .limit(max(1, int(limit)))
        .with_for_update(skip_locked=True)
    )).scalars().all())

    if not rows:
        await db.rollback()
        return 0

    now = utcnow()
    for row in rows:
        row.status = "pending"
        row.retry_count = 0
        row.error_message = None
        row.lease_token = None
        row.lease_expires_at = None
        row.updated_at = now

    await db.commit()
    logger.warning(
        "Recovered %d legacy Outbox rows failed only by Redis unavailability",
        len(rows),
    )
    return len(rows)


async def mark_cancelled(
    db: AsyncSession, task_id: str,
) -> bool:
    """Mark an outbox record as cancelled.

    Returns True if a record was found and updated.
    """
    result = await db.execute(
        update(TaskOutbox)
        .where(
            and_(
                TaskOutbox.task_id == task_id,
                TaskOutbox.status.in_(["pending", "leased"]),
            )
        )
        .values(
            status="cancelled",
            error_message="cancelled by admin",
            updated_at=utcnow(),
        )
    )
    await db.commit()
    updated = result.rowcount or 0
    if updated:
        logger.info("Outbox cancelled: task_id=%s", task_id)
    return updated > 0


async def purge_old(db: AsyncSession, retention_days: int = _OUTBOX_RETENTION_DAYS) -> int:
    """Delete published/failed/cancelled outbox records older than retention."""
    cutoff = utcnow() - timedelta(days=retention_days)
    result = await db.execute(
        delete(TaskOutbox).where(
            and_(
                TaskOutbox.status.in_(["published", "failed", "cancelled"]),
                TaskOutbox.updated_at < cutoff,
            )
        )
    )
    await db.commit()
    deleted = result.rowcount or 0
    if deleted:
        logger.info("Outbox purge: removed %d records older than %d days", deleted, retention_days)
    return deleted


async def reconcile(db: AsyncSession, task_queue: Any, batch_size: int = _RECONCILE_BATCH_SIZE) -> dict[str, int]:
    """Reconcile DB outbox state with Redis task state.

    Redis task hashes can expire before the Outbox retention window.  A
    surviving v2 idempotency key is therefore treated as proof that the task
    was accepted and must not be republished merely because its hash expired.
    All transitions from ``leased`` are fenced by the observed lease token so
    this reconciler cannot overwrite a lease reclaimed concurrently.
    """
    stats = {
        "checked": 0,
        "fixed_publish": 0,
        "fixed_status": 0,
        "recovered_infra_failed": 0,
        "recovered_contract_failed": 0,
        "finalized_exhausted": 0,
        "errors": 0,
    }

    # PostgreSQL-only repairs remain safe even when Redis is unavailable.
    try:
        stats["recovered_contract_failed"] = await recover_legacy_answer_projection_outbox(
            db, limit=batch_size,
        )
    except Exception as exc:
        stats["errors"] += 1
        logger.warning("Legacy answer_projection Outbox recovery failed: %s", exc)

    try:
        stats["finalized_exhausted"] = await finalize_exhausted_nonterminal_outbox(
            db, limit=batch_size,
        )
    except Exception as exc:
        stats["errors"] += 1
        logger.warning("Exhausted Outbox invariant repair failed: %s", exc)

    # ``None`` means missing only after Redis reachability is established.
    try:
        await task_queue.get_task_v2("__outbox_reconcile_health_probe__")
    except Exception as exc:
        logger.debug("Outbox reconcile Redis probe unavailable: %s", exc)
        return stats

    try:
        stats["recovered_infra_failed"] = await recover_infrastructure_failed_outbox(
            db, limit=batch_size,
        )
    except Exception as exc:
        stats["errors"] += 1
        logger.warning("Legacy Redis-outage Outbox recovery failed: %s", exc)

    # Never resurrect rows that are already beyond the Outbox retention horizon.
    # They are purge candidates, and the Redis idempotency tombstone may expire at
    # roughly the same age.  Excluding them closes that boundary race.
    retention_cutoff = utcnow() - timedelta(days=_OUTBOX_RETENTION_DAYS)
    result = await db.execute(
        select(TaskOutbox)
        .where(
            or_(
                TaskOutbox.status == "leased",
                and_(
                    TaskOutbox.status == "published",
                    TaskOutbox.updated_at >= retention_cutoff,
                ),
            )
        )
        .order_by(TaskOutbox.updated_at.asc())
        .limit(batch_size)
    )
    rows = list(result.scalars().all())

    for row in rows:
        stats["checked"] += 1
        observed_status = str(row.status or "")
        observed_lease_token = str(row.lease_token or "")
        try:
            task_data = await task_queue.get_task_v2(row.task_id)
        except Exception as exc:
            stats["errors"] += 1
            logger.debug(
                "Outbox reconcile Redis lookup unavailable: task_id=%s error=%s",
                row.task_id, exc,
            )
            continue

        try:
            if observed_status == "leased":
                if task_data is None:
                    # The normal claim path owns retry once this lease expires.
                    continue

                # Redis already accepted the task. Fence this transition against
                # an expired lease being reclaimed while the Redis lookup ran.
                now = utcnow()
                update_result = await db.execute(
                    update(TaskOutbox)
                    .where(
                        TaskOutbox.id == row.id,
                        TaskOutbox.task_id == row.task_id,
                        TaskOutbox.status == "leased",
                        TaskOutbox.lease_token == observed_lease_token,
                    )
                    .values(
                        status="published",
                        published_at=now,
                        lease_token=None,
                        lease_expires_at=None,
                        updated_at=now,
                    )
                )
                await db.commit()
                if update_result.rowcount:
                    stats["fixed_publish"] += 1
                    logger.info(
                        "Reconcile: outbox leased→published (Redis has task): task_id=%s",
                        row.task_id,
                    )
                else:
                    logger.debug(
                        "Reconcile leased→published skipped after lease changed: task_id=%s",
                        row.task_id,
                    )
                continue

            if observed_status == "published" and task_data is None:
                # A completed task hash expires after one day, while its
                # idempotency guard survives much longer.  That is normal and
                # must not cause permanent published↔pending churn.
                try:
                    idempotency_exists = await task_queue.has_idempotency_v2(row.task_id)
                except Exception as exc:
                    stats["errors"] += 1
                    logger.debug(
                        "Outbox reconcile idempotency lookup unavailable: task_id=%s error=%s",
                        row.task_id, exc,
                    )
                    continue
                if idempotency_exists:
                    continue

                # Redis is reachable and has neither task state nor its acceptance
                # tombstone. Only a still-published row may be returned to pending.
                update_result = await db.execute(
                    update(TaskOutbox)
                    .where(
                        TaskOutbox.id == row.id,
                        TaskOutbox.task_id == row.task_id,
                        TaskOutbox.status == "published",
                        TaskOutbox.updated_at >= retention_cutoff,
                    )
                    .values(
                        status="pending",
                        lease_token=None,
                        lease_expires_at=None,
                        updated_at=utcnow(),
                    )
                )
                await db.commit()
                if update_result.rowcount:
                    stats["fixed_publish"] += 1
                    logger.warning(
                        "Reconcile: outbox published→pending (Redis lost task and idempotency guard): task_id=%s",
                        row.task_id,
                    )

        except Exception as exc:
            stats["errors"] += 1
            await db.rollback()
            logger.warning("Reconcile error for task_id=%s: %s", row.task_id, exc)

    if stats["checked"] > 0:
        logger.info("Outbox reconcile: %s", stats)

    return stats


async def count_pending(db: AsyncSession, task_type: str | None = None) -> int:
    """Count pending (unpublished) outbox records."""
    conditions = [TaskOutbox.status == "pending"]
    if task_type:
        conditions.append(TaskOutbox.task_type == task_type)
    result = await db.execute(
        select(func.count(TaskOutbox.id)).where(and_(*conditions))
    )
    return result.scalar() or 0


async def get_outbox_metrics(db: AsyncSession) -> dict[str, int]:
    """Return outbox metrics: counts by status."""
    result = await db.execute(
        select(
            TaskOutbox.status,
            func.count(TaskOutbox.id).label("count"),
        ).group_by(TaskOutbox.status)
    )
    counts: dict[str, int] = {"pending": 0, "leased": 0, "published": 0, "failed": 0, "cancelled": 0}
    for row in result:
        counts[row.status] = row.count
    return counts


# ══════════════════════════════════════════════════════════════════
# Background Dispatcher
# ══════════════════════════════════════════════════════════════════

_outbox_dispatcher_running = False
_outbox_dispatcher_draining = False


async def run_outbox_dispatcher(
    enqueue_fn: Callable[[str, str, dict, int], Any],
    poll_interval: float = 5.0,
    batch_size: int = _OUTBOX_BATCH_SIZE,
    lease_sec: int = _OUTBOX_LEASE_SEC,
) -> None:
    """Background dispatcher: reads pending outbox records and enqueues to Redis.

    Redis unavailability is handled as an infrastructure pause rather than a
    task failure: claimed rows are released without incrementing retry_count and
    the dispatcher waits with bounded exponential backoff for as long as Redis
    remains unavailable.  A Redis outage therefore cannot permanently fail
    otherwise-valid business tasks.
    """
    global _outbox_dispatcher_running, _outbox_dispatcher_draining
    if _outbox_dispatcher_running:
        logger.warning("Outbox dispatcher already running; duplicate start ignored")
        return
    # ``stop_outbox_dispatcher`` is a one-run drain signal, not permanent process
    # state. Reset it so scheduler/worker restart inside the same process works.
    _outbox_dispatcher_draining = False
    _outbox_dispatcher_running = True

    from app.core.database import async_session

    logger.info("Outbox dispatcher started: poll_interval=%ss batch_size=%d", poll_interval, batch_size)
    redis_backoff = REDIS_BACKOFF_INITIAL_SEC
    redis_paused = False
    redis_pause_started = None

    try:
        while _outbox_dispatcher_running and not _outbox_dispatcher_draining:
            try:
                async with async_session() as db:
                    claimed = await claim_pending(
                        db, batch_size=batch_size, lease_sec=lease_sec,
                    )

                retry_pause = 0.0
                transient_reasons = {
                    "queue_full",
                    "internal_error",
                    "enqueue_failed",
                }
                infrastructure_paused_this_cycle = False

                for index, outbox in enumerate(claimed):
                    try:
                        effective_schema_version = _normalize_outbox_contract(
                            outbox.task_type,
                            outbox.payload,
                            int(outbox.schema_version or 1),
                        )
                        if effective_schema_version != int(outbox.schema_version or 1):
                            async with async_session() as schema_db:
                                upgraded = await _persist_schema_upgrade(
                                    schema_db,
                                    outbox_id=outbox.id,
                                    task_id=outbox.task_id,
                                    schema_version=effective_schema_version,
                                    lease_token=str(outbox.lease_token or ""),
                                )
                            if not upgraded:
                                logger.info(
                                    "Outbox schema upgrade lost lease; deferring: task_id=%s",
                                    outbox.task_id,
                                )
                                continue
                            logger.warning(
                                "Outbox schema safely upgraded before publish: task_id=%s type=%s %s->%s",
                                outbox.task_id,
                                outbox.task_type,
                                outbox.schema_version,
                                effective_schema_version,
                            )

                        async with async_session() as publish_db:
                            result = await enqueue_fn(
                                outbox.task_id,
                                outbox.task_type,
                                outbox.payload,
                                effective_schema_version,
                            )
                            if result and result.accepted:
                                await mark_published(
                                    publish_db, outbox.id, outbox.task_id,
                                    str(outbox.lease_token or ""),
                                )
                                if redis_paused:
                                    paused_for = 0.0
                                    if redis_pause_started is not None:
                                        paused_for = max(0.0, asyncio.get_running_loop().time() - redis_pause_started)
                                    logger.info(
                                        "Outbox dispatcher resumed after Redis recovery: paused_for=%.1fs",
                                        paused_for,
                                    )
                                    redis_paused = False
                                    redis_pause_started = None
                                    redis_backoff = REDIS_BACKOFF_INITIAL_SEC
                                logger.debug(
                                    "Outbox dispatched: task_id=%s type=%s reason=%s",
                                    outbox.task_id, outbox.task_type,
                                    getattr(result, "reason", ""),
                                )
                                continue

                            reason = getattr(result, "reason", "unknown")
                            error = f"enqueue rejected: {reason}"
                            if reason == "redis_unavailable":
                                remaining_claims = [
                                    (item.id, item.task_id, str(item.lease_token or ""))
                                    for item in claimed[index:]
                                ]
                                async with async_session() as infra_db:
                                    released = await release_infrastructure_failure(
                                        infra_db, remaining_claims, error,
                                    )
                                if not redis_paused:
                                    redis_paused = True
                                    redis_pause_started = asyncio.get_running_loop().time()
                                    logger.warning(
                                        "Outbox dispatcher paused: reason=redis_unavailable "
                                        "released=%d backoff=%.1fs (retry budget preserved)",
                                        released,
                                        redis_backoff,
                                    )
                                else:
                                    logger.debug(
                                        "Redis still unavailable: released=%d backoff=%.1fs",
                                        released,
                                        redis_backoff,
                                    )
                                infrastructure_paused_this_cycle = True
                                break

                            if reason in transient_reasons:
                                await mark_retryable(
                                    publish_db, outbox.id, outbox.task_id, error,
                                    str(outbox.lease_token or ""),
                                )
                                retry_pause = max(
                                    retry_pause,
                                    float(getattr(result, "retry_after", 0) or poll_interval),
                                )
                            else:
                                await mark_failed(
                                    publish_db, outbox.id, outbox.task_id, error,
                                    str(outbox.lease_token or ""),
                                )
                    except (OutboxContractError, ValueError) as e:
                        # Payload/schema validation is deterministic. Repeating
                        # it cannot recover, so fail once instead of burning the
                        # retry budget and flooding diagnostics.
                        logger.error(
                            "Outbox permanent contract error: task_id=%s error=%s",
                            outbox.task_id, e,
                        )
                        try:
                            async with async_session() as invalid_db:
                                await mark_failed(
                                    invalid_db,
                                    outbox.id,
                                    outbox.task_id,
                                    f"dispatcher contract error: {type(e).__name__}: {e}",
                                    str(outbox.lease_token or ""),
                                )
                        except Exception:
                            logger.exception(
                                "Outbox permanent-failure state update failed: task_id=%s",
                                outbox.task_id,
                            )
                    except Exception as e:
                        if is_redis_infrastructure_exception(e):
                            error = f"redis unavailable: {type(e).__name__}: {e}"
                            remaining_claims = [
                                (item.id, item.task_id, str(item.lease_token or ""))
                                for item in claimed[index:]
                            ]
                            try:
                                async with async_session() as infra_db:
                                    released = await release_infrastructure_failure(
                                        infra_db, remaining_claims, error,
                                    )
                                if not redis_paused:
                                    redis_paused = True
                                    redis_pause_started = asyncio.get_running_loop().time()
                                    logger.warning(
                                        "Outbox dispatcher paused: reason=redis_unavailable "
                                        "released=%d backoff=%.1fs (retry budget preserved)",
                                        released,
                                        redis_backoff,
                                    )
                                else:
                                    logger.debug(
                                        "Redis still unavailable: released=%d backoff=%.1fs",
                                        released,
                                        redis_backoff,
                                    )
                                infrastructure_paused_this_cycle = True
                                break
                            except Exception:
                                logger.exception("Outbox infrastructure release failed")
                                retry_pause = max(retry_pause, poll_interval)
                                continue

                        logger.warning(
                            "Outbox dispatch error: task_id=%s error=%s",
                            outbox.task_id, e,
                        )
                        try:
                            async with async_session() as retry_db:
                                await mark_retryable(
                                    retry_db, outbox.id, outbox.task_id,
                                    f"dispatcher exception: {type(e).__name__}: {e}",
                                    str(outbox.lease_token or ""),
                                )
                            retry_pause = max(retry_pause, poll_interval)
                        except Exception:
                            logger.exception(
                                "Outbox retry state update failed: task_id=%s",
                                outbox.task_id,
                            )

                if infrastructure_paused_this_cycle:
                    await asyncio.sleep(redis_backoff)
                    redis_backoff = next_redis_backoff(redis_backoff)
                elif retry_pause > 0:
                    await asyncio.sleep(min(60.0, max(poll_interval, retry_pause)))
                elif not claimed:
                    await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Outbox dispatcher cycle error: %s", e)
                await asyncio.sleep(poll_interval * 2)

    except asyncio.CancelledError:
        logger.info("Outbox dispatcher cancelled")
        raise
    finally:
        _outbox_dispatcher_running = False
        logger.info("Outbox dispatcher stopped")


async def stop_outbox_dispatcher() -> None:
    """Signal the outbox dispatcher to stop after current cycle."""
    global _outbox_dispatcher_draining
    _outbox_dispatcher_draining = True
    logger.info("Outbox dispatcher draining requested")


async def run_outbox_reconciler(
    poll_interval: float = 300.0,
    batch_size: int = _RECONCILE_BATCH_SIZE,
) -> None:
    """Background reconciler: fixes drift between DB outbox and Redis state.

    Runs every 5 minutes by default. Designed for the scheduler role.
    """
    from app.core.database import async_session
    from app.services.task_queue_service import task_queue

    logger.info("Outbox reconciler started: poll_interval=%ss", poll_interval)

    try:
        # Reconciliation is an independent scheduler safety net.  Do not couple
        # its lifetime to an in-process dispatcher flag: scheduler/worker roles
        # can start tasks in either order, and a dispatcher restart must not
        # silently disable contract recovery, state repair, or Redis drift checks.
        # TaskRegistry cancellation owns shutdown.
        while True:
            await asyncio.sleep(poll_interval)
            try:
                async with async_session() as db:
                    stats = await reconcile(db, task_queue, batch_size=batch_size)
                    if stats["checked"] > 0 or stats["errors"] > 0:
                        logger.info("Outbox reconcile cycle: %s", stats)

                # Purge old records
                async with async_session() as purge_db:
                    purged = await purge_old(purge_db)
                    if purged:
                        logger.info("Outbox purge: %d records removed", purged)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Outbox reconciler error: %s", e)

    except asyncio.CancelledError:
        logger.info("Outbox reconciler cancelled")
        raise


async def replay_dead_letter(
    db: AsyncSession,
    outbox_id: int,
) -> TaskOutbox | None:
    """Move one dead/failed outbox item back to pending safely.

    The operation is idempotent: repeated admin retries only create one
    executable lifecycle and never duplicate the task identity.
    """
    result = await db.execute(
        select(TaskOutbox).where(TaskOutbox.id == outbox_id).with_for_update()
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if row.status in ("pending", "leased", "published"):
        return row
    row.status = "pending"
    row.retry_count = 0
    row.error_message = None
    row.lease_token = None
    row.lease_expires_at = None
    await db.flush()
    return row
