"""Failure persistence for the generic import background wrapper."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


async def record_background_pipeline_failure(
    *,
    pipeline_id: str,
    source_type: str,
    source_file: str,
    exc: Exception,
    async_session: Callable[[], Any],
    set_pipeline_store: Callable[..., Awaitable[Any]],
    capture_exception: Callable[..., Any],
) -> None:
    try:
        from app.features import pipeline_checkpoint as ckpt

        async with async_session() as db:
            await ckpt.update_pipeline_status(
                db,
                pipeline_id,
                status="failed",
                error_message=str(exc)[:4000],
                finished=True,
            )
    except Exception:
        logger.exception(
            "Failed to persist background pipeline failure: %s", pipeline_id
        )
    await set_pipeline_store(
        pipeline_id,
        {
            "pipeline_id": pipeline_id,
            "status": "failed",
            "source_type": source_type,
            "errors": [f"后台任务崩溃: {exc}"],
            "started_at": "",
            "finished_at": "",
        },
    )
    capture_exception(
        exc, tags={"pipeline_id": pipeline_id, "stage": "pipeline_background"}
    )
