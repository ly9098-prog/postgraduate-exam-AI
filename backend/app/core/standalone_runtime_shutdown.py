"""Stop standalone role resources at their original failure boundaries."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.runtime_ocr_startup import HttpOcrResources


async def stop_standalone_worker_services(role: str, logger: logging.Logger) -> None:
    if role in ("worker", "all"):
        try:
            from app.services.task_queue_worker import graceful_shutdown_v2

            await graceful_shutdown_v2()
        except Exception as e:
            logger.warning("v2 Graceful shutdown failed: %s", e)

        try:
            from app.services.task_queue_worker import stop_reaper_v2

            await stop_reaper_v2()
        except Exception as e:
            logger.warning("Reaper v2 stop failed: %s", e)

        try:
            from app.services.ai_prewarm_worker import stop_worker

            await stop_worker()
        except Exception as e:
            logger.warning("AI prewarm worker stop error: %s", e)
    else:
        # Non-worker roles still signal draining
        try:
            from app.services.task_queue_worker import set_draining_v2

            await set_draining_v2()
        except Exception:
            pass


async def stop_standalone_scheduler_services(role: str, logger: logging.Logger) -> None:
    if role in ("scheduler", "all"):
        try:
            from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler

            await audit_log_cleanup_scheduler.stop()
        except Exception as e:
            logger.warning("Audit cleanup scheduler stop error: %s", e)

        try:
            from app.services.recommendation_metrics_scheduler import (
                recommendation_metrics_scheduler,
            )

            await recommendation_metrics_scheduler.stop()
        except Exception as e:
            logger.warning("Recommendation metrics scheduler stop error: %s", e)

        try:
            from app.services.export.processor import stop_processor

            await stop_processor()
        except Exception as e:
            logger.warning("Export processor stop error: %s", e)


async def shutdown_standalone_formula_pool(logger: logging.Logger) -> None:
    try:
        from app.services.formula_graph_spec_renderer import (
            shutdown_formula_render_pool,
        )

        await asyncio.wait_for(
            asyncio.to_thread(
                shutdown_formula_render_pool, wait=True, cancel_futures=False
            ),
            timeout=30,
        )
    except TimeoutError:
        logger.warning("Formula render pool shutdown timed out")
    except Exception:
        logger.exception("Formula render pool shutdown error")


async def shutdown_standalone_ocr(
    role: str,
    logger: logging.Logger,
    *,
    ocr_resources: HttpOcrResources | None = None,
) -> None:
    if role in ("worker", "all"):
        from app.core.deployment_profile import (
            DeploymentProfile,
            detect_deployment_profile,
        )

        profile = detect_deployment_profile()
        if profile != DeploymentProfile.CLOUD_API:
            try:
                from app.services.ocr_executor_service import ocr_executor

                await asyncio.wait_for(ocr_executor.shutdown(wait=True), timeout=30)
            except Exception:
                logger.exception("OCR executor shutdown error")

        if ocr_resources is not None:
            try:
                if ocr_resources.gateway is not None:
                    try:
                        await ocr_resources.gateway.shutdown()
                    except Exception:
                        pass
                if ocr_resources.worker_client is not None:
                    try:
                        await ocr_resources.worker_client.shutdown()
                    except Exception:
                        pass
                    finally:
                        ocr_resources.worker_client = None
            except asyncio.CancelledError:
                ocr_resources.worker_client = None
                raise
            return

        try:
            # Gateway may or may not be initialized in this role
            # Attempt shutdown safely
            from app.services.ocr_service import get_gateway

            gw = get_gateway()
            if gw is not None:
                await gw.shutdown()
        except Exception:
            pass


async def shutdown_standalone_render_resources(logger: logging.Logger) -> None:
    try:
        from app.core.executor_registry import (
            clear_executor_registry,
            get_all_executors,
        )
        from app.core.executors import shutdown_executors

        await shutdown_executors(get_all_executors())
        clear_executor_registry()
    except Exception as e:
        logger.warning("Executor shutdown error: %s", e)

    # 7. PDF renderer
    try:
        from app.services.pdf_renderer_service import pdf_renderer

        await pdf_renderer.shutdown()
    except Exception as e:
        logger.warning("PDF renderer shutdown error: %s", e)


async def close_standalone_runtime_connections(logger: logging.Logger) -> None:
    try:
        from app.services.task_queue_service import task_queue

        await task_queue.close()
    except Exception as e:
        logger.warning("Task queue close error: %s", e)

    # 9. DB engine
    try:
        from app.core.database import engine

        await engine.dispose()
    except Exception as e:
        logger.warning("Engine dispose error: %s", e)

    # 10. Resource guard orphan reconciler
    try:
        from app.core.resource_guard import resource_guard

        await resource_guard.stop_orphan_reconciler()
    except Exception as e:
        logger.warning("Orphan reconciler stop error: %s", e)
