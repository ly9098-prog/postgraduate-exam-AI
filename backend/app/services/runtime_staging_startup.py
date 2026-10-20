"""Shared staging startup sweep policy for HTTP and standalone roles."""

import logging


async def sweep_staging_on_startup(logger: logging.Logger) -> None:
    """Sweep legacy temporary files before role resources are initialized."""
    try:
        from app.core.log_context import log_event
        from app.services.staging_storage import async_sweep_temp_files

        swept = await async_sweep_temp_files()
        if swept:
            log_event(logger, "staging.sweep", count=swept)
    except Exception:
        logger.warning("Staging temp sweep failed (non-fatal)", exc_info=True)
