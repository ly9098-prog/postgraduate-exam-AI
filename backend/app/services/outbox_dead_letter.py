"""Helpers for failed projection/outbox visibility and replay.

Replay must be audited by the API layer before invoking dispatch.
"""

from sqlalchemy import select

from app.models.task_outbox import TaskOutbox


async def list_projection_dead_letters(db, limit: int = 100):
    stmt = (
        select(TaskOutbox)
        .where(TaskOutbox.status == "failed")
        .order_by(TaskOutbox.updated_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    return list((await db.execute(stmt)).scalars().all())


def build_dead_letter_replay_audit(actor_id: int, task_id: str, request_id: str):
    return {
        "action": "dead_letter_replay",
        "actor_id": actor_id,
        "resource_type": "task_outbox",
        "resource_id": task_id,
        "request_id": request_id,
    }
