"""Scheduler entry point — periodic background tasks (no HTTP listener).

Usage::

    python -m app.scheduler_main

Sets PROCESS_ROLE=scheduler and runs only periodic tasks:
token cleanup, staging cleanup, pomodoro scheduler, audit cleanup,
export processor. Does NOT start an HTTP server.

All scheduled tasks acquire a distributed Redis lock before execution.
If the lock cannot be acquired, the task is skipped (another instance
is already running it).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

os.environ.setdefault("PROCESS_ROLE", "scheduler")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("postgraduate-ai.scheduler")


async def _run_scheduler() -> None:
    """Initialize dependencies and run the scheduler event loop."""
    from app.core.config import settings
    from app.core.database import init_db
    from app.core.logging_config import setup_logging
    from app.services.production_config_validator import (
        validate_production_config,
        validate_production_config_async,
    )

    setup_logging()

    validate_production_config()
    await validate_production_config_async()

    await init_db()

    # Start periodic background tasks
    bg_tasks: list[asyncio.Task] = []

    # Token cleanup (every 6 hours, with distributed lock)
    async def _token_cleanup_loop():
        from app.core.distributed_lock import DistributedLock
        lock = DistributedLock("token:cleanup")
        while True:
            await asyncio.sleep(6 * 3600)
            async with lock.acquire_and_renew(ttl=300, renew_interval=60) as handle:
                if not handle.is_still_held():
                    logger.debug("Token cleanup lock held by another instance")
                    continue
                try:
                    from app.core.database import async_session
                    from app.services import token_service
                    async with async_session() as db:
                        deleted = await token_service.cleanup_expired_tokens(db)
                        if deleted:
                            logger.info("Cleaned up %d expired refresh tokens", deleted)
                except Exception as e:
                    logger.warning("Token cleanup failed (non-fatal): %s", e)

    bg_tasks.append(asyncio.create_task(_token_cleanup_loop(), name="token-cleanup"))

    # Staging cleanup (hourly)
    async def _staging_cleanup_loop():
        while True:
            await asyncio.sleep(3600)
            try:
                from app.services.staging_storage import async_cleanup_orphans
                removed = await async_cleanup_orphans()
                if removed:
                    logger.info("Staging cleanup removed %d expired objects", removed)
            except Exception as e:
                logger.warning("Staging cleanup failed (non-fatal): %s", e)

    bg_tasks.append(asyncio.create_task(_staging_cleanup_loop(), name="staging-cleanup"))

    # Pomodoro scheduler
    try:
        from app.services.pomodoro_scheduler_service import pomodoro_scheduler
        await pomodoro_scheduler.start()
        logger.info("Pomodoro scheduler started")
    except Exception as e:
        logger.warning("Pomodoro scheduler start failed (non-fatal): %s", e)

    # Audit log cleanup scheduler
    try:
        from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler
        await audit_log_cleanup_scheduler.start()
        logger.info("Audit log cleanup scheduler started")
    except Exception as e:
        logger.warning("Audit log cleanup scheduler start failed (non-fatal): %s", e)

    # Export processor + cleanup
    async def _export_processor_loop():
        try:
            from app.services.export.processor import run_export_processor
            await run_export_processor()
        except Exception as e:
            logger.warning("Export processor exited: %s", e)

    bg_tasks.append(asyncio.create_task(_export_processor_loop(), name="export-processor"))

    async def _export_cleanup_loop():
        while True:
            await asyncio.sleep(3600)
            try:
                from app.core.database import async_session
                from app.services.export.cleanup import cleanup_expired
                async with async_session() as db:
                    stats = await cleanup_expired(db)
                    if stats["tasks_expired"] > 0:
                        logger.info("Export cleanup: %s", stats)
            except Exception as e:
                logger.warning("Export cleanup failed (non-fatal): %s", e)

    bg_tasks.append(asyncio.create_task(_export_cleanup_loop(), name="export-cleanup"))

    logger.info(
        "Scheduler started: role=%s env=%s",
        settings.PROCESS_ROLE, settings.APP_ENV,
    )

    # Wait for shutdown
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Scheduler received SIGTERM/SIGINT, shutting down")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    await stop_event.wait()

    # Shutdown
    logger.info("Scheduler shutting down...")
    try:
        await pomodoro_scheduler.stop()
    except Exception:
        pass
    try:
        await audit_log_cleanup_scheduler.stop()
    except Exception:
        pass
    try:
        from app.services.export.processor import stop_processor
        await stop_processor()
    except Exception:
        pass

    for t in bg_tasks:
        if not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    from app.core.database import engine
    await engine.dispose()

    logger.info("Scheduler shut down complete")


def main() -> None:
    """Run the scheduler process."""
    try:
        asyncio.run(_run_scheduler())
    except KeyboardInterrupt:
        logger.info("Scheduler interrupted")
    except SystemExit:
        raise
    except Exception:
        logger.exception("Scheduler fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
