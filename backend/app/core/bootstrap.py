"""Shared process lifecycle — bootstrap/lifecycle for web/worker/scheduler.

All three entry points (``web_main.py``, ``worker_main.py``, ``scheduler_main.py``)
delegate to this module so that startup and shutdown logic is defined exactly once.

Usage::

    # Web (FastAPI via uvicorn/gunicorn — lifespan is in main.py)
    os.environ.setdefault("PROCESS_ROLE", "web")

    # Worker (standalone process)
    from app.core.bootstrap import run_role
    run_role("worker")

    # Scheduler (standalone process)
    from app.core.bootstrap import run_role
    run_role("scheduler")
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from app.core.config import settings
from app.core.runtime_task_registry import TaskRegistry
from app.services.runtime_ocr_startup import initialize_worker_ocr_gateway
from app.services.runtime_periodic_tasks import (
    run_export_cleanup,
    run_export_processor_loop,
    run_staging_cleanup,
    run_token_cleanup,
)
from app.services.runtime_scheduler_startup import (
    start_answer_projection_task,
    start_audit_cleanup_scheduler,
    start_recommendation_metrics_scheduler,
    start_scheduler_health_task,
    start_scheduler_outbox_tasks,
)

logger = logging.getLogger("postgraduate-ai.bootstrap")

# Guard: worker/scheduler roles started via HTTP (Gunicorn / uvicorn) must fail.
_FORBIDDEN_HTTP_ROLES = frozenset({"worker", "scheduler"})


def _guard_http_role(role: str) -> None:
    """Raise SystemError if a worker or scheduler role is started over HTTP.

    Detects Gunicorn/uvicorn by checking whether this process was launched
    by a web server (argv contains gunicorn/uvicorn or GUNICORN_CMD_ARGS
    / UVICORN_CMD_ARGS env vars are set).

    Workers and schedulers must be started as standalone processes via
    ``python -m app.worker_main`` / ``python -m app.scheduler_main``.
    Starting them over HTTP would expose an unnecessary port and waste
    resources on connection handling.
    """
    if role not in _FORBIDDEN_HTTP_ROLES:
        return
    is_http = (
        "gunicorn" in (sys.argv[0] if sys.argv else "").lower()
        or "uvicorn" in (sys.argv[0] if sys.argv else "").lower()
        or bool(os.environ.get("GUNICORN_CMD_ARGS"))
        or bool(os.environ.get("UVICORN_CMD_ARGS"))
    )
    if is_http:
        raise SystemError(
            f"PROCESS_ROLE={role} started over HTTP (Gunicorn/uvicorn). "
            f"This role must be started as a standalone process: "
            f"python -m app.{role}_main"
        )


# ── Signal handling ──


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Install SIGTERM/SIGINT handlers that set the stop event."""
    loop = asyncio.get_running_loop()

    def _on_signal() -> None:
        if not stop_event.is_set():
            logger.info("Received shutdown signal, initiating graceful shutdown")
            stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Windows / some environments don't support add_signal_handler
            pass
        except Exception:
            logger.warning("Could not install signal handler for %s", sig)


# ── Role-specific initializers (lazy imports) ──


async def _init_worker_dependencies(registry: TaskRegistry) -> None:
    """Initialize worker-specific: OCR Gateway, executors, dispatcher, reaper, AI prewarm.

    Called at startup; raises on failure in production.
    """
    from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

    profile = detect_deployment_profile()
    # Worker scratch dir
    _ensure_scratch_dir()

    # Role-aware bounded executors
    from app.core.executor_registry import init_executor_registry
    from app.core.executors import init_executors_for_role

    executors = init_executors_for_role(
        "worker",
        is_production=(profile == DeploymentProfile.CLOUD_API),
    )
    init_executor_registry(executors)
    logger.info(
        "Worker executors initialized: %s", {k: v.name for k, v in executors.items()}
    )

    # OCR Gateway (external HTTP client only — no local Paddle).
    # Let the worker client own its AsyncClient so gateway.shutdown() closes it.
    initialize_worker_ocr_gateway(profile, logger)

    # Staging orphan reconciler
    from app.core.resource_guard import resource_guard

    await resource_guard.start_orphan_reconciler()

    # Pipeline dispatcher + reaper (v2)
    from app.services.task_queue_worker import run_dispatcher_v2, run_reaper_loop_v2

    registry.create(run_dispatcher_v2(), "pipeline-dispatcher-v2")
    registry.create(run_reaper_loop_v2(), "task-reaper-v2")

    # AI prewarm worker
    from app.services.ai_prewarm_worker import start_worker

    await start_worker()

    logger.info(
        "Worker dependencies initialized: concurrency=%d profile=%s",
        settings.WORKER_CONCURRENCY,
        profile,
    )


async def _init_scheduler_dependencies(registry: TaskRegistry) -> None:
    """Initialize scheduler-specific: periodic tasks, cleanup loops."""
    from app.core.deployment_profile import detect_deployment_profile

    profile = detect_deployment_profile()
    _report = _startup_failure_reporter(profile)

    # Cross-process heartbeat used by /system/tasks to distinguish a healthy
    # recurring executor from a web process that can only run tasks manually.
    try:
        from app.services.system_task_service import run_scheduler_heartbeat

        registry.create(run_scheduler_heartbeat(), "scheduler-heartbeat")
    except Exception as e:
        _report("Scheduler heartbeat", e)

    # Audit log cleanup scheduler
    try:
        await start_audit_cleanup_scheduler(logger)
    except Exception as e:
        _report("Audit log cleanup scheduler", e)

    # Recommendation metrics daily aggregation scheduler
    try:
        await start_recommendation_metrics_scheduler(logger)
    except Exception as e:
        _report("Recommendation metrics scheduler", e)

    # Periodic token cleanup (with distributed lock)
    registry.create(run_token_cleanup(), "token-cleanup")

    # Periodic staging cleanup
    registry.create(run_staging_cleanup(), "staging-cleanup")

    # Export processor + cleanup
    registry.create(run_export_processor_loop(logger), "export-processor")
    registry.create(run_export_cleanup(), "export-cleanup")

    # Outbox dispatcher + DB/Redis reconciler
    start_scheduler_outbox_tasks(registry, logger)

    # Business-level answer projection reconciler.  Keep this safety net
    # independent from the generic DB/Redis outbox reconciler so one component
    # failing to initialize cannot disable the other.
    start_answer_projection_task(registry, logger)

    # Production async-task health monitor.  It derives state from PostgreSQL
    # and Redis and only logs/reports when the health signature changes, so a
    # persistent incident does not create one alert per polling interval.
    start_scheduler_health_task(registry, logger)


# ── Startup helpers ──


def _startup_failure_reporter(profile):
    """Return a callable that reports component startup failures.

    In cloud_api/production, raises SystemError; in development, logs warning.
    """
    from app.core.deployment_profile import DeploymentProfile

    is_restricted = (
        profile == DeploymentProfile.CLOUD_API or settings.APP_ENV == "production"
    )

    def _report(component: str, exc: Exception) -> None:
        if is_restricted:
            logger.critical("%s start failed — fatal in production", component)
            raise SystemError(f"{component} start failed: {exc}") from exc
        logger.warning("%s start failed (non-fatal): %s", component, exc)

    return _report


def _ensure_scratch_dir() -> str:
    """Ensure worker scratch directory exists, raising on misconfiguration."""
    scratch = settings.WORKER_SCRATCH_DIR
    if not scratch or scratch == "/tmp" or scratch == "/tmp/worker-scratch":
        # In production, WORKER_SCRATCH_DIR must be explicitly configured.
        # In development, fall back to a safe location.
        from app.core.deployment_profile import (
            DeploymentProfile,
            detect_deployment_profile,
        )

        profile = detect_deployment_profile()
        if profile == DeploymentProfile.CLOUD_API or settings.APP_ENV == "production":
            raise SystemError(
                "WORKER_SCRATCH_DIR must be explicitly configured in production "
                "(pointing to a Docker volume or dedicated directory). "
                f"Current value: {scratch!r}"
            )
        scratch = os.path.join(
            os.path.dirname(settings.STAGING_STORAGE_DIR or "/opt/2240ai-v2/staging"),
            "scratch",
        )
    os.makedirs(scratch, exist_ok=True)
    return scratch


# ── Shutdown ──


async def shutdown_role(role: str, registry: TaskRegistry) -> None:
    """Ordered shutdown of all role-specific infrastructure.

    Call from the role's shutdown path (FastAPI lifespan finally block
    or standalone process signal handler).
    """
    logger.info("=== Shutdown sequence started (role=%s) ===", role)

    # 1. Worker: graceful drain
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

    # 2. Scheduler: stop periodic loops
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

    # 3. Cancel all managed background tasks
    await registry.wait_all(timeout=settings.WORKER_SHUTDOWN_GRACE_SEC)

    # 4. Formula render pool
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

    # 5. OCR infrastructure (role-aware)
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

        try:
            # Gateway may or may not be initialized in this role
            # Attempt shutdown safely
            from app.services.ocr_service import get_gateway

            gw = get_gateway()
            if gw is not None:
                await gw.shutdown()
        except Exception:
            pass

    # 6. BoundedExecutors shutdown
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

    # 8. Task queue Redis
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

    logger.info("=== Shutdown sequence completed (role=%s) ===", role)


# ── Standalone process runner ──


async def _run_role_async(role: str) -> None:
    """Initialize dependencies and run the event loop for a standalone role."""
    from app.core.logging_config import setup_logging

    setup_logging()

    logger.info("Starting 2240AI — role=%s env=%s", role, settings.APP_ENV)

    # Validate production config
    from app.services.production_config_validator import (
        validate_production_config,
        validate_production_config_async,
    )

    validate_production_config()
    await validate_production_config_async()

    from app.core.deployment_profile import detect_deployment_profile

    detect_deployment_profile()

    # Staging sweep on startup
    try:
        from app.core.log_context import log_event
        from app.services.staging_storage import async_sweep_temp_files

        swept = await async_sweep_temp_files()
        if swept:
            log_event(logger, "staging.sweep", count=swept)
    except Exception:
        logger.warning("Staging temp sweep failed (non-fatal)", exc_info=True)

    # Create managed task registry
    registry = TaskRegistry()

    # Initialize role-specific dependencies
    try:
        if role == "worker":
            await _init_worker_dependencies(registry)
        elif role == "scheduler":
            await _init_scheduler_dependencies(registry)
        else:
            raise ValueError(f"Unknown standalone role: {role!r}")
    except SystemError:
        raise
    except Exception as e:
        logger.critical("Role %s initialization failed: %s", role, e)
        raise SystemError(f"Role {role} initialization failed: {e}") from e

    logger.info(
        "Role %s fully initialized — running event loop",
        role,
    )

    # Wait for shutdown signal
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    await stop_event.wait()

    # Shutdown
    await shutdown_role(role, registry)


def run_role(role: str) -> None:
    """Run a standalone process role (worker or scheduler).

    Sets ``PROCESS_ROLE``, validates environment, initializes dependencies,
    runs the event loop, and performs graceful shutdown on SIGTERM/SIGINT.

    Usage::

        # In worker_main.py:
        from app.core.bootstrap import run_role
        run_role("worker")

        # In scheduler_main.py:
        from app.core.bootstrap import run_role
        run_role("scheduler")
    """
    if role not in _FORBIDDEN_HTTP_ROLES:
        raise ValueError(f"Unknown standalone role: {role!r}")
    _guard_http_role(role)
    # Settings is imported at module load time, so update both the process
    # environment and the singleton before any role-aware validation/pool setup.
    os.environ["PROCESS_ROLE"] = role
    settings.PROCESS_ROLE = role

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    try:
        asyncio.run(_run_role_async(role))
    except KeyboardInterrupt:
        logger.info("Process interrupted")
    except SystemExit:
        raise
    except SystemError:
        raise
    except Exception:
        logger.exception("Fatal error in role %s", role)
        sys.exit(1)
