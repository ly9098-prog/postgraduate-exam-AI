"""Close shared runtime resources at their original lifespan boundaries."""

import logging

logger = logging.getLogger("postgraduate-ai")


async def shutdown_render_resources() -> None:
    try:
        from app.core.executor_registry import (
            clear_executor_registry,
            get_all_executors,
        )
        from app.core.executors import shutdown_executors

        await shutdown_executors(get_all_executors())
        clear_executor_registry()
        logger.info("BoundedExecutors shut down")
    except Exception as e:
        logger.warning("BoundedExecutor shutdown error: %s", e)

    # 8. PDF renderer shutdown (common)
    try:
        from app.services.pdf_renderer_service import pdf_renderer

        await pdf_renderer.shutdown()
        logger.info("PDF renderer shut down")
    except Exception as e:
        logger.warning("PDF renderer shutdown error: %s", e)


async def close_runtime_connections() -> None:
    try:
        from app.services.task_queue_service import task_queue

        await task_queue.close()
        logger.info("Task queue Redis client closed")
    except Exception as e:
        logger.warning("Task queue close error: %s", e)

    # 8b. Close AI resource-governance Redis pools.
    try:
        from app.core.ai_runtime_guard import ai_runtime_guard

        await ai_runtime_guard.close()
        from app.features.token_budget import close_token_budget

        await close_token_budget()
        logger.info("AI runtime resource pools closed")
    except Exception as e:
        logger.warning("AI runtime resource pool close error: %s", e)

    # 9. Dispose SQLAlchemy engine
    try:
        from app.core.database import engine

        await engine.dispose()
        logger.info("SQLAlchemy engine disposed")
    except Exception as e:
        logger.warning("Engine dispose error: %s", e)


async def stop_resource_reconciler() -> None:
    try:
        from app.core.resource_guard import resource_guard

        await resource_guard.stop_orphan_reconciler()
    except Exception as e:
        logger.warning("Orphan reconciler stop error: %s", e)
