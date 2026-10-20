"""Standalone worker and scheduler lifecycle assembly.

Entry modules call ``run_role`` here without starting an HTTP listener.
The HTTP lifespan remains in ``app.main``. Resource implementations are
separate from the runner's task registry, signal wait and shutdown order.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from app.core.config import settings
from app.core.runtime_signals import install_role_signal_handlers
from app.core.runtime_task_registry import TaskRegistry
from app.core.standalone_runtime_policy import (
    STANDALONE_ROLES,
    create_standalone_failure_reporter,
    ensure_worker_scratch_directory,
    reject_standalone_http_launch,
)
from app.core.standalone_runtime_shutdown import (
    close_standalone_runtime_connections,
    shutdown_standalone_formula_pool,
    shutdown_standalone_ocr,
    shutdown_standalone_render_resources,
    stop_standalone_scheduler_services,
    stop_standalone_worker_services,
)
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

# ── Role-specific initializers (lazy imports) ──


async def _init_worker_dependencies(registry: TaskRegistry) -> None:
    """Initialize worker-specific: OCR Gateway, executors, dispatcher, reaper, AI prewarm.

    Called at startup; raises on failure in production.
    """
    from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

    profile = detect_deployment_profile()
    # Worker scratch dir
    ensure_worker_scratch_directory(settings)

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
    _report = create_standalone_failure_reporter(profile, settings, logger)

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


# ── Shutdown ──


async def shutdown_role(role: str, registry: TaskRegistry) -> None:
    """Ordered shutdown of all role-specific infrastructure.

    Call from the role's shutdown path (FastAPI lifespan finally block
    or standalone process signal handler).
    """
    logger.info("=== Shutdown sequence started (role=%s) ===", role)

    # 1. Worker: graceful drain
    await stop_standalone_worker_services(role, logger)

    # 2. Scheduler: stop periodic loops
    await stop_standalone_scheduler_services(role, logger)

    # 3. Cancel all managed background tasks
    await registry.wait_all(timeout=settings.WORKER_SHUTDOWN_GRACE_SEC)

    # 4. Formula render pool
    await shutdown_standalone_formula_pool(logger)

    # 5. OCR infrastructure (role-aware)
    await shutdown_standalone_ocr(role, logger)

    # 6. BoundedExecutors shutdown
    await shutdown_standalone_render_resources(logger)

    # 8. Task queue Redis
    await close_standalone_runtime_connections(logger)

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
    install_role_signal_handlers(stop_event, logger)
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
    if role not in STANDALONE_ROLES:
        raise ValueError(f"Unknown standalone role: {role!r}")
    reject_standalone_http_launch(role)
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
