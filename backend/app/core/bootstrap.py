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
from collections.abc import Awaitable

from app.core.config import settings

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


# ── Background task management ──


class ManagedTask:
    """A managed ``asyncio.Task`` with auto-exception-logging and cancellation.

    Usage::

        mt = ManagedTask.create(coro, name="my-task")
        ...
        mt.cancel()
        await mt.wait(timeout=30)
    """

    def __init__(self, task: asyncio.Task, name: str) -> None:
        self._task = task
        self._name = name
        self._task.add_done_callback(self._on_done)

    @property
    def name(self) -> str:
        return self._name

    @staticmethod
    def _on_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(
                "Background task %s failed: %s: %s",
                task.get_name(), type(exc).__name__, exc,
            )

    def cancel(self) -> None:
        if not self._task.done():
            self._task.cancel()

    async def wait(self, timeout: float = 30) -> None:
        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except asyncio.CancelledError:
            pass
        except TimeoutError:
            logger.warning("Managed task %s: did not stop within %ss grace", self._name, timeout)
        except Exception as exc:
            logger.warning("Managed task %s: %s: %s", self._name, type(exc).__name__, exc)

    @classmethod
    def create(cls, coro: Awaitable, name: str) -> ManagedTask:
        """Create a managed background task from a coroutine."""
        task = asyncio.create_task(coro, name=name)
        return cls(task, name)


class TaskRegistry:
    """Registry of managed background tasks for ordered shutdown."""

    def __init__(self) -> None:
        self._tasks: list[ManagedTask] = []

    def register(self, task: ManagedTask) -> None:
        self._tasks.append(task)

    def create(self, coro: Awaitable, name: str) -> ManagedTask:
        mt = ManagedTask.create(coro, name)
        self._tasks.append(mt)
        return mt

    def cancel_all(self) -> list[ManagedTask]:
        running = [t for t in self._tasks if not t._task.done()]
        for t in running:
            t.cancel()
        return running

    async def wait_all(self, timeout: float = 30) -> None:
        """Cancel all tasks and wait once for the whole registry.

        Waiting task-by-task multiplied shutdown latency by the number of
        registered loops (for example, six tasks × 30 seconds).  A single
        bounded wait keeps the process shutdown deadline predictable.
        """
        running = self.cancel_all()
        if not running:
            return

        tasks = {managed._task for managed in running}
        _done, pending = await asyncio.wait(tasks, timeout=timeout)
        if pending:
            names = sorted(task.get_name() for task in pending)
            logger.warning(
                "Managed tasks did not stop within %ss grace: %s",
                timeout,
                names,
            )
            for task in pending:
                task.cancel()

    def __len__(self) -> int:
        return len(self._tasks)


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
    logger.info("Worker executors initialized: %s", {k: v.name for k, v in executors.items()})

    # OCR Gateway (external HTTP client only — no local Paddle).
    # Let the worker client own its AsyncClient so gateway.shutdown() closes it.
    from app.core.ocr_runtime_config import get_runtime_config
    from app.features.ocr_gateway import OCRGateway
    from app.services.ocr_worker_client import create_ocr_worker_client

    cfg = get_runtime_config()
    if cfg.enabled:
        worker_client = create_ocr_worker_client(cfg)
        ocr_gateway = OCRGateway(
            mode="gateway",
            profile=profile,
            worker_client=worker_client,
        )
        from app.services.ocr_service import set_gateway

        set_gateway(ocr_gateway)
        logger.info(
            "OCR Gateway initialized (role=worker exec_backend=%s profile=%s)",
            cfg.execution_backend, cfg.profile,
        )
    else:
        logger.info("OCR not enabled on worker, skipping Gateway")

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
        settings.WORKER_CONCURRENCY, profile,
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
        from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler

        await audit_log_cleanup_scheduler.start()
        logger.info("Audit log cleanup scheduler started")
    except Exception as e:
        _report("Audit log cleanup scheduler", e)

    # Recommendation metrics daily aggregation scheduler
    try:
        from app.services.recommendation_metrics_scheduler import (
            recommendation_metrics_scheduler,
        )

        await recommendation_metrics_scheduler.start()
        logger.info("Recommendation metrics scheduler started")
    except Exception as e:
        _report("Recommendation metrics scheduler", e)

    # Periodic token cleanup (with distributed lock)
    registry.create(_periodic_token_cleanup(), "token-cleanup")

    # Periodic staging cleanup
    registry.create(_periodic_staging_cleanup(), "staging-cleanup")

    # Export processor + cleanup
    registry.create(_periodic_export_processor(), "export-processor")
    registry.create(_periodic_export_cleanup(), "export-cleanup")

    # Outbox dispatcher + DB/Redis reconciler
    try:
        from app.services.outbox_service import (
            run_outbox_dispatcher,
            run_outbox_reconciler,
        )
        from app.services.task_queue_service import task_queue

        async def _enqueue_from_outbox(
            task_id: str,
            task_type: str,
            payload: dict,
            schema_version: int,
        ) -> object:
            return await task_queue.enqueue_v2(
                task_type,
                payload,
                task_id=task_id,
                schema_version=schema_version,
            )

        registry.create(run_outbox_dispatcher(_enqueue_from_outbox), "outbox-dispatcher")
        registry.create(run_outbox_reconciler(), "outbox-reconciler")
        logger.info("Outbox dispatcher + DB/Redis reconciler started")
    except Exception as e:
        logger.warning("Outbox init failed (non-fatal): %s", e)

    # Business-level answer projection reconciler.  Keep this safety net
    # independent from the generic DB/Redis outbox reconciler so one component
    # failing to initialize cannot disable the other.
    try:
        from app.services.practice.projection_reconciliation_service import (
            run_answer_projection_reconciler,
        )

        registry.create(
            run_answer_projection_reconciler(),
            "answer-projection-reconciler",
        )
        logger.info("Answer projection business reconciler started")
    except Exception as e:
        logger.warning("Answer projection reconciler init failed (non-fatal): %s", e)

    # Production async-task health monitor.  It derives state from PostgreSQL
    # and Redis and only logs/reports when the health signature changes, so a
    # persistent incident does not create one alert per polling interval.
    try:
        from app.services.task_observability_service import run_task_health_monitor

        registry.create(run_task_health_monitor(), "async-task-health-monitor")
        logger.info("Async task health monitor started")
    except Exception as e:
        logger.warning("Async task health monitor init failed (non-fatal): %s", e)


# ── Periodic task implementations (shared between roles) ──


async def _run_registered_periodic_task(task_id: str, label: str) -> None:
    """Delegate periodic scheduling to the shared system-task runtime."""
    from app.services.system_task_service import run_registered_periodic_task

    await run_registered_periodic_task(task_id, label)


async def _periodic_token_cleanup() -> None:
    """Clean up expired refresh tokens on deterministic 6-hour UTC slots."""
    await _run_registered_periodic_task("refresh_token_cleanup", "Refresh token cleanup")


async def _periodic_staging_cleanup() -> None:
    """Clean up expired staging files at minute 00 of every UTC hour."""
    await _run_registered_periodic_task("staging_cleanup", "Staging cleanup")


async def _periodic_export_processor() -> None:
    """Run export processor (loop, exits via stop_processor)."""
    try:
        from app.services.export.processor import run_export_processor

        await run_export_processor()
    except Exception as e:
        logger.warning("Export processor exited: %s", e)


async def _periodic_export_cleanup() -> None:
    """Clean up expired export tasks at minute 02 of every UTC hour."""
    await _run_registered_periodic_task("export_cleanup", "Export cleanup")


# ── Startup helpers ──


def _startup_failure_reporter(profile):
    """Return a callable that reports component startup failures.

    In cloud_api/production, raises SystemError; in development, logs warning.
    """
    from app.core.deployment_profile import DeploymentProfile

    is_restricted = profile == DeploymentProfile.CLOUD_API or settings.APP_ENV == "production"

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
        scratch = os.path.join(os.path.dirname(settings.STAGING_STORAGE_DIR or "/opt/2240ai-v2/staging"), "scratch")
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
            asyncio.to_thread(shutdown_formula_render_pool, wait=True, cancel_futures=False),
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
        "Role %s fully initialized — running event loop", role,
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
