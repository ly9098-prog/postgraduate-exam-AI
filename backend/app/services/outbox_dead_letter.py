"""Helpers for exposing failed projection/outbox events to admin views."""
from sqlalchemy import select

from app.models.task_outbox import TaskOutbox


async def list_projection_dead_letters(db, limit: int = 100):
    """Return failed durable events without changing retry state."""
    stmt = (
        select(TaskOutbox)
        .where(TaskOutbox.status == "failed")
        .order_by(TaskOutbox.updated_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    return list((await db.execute(stmt)).scalars().all())
