"""Execute formula graph batches using the existing preview/confirm transaction."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc_datetime, utcnow
from app.models.formula import FormulaCard
from app.services import formula_graph_batch_state as batch_state
from app.services.formula_graph_spec_service import confirm_preview, generate_preview

logger = logging.getLogger("app.services.formula_graph_spec_service")
MAX_RETRIES = 3


async def _process_card(
    session: AsyncSession, card: FormulaCard, admin_id: int, job: dict,
) -> bool:
    card_reload = await session.get(FormulaCard, card.id)
    if not card_reload or card_reload.deleted_at:
        job["skipped"] += 1
        return False
    if card_reload.graph_status not in ("missing", "failed"):
        job["skipped"] += 1
        return False
    spec = card_reload.graph_spec
    if not spec:
        job["skipped"] += 1
        return False
    retries = 0
    while retries <= MAX_RETRIES:
        try:
            preview = await generate_preview(session, card_reload, spec, admin_id)
            await confirm_preview(
                session, card_reload, preview["preview_token"],
                card_version=card_reload.version, accept_warnings=True, admin_id=admin_id,
            )
            job["succeeded"] += 1
            return True
        except ValueError as e:
            retries += 1
            str(e)
            if retries > MAX_RETRIES:
                raise
            await asyncio.sleep(1)
    return True


async def process_batch(job_id: str, cards: list[FormulaCard], admin_id: int) -> None:
    job = batch_state.jobs.get(job_id)
    if not job:
        return
    from app.core.database import async_session

    for idx, card in enumerate(cards):
        try:
            async with async_session() as session:
                async with session.begin():
                    if not await _process_card(session, card, admin_id, job):
                        continue
        except Exception as e:
            job["failed"] += 1
            job["errors"].append(
                {"card_id": card.id, "title": card.title, "error": str(e)[:200]}
            )
            logger.warning(
                "Batch card %d failed after %d retries: %s", card.id, MAX_RETRIES, e
            )
        job["processed"] += 1
        job["progress"] = (idx + 1) / len(cards) if cards else 1.0
    if job["succeeded"] > 0 and job["failed"] == 0:
        job["status"] = "completed"
    elif job["succeeded"] > 0 and job["failed"] > 0:
        job["status"] = "partial_failed"
    elif job["failed"] > 0:
        job["status"] = "failed"
    else:
        job["status"] = "completed"
    job["finished_at"] = serialize_utc_datetime(utcnow())
    batch_state._cleanup_old_jobs()
