"""Outbox/Redis drift reconciliation helpers.

DB outbox is authoritative. Redis is only a delivery/execution layer.
This module intentionally performs repair planning only; callers execute
Redis operations with their own infrastructure transaction boundaries.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task_outbox import TaskOutbox


async def find_outbox_drift_candidates(db: AsyncSession, limit: int = 100):
    """Find durable tasks that need Redis reconciliation.

    Published rows may need re-dispatch after Redis loss. Terminal failed rows
    are never resurrected automatically.
    """
    stmt = (
        select(TaskOutbox)
        .where(TaskOutbox.status.in_(("published", "failed")))
        .order_by(TaskOutbox.updated_at.asc())
        .limit(max(1, min(limit, 500)))
    )
    return list((await db.execute(stmt)).scalars().all())


def redis_should_accept(outbox: TaskOutbox, redis_state: str | None) -> bool:
    """Return whether Redis state may be repaired from DB state."""
    if outbox.status == "published":
        return redis_state not in ("pending", "running", "done")
    return False
