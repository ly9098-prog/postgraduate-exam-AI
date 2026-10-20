"""Create formula graph batch jobs and submit them to the existing durable queue."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc_datetime, utcnow
from app.models.formula import FormulaCard
from app.services import formula_graph_batch_state as batch_state

logger = logging.getLogger("app.services.formula_graph_spec_service")
BATCH_MAX_SIZE = 50


async def start_batch_generate(
    db: AsyncSession,
    admin_id: int,
    batch_size: int = BATCH_MAX_SIZE,
) -> str:
    """Start batch generation for missing/failed cards. Returns job_id."""
    async with batch_state.lock:
        for jid, job in list(batch_state.jobs.items()):
            if job.get("status") == "running":
                raise ValueError("A batch generation job is already running", "429")

    result = await db.execute(
        select(FormulaCard)
        .where(
            FormulaCard.graph_spec.isnot(None),
            FormulaCard.graph_status.in_(["missing", "failed"]),
            FormulaCard.deleted_at.is_(None),
        )
        .limit(batch_size)
    )
    cards = list(result.scalars().all())

    job_id = uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "status": "running",
        "progress": 0.0,
        "total": len(cards),
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "created_at": serialize_utc_datetime(utcnow()),
        "started_at": serialize_utc_datetime(utcnow()),
        "finished_at": None,
    }
    card_ids = [c.id for c in cards]
    batch_state.jobs[job_id] = job

    from app.services.task_queue_worker import enqueue_formula_batch

    result = await enqueue_formula_batch(job_id, card_ids, admin_id)
    if not result:
        logger.warning("Formula batch %s rejected by queue: %s", job_id, result.reason)
        job["status"] = "failed"
        raise RuntimeError(f"任务队列已满: {result.reason}")

    return job_id
