"""Worker entry point — background task processor (no HTTP listener).

Usage::

    python -m app.worker_main

Sets PROCESS_ROLE=worker and runs only the task dispatcher, reaper,
and AI prewarm worker. Does NOT start an HTTP server.

The worker process should NOT be exposed to public networks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

os.environ.setdefault("PROCESS_ROLE", "worker")

# Ensure the app package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("postgraduate-ai.worker")


async def _run_worker() -> None:
    """Initialize dependencies and run the worker event loop."""
    from app.core.config import settings
    from app.core.database import init_db
    from app.core.logging_config import setup_logging
    from app.services.production_config_validator import (
        validate_production_config,
        validate_production_config_async,
    )

    setup_logging()

    # Validate production config
    validate_production_config()
    await validate_production_config_async()

    # Initialize database
    await init_db()

    # Start task dispatcher (v2)
    from app.services.task_queue_worker import run_dispatcher_v2
    dispatcher_task = asyncio.create_task(
        run_dispatcher_v2(), name="pipeline-dispatcher-v2"
    )

    # Start reaper (v2)
    from app.services.task_queue_worker import run_reaper_loop_v2
    reaper_task = asyncio.create_task(
        run_reaper_loop_v2(), name="task-reaper-v2"
    )

    # Start AI prewarm worker
    from app.services.ai_prewarm_worker import start_worker
    await start_worker()

    logger.info(
        "Worker started: role=%s concurrency=%d env=%s",
        settings.PROCESS_ROLE, settings.WORKER_CONCURRENCY, settings.APP_ENV,
    )

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Worker received SIGTERM/SIGINT, initiating graceful shutdown")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

    await stop_event.wait()

    # Graceful shutdown
    logger.info("Worker shutting down...")
    from app.services.task_queue_worker import graceful_shutdown_v2
    await graceful_shutdown_v2()

    from app.services.task_queue_worker import stop_reaper_v2
    await stop_reaper_v2()

    from app.services.ai_prewarm_worker import stop_worker as stop_prewarm
    await stop_prewarm()

    # Cancel background tasks
    for t in (dispatcher_task, reaper_task):
        if not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    # Close infrastructure
    from app.services.task_queue_service import task_queue
    await task_queue.close()

    from app.core.database import engine
    await engine.dispose()

    logger.info("Worker shut down complete")


def main() -> None:
    """Run the worker process."""
    try:
        asyncio.run(_run_worker())
    except KeyboardInterrupt:
        logger.info("Worker interrupted")
    except SystemExit:
        raise
    except Exception:
        logger.exception("Worker fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
