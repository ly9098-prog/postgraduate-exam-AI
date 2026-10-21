"""Stop HTTP-only prerun tasks at their original lifespan shutdown position."""

import asyncio
import logging
import sys

logger = logging.getLogger("postgraduate-ai")


async def stop_lag_monitor(task: asyncio.Task | None) -> None:
    """Cancel and await the event-loop lag monitor before draining tasks."""
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def stop_export_processor(role: str) -> None:
    """Signal the export processor to drain before cancelling background tasks."""
    try:
        from app.services.export.processor import stop_processor

        await stop_processor()
        logger.info("export_processor_stopped role=%s", role)
    except Exception as e:
        logger.warning("Export processor stop signal failed: %s", e)


def raise_after_http_shutdown(error: Exception | None) -> None:
    """Raise a completed shutdown failure unless startup already owns the exit."""
    if error is not None and sys.exc_info() == (None, None, None):
        raise error
