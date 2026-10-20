"""Shared periodic entrypoints; scheduling and locks stay in system tasks."""

import logging


async def _run_registered_periodic_task(task_id: str, label: str) -> None:
    from app.services.system_task_service import run_registered_periodic_task

    await run_registered_periodic_task(task_id, label)


async def run_token_cleanup() -> None:
    await _run_registered_periodic_task(
        "refresh_token_cleanup", "Refresh token cleanup"
    )


async def run_staging_cleanup() -> None:
    await _run_registered_periodic_task("staging_cleanup", "Staging cleanup")


async def run_export_processor_loop(logger: logging.Logger) -> None:
    try:
        from app.services.export.processor import run_export_processor

        await run_export_processor()
    except Exception as e:
        logger.warning("Export processor exited: %s", e)


async def run_export_cleanup() -> None:
    await _run_registered_periodic_task("export_cleanup", "Export cleanup")
