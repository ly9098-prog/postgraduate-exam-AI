import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import async_session, init_db
from app.core.error_codes import ApiError, ErrorCode
from app.core.logging_config import setup_logging
from app.core.ocr_isolation import (
    is_restricted_ocr_environment,
    loaded_local_ocr_modules,
)
from app.core.sentry import init_sentry
from app.services.admin_bootstrap_service import ensure_dev_super_admin
from app.services.production_config_validator import (
    validate_production_config,
    validate_production_config_async,
)

setup_logging()
init_sentry()

logger = logging.getLogger("postgraduate-ai")


_INTERVAL_SEC = 6 * 3600  # 6 hours


async def _periodic_token_cleanup():
    """Background task: clean up expired refresh tokens every 6 hours.

    Uses DistributedLock to prevent concurrent execution across scheduler
    instances. If lock is held by another instance, skip this cycle.
    """
    try:
        from app.core.distributed_lock import DistributedLock
        _token_cleanup_lock = DistributedLock("token:cleanup")
    except Exception:
        _token_cleanup_lock = None

    while True:
        await asyncio.sleep(_INTERVAL_SEC)
        # Try to acquire the distributed lock; skip if another instance is cleaning
        if _token_cleanup_lock is not None:
            async with _token_cleanup_lock.acquire_and_renew(ttl=300, renew_interval=60) as handle:
                if not handle.is_still_held():
                    logger.debug("Token cleanup lock held by another instance, skipping")
                    continue
                await _do_token_cleanup()
        else:
            await _do_token_cleanup()


async def _do_token_cleanup():
    """Execute the actual token cleanup query."""
    try:
        from app.core.database import async_session
        from app.services import token_service

        async with async_session() as db:
            deleted = await token_service.cleanup_expired_tokens(db)
            if deleted:
                logger.info("Cleaned up %d expired refresh tokens", deleted)
    except Exception as e:
        logger.warning("Refresh token cleanup failed (non-fatal): %s", e)


async def _periodic_staging_cleanup():
    """Background task: clean up expired staging files hourly."""
    while True:
        await asyncio.sleep(3600)
        try:
            from app.services.staging_storage import async_cleanup_orphans
            removed = await async_cleanup_orphans()
            if removed:
                logger.info("Staging cleanup removed %d expired objects", removed)
        except Exception as e:
            logger.warning("Staging cleanup failed (non-fatal): %s", e)


async def _periodic_export_processor():
    """Background task: process pending export tasks (scheduler role only)."""
    try:
        from app.services.export.processor import run_export_processor
        await run_export_processor()
    except Exception as e:
        logger.warning("Export processor exited: %s", e)


async def _periodic_export_cleanup():
    """Background task: clean up expired export tasks hourly."""
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


def _report_startup_failure(component: str, exc: Exception) -> None:
    """Log component startup failure.

    In production, any core component startup failure is fatal.
    """
    from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
    try:
        is_prod = (
            detect_deployment_profile() == DeploymentProfile.CLOUD_API
            or _production_mode
        )
    except Exception:
        is_prod = False
    if is_prod:
        logger.critical("%s start failed — fatal in production", component)
        raise SystemError(f"{component} start failed: {exc}") from exc
    logger.warning("%s start failed (non-fatal): %s", component, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    role = settings.PROCESS_ROLE

    # Guard: worker/scheduler roles should not serve HTTP.
    # Use app.worker_main or app.scheduler_main entry points instead.
    if role in ("worker", "scheduler"):
        raise SystemError(
            f"PROCESS_ROLE={role} must not start the FastAPI HTTP application; "
            f"use python -m app.{role}_main"
        )

    # Background asyncio task references (initialized per role block)
    cleanup_task = None
    _staging_cleanup_task = None
    _pipeline_worker_task = None
    _reaper_task = None
    _export_processor_task = None
    _export_cleanup_task = None
    _outbox_dispatcher_task = None
    _outbox_reconciler_task = None

    # ── Common startup (all roles) ──
    validate_production_config()
    await validate_production_config_async()

    # Check sys.modules for banned OCR packages in cloud_api
    try:
        from app.core.deployment_profile import (
            DeploymentProfile,
            detect_deployment_profile,
        )
        if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
            loaded = loaded_local_ocr_modules()
            if loaded:
                logger.critical(
                    "cloud_api deployment detected banned modules in sys.modules: %s",
                    loaded,
                )
                raise SystemError(
                    f"Banned local OCR modules loaded in cloud_api: {loaded}"
                )
    except SystemError:
        raise
    except Exception as e:
        if is_restricted_ocr_environment():
            raise SystemError(f"OCR module isolation check failed: {e}") from e
        logger.warning("OCR module isolation check failed: %s", e)

    from app.core.ocr_profile import get_ocr_profile
    profile = get_ocr_profile()

    # Staging storage: sweep stale temp files on startup
    try:
        from app.core.log_context import log_event
        from app.services.staging_storage import async_sweep_temp_files
        swept = await async_sweep_temp_files()
        if swept:
            log_event(logger, "staging.sweep", count=swept)
    except Exception:
        logger.warning("Staging temp sweep failed (non-fatal)", exc_info=True)
    logger.info(
        "Starting 2240AI — env=%s role=%s ocr_profile=%s (gpu=%s, workers=%d, max_pdf_pages=%d)",
        settings.APP_ENV, role, profile.name, profile.use_gpu,
        profile.max_workers, profile.max_pdf_pages,
    )
    # Explicitly log which components are active per role
    if role == "web":
        logger.info("Role=%s: API serving, OCR gateway active (no worker/dispatcher)", role)
    elif role == "worker":
        logger.info("Role=%s: pipeline dispatcher, reaper, AI prewarm active (no API)", role)
    elif role == "scheduler":
        logger.info(
            "Role=%s: periodic tasks (token cleanup, staging cleanup, pomodoro, "
            "audit cleanup, export) active (no API, no worker)",
            role,
        )
    elif role == "all":
        logger.warning(
            "Role=%s: ALL components in one process (development mode). "
            "In production, use web/worker/scheduler split.",
            role,
        )

    # Log export access config
    try:
        from app.services.export.capability import log_export_config_on_startup
        log_export_config_on_startup()
    except Exception:
        logger.warning("Export config logging failed (non-fatal)", exc_info=True)

    # Log export processor status
    _has_processor = role in ("scheduler", "all")
    _has_redis = bool(settings.REDIS_URL)
    if _has_processor:
        logger.info("export_processor_enabled=true process_role=%s redis_available=%s", role, _has_redis)
    elif role == "web":
        logger.warning(
            "process_role=web export_processor_enabled=false export_processor_mode=external "
            " — pending export tasks will NOT be processed. "
            "Start a scheduler process (PROCESS_ROLE=scheduler) or use PROCESS_ROLE=all for local dev."
        )
    os.makedirs("static/formulas", exist_ok=True)
    os.makedirs("static/question-assets", exist_ok=True)
    os.makedirs(settings.EXPORT_DIR, exist_ok=True)
    await init_db()

    # Fix residual UNIQUE constraint on export_tasks.idempotency_key.
    # The phase7_export_fixes migration attempted this but failed on SQLite
    # (table-level UNIQUE constraints can't be dropped via batch_op.drop_index).
    # This runtime DDL is a belt-and-suspenders fix alongside the application-level
    # IntegrityError handler in the create_export endpoint.
    try:
        from app.core.database import engine as _db_engine
        _sync_engine = _db_engine.sync_engine
        _dialect = _sync_engine.dialect.name
        if _dialect == "sqlite":
            from sqlalchemy import inspect as _sa_inspect
            _inspector = _sa_inspect(_sync_engine)
            _ix_list = _inspector.get_indexes("export_tasks")
            # SQLite may expose the UNIQUE constraint as a unique index
            _has_unique_ix = any(
                _ix.get("column_names", []) == ["idempotency_key"] and _ix.get("unique")
                for _ix in _ix_list
            )
            if _has_unique_ix:
                # Recreate table without the UNIQUE constraint using Alembic batch mode
                from alembic.runtime.migration import MigrationContext

                from alembic import op
                _conn = _sync_engine.connect()
                _ctx = MigrationContext.configure(_conn)
                _op = op.Operations(_ctx)
                with _op.batch_alter_table("export_tasks") as _batch:
                    # Drop all unique indexes on idempotency_key
                    for _ix in _ix_list:
                        if _ix.get("column_names", []) == ["idempotency_key"]:
                            _batch.drop_index(_ix["name"])
                    # Recreate non-unique index
                    _batch.create_index("ix_export_tasks_idempotency_key", ["idempotency_key"])
                _conn.commit()
                _conn.close()
                logger.info("Fixed residual UNIQUE constraint on export_tasks.idempotency_key (SQLite)")
        elif _dialect == "postgresql":
            # PostgreSQL: drop the UNIQUE constraint if it exists and replace with index
            async with async_session() as _s:
                _row = (await _s.execute(text("""
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'export_tasks'::regclass
                    AND conname LIKE '%idempotency_key%'
                    AND contype = 'u'
                """))).scalar_one_or_none()
                if _row:
                    # Constraint names come from PostgreSQL metadata, but still
                    # escape identifier quotes before interpolating into DDL.
                    _quoted_constraint = str(_row).replace('"', '""')
                    await _s.execute(
                        text(
                            f'ALTER TABLE export_tasks DROP CONSTRAINT "{_quoted_constraint}"'
                        )
                    )
                    await _s.execute(text(
                        'CREATE INDEX IF NOT EXISTS ix_export_tasks_idempotency_key '
                        'ON export_tasks (idempotency_key)'
                    ))
                    await _s.commit()
                    logger.info("Fixed residual UNIQUE constraint on export_tasks.idempotency_key (PostgreSQL)")
    except Exception as _exc:
        logger.warning(
            "Failed to fix idempotency_key UNIQUE constraint (%s: %s) "
            "(non-fatal, application-level fallback active)",
            type(_exc).__name__, _exc,
        )

    # Schema divergence diagnostic: detect missing runtime-DDL columns on PostgreSQL.
    # Lightweight startup check — warns if known columns are absent.
    try:
        from app.core.database import engine
        _sync_engine = engine.sync_engine
        if _sync_engine.dialect.name == "postgresql":
            _runtime_ddl_checks: dict[str, list[str]] = {
                "questions": ["question_hash", "sync_uuid", "sync_version"],
                "question_imports": ["question_hash", "duplicate_status",
                                   "duplicate_of_question_id", "duplicate_of_import_id"],
                "users": ["is_banned", "deleted_at"],
            }
            _divergence: list[str] = []
            async with async_session() as _s:
                for _tbl, _cols in _runtime_ddl_checks.items():
                    try:
                        _row = (await _s.execute(
                            text("SELECT column_name FROM information_schema.columns "
                                 "WHERE table_name=:tbl AND column_name=ANY(:cols)"),
                            {"tbl": _tbl, "cols": _cols},
                        )).all()
                        _found = {r[0] for r in _row}
                        for _c in _cols:
                            if _c not in _found:
                                _divergence.append(f"{_tbl}.{_c}")
                    except Exception:
                        pass
            if _divergence:
                logger.warning(
                    "Schema divergence (runtime DDL not in Alembic): %s",
                    ", ".join(_divergence),
                )
            else:
                logger.debug("Schema divergence check: all runtime-DDL columns present")
    except Exception:
        logger.debug("Schema divergence check skipped (not PostgreSQL or transient)")
    try:
        async with async_session() as db:
            created_admin = await ensure_dev_super_admin(db, settings.APP_ENV)
            await db.commit()
            if created_admin:
                logger.info("Development super admin initialized")
    except Exception as e:
        logger.warning("Development super admin init failed (non-fatal): %s", e)

    # Seed default recommendation strategies (idempotent, fills only empty fields)
    try:
        from app.services.recommendation_seed_service import (
            seed_default_recommendation_strategies,
        )

        async with async_session() as db:
            seed_result = await seed_default_recommendation_strategies(db, force=False)
            await db.commit()
            if any(v for v in seed_result.values()):
                logger.info(
                    "Recommendation strategies seeded: created=%s updated=%s skipped=%s",
                    seed_result.get("created"), seed_result.get("updated"),
                    seed_result.get("skipped"),
                )
    except Exception as e:
        logger.warning("Recommendation strategy seed failed (non-fatal): %s", e)

    # AI model config self-check (common)
    try:
        from app.services.health_check_service import check_ai_model_config

        async with async_session() as db:
            ai_check = await check_ai_model_config(db)
            if ai_check.severity == "error":
                logger.error(
                    "AI_MODEL_NOT_CONFIGURED: admin_ai_model_configs has no enabled model; "
                    "OCR AI repair / VL fallback may be unavailable"
                )
            elif ai_check.severity == "warning":
                logger.warning(
                    "AI_MODEL_DEFAULT_MISSING: enabled AI models exist (%d) but no default model is configured; "
                    "providers=%s features=%s",
                    ai_check.enabled_count, ai_check.providers, ai_check.features,
                )
            else:
                logger.info(
                    "AI model config healthy: enabled_count=%d default_count=%d providers=%s features=%s",
                    ai_check.enabled_count, ai_check.default_count,
                    ai_check.providers, ai_check.features,
                )
    except Exception as e:
        logger.warning("AI model config self-check failed (non-fatal, DB may not be ready): %s", e)

    # ── Resource references (initialized to None, populated by role) ──
    cleanup_task: asyncio.Task | None = None
    _staging_cleanup_task: asyncio.Task | None = None
    _ocr_gateway = None

    # ── Role-aware BoundedExecutors ──
    try:
        from app.core.deployment_profile import (
            DeploymentProfile,
            detect_deployment_profile,
        )
        from app.core.executor_registry import init_executor_registry
        from app.core.executors import init_executors_for_role

        _deploy_profile = detect_deployment_profile()
        _executors = init_executors_for_role(
            role,
            is_production=(_deploy_profile == DeploymentProfile.CLOUD_API),
        )
        init_executor_registry(_executors)
        logger.info(
            "Executors initialized for role=%s: %s",
            role, {k: v.name for k, v in _executors.items()},
        )
    except Exception as e:
        _report_startup_failure("Executors", e)
    _pipeline_worker_task: asyncio.Task | None = None
    _reaper_task: asyncio.Task | None = None
    _lag_monitor_task: asyncio.Task | None = None

    # Event-loop lag monitor (always runs — lightweight, all roles)
    _lag_monitor_task = asyncio.create_task(
        _event_loop_lag_monitor(), name="event-loop-lag-monitor"
    )

    # ── Role: web — HTTP + enqueue ──
    # Periodic cleanup tasks (token, staging) belong exclusively to the
    # scheduler role. The web role only handles request serving and enqueue.
    if role in ("web", "all"):
        # Initialize OCR Gateway (needed for API enqueue endpoints)
        try:
            import httpx

            from app.core.ocr_runtime_config import get_runtime_config
            from app.features.ocr_gateway import OCRGateway
            from app.services.ocr_worker_client import create_ocr_worker_client

            cfg = get_runtime_config()
            if cfg.enabled:
                # Create a shared httpx.AsyncClient for all OCR HTTP
                # communication.  Ownership remains in this lifespan block;
                # the worker client will NOT close it on shutdown.
                _ocr_shared_http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        connect=cfg.remote_connect_timeout_sec,
                        read=cfg.remote_read_timeout_sec,
                        write=cfg.remote_connect_timeout_sec,
                        pool=cfg.remote_connect_timeout_sec,
                    ),
                    limits=httpx.Limits(
                        max_keepalive_connections=cfg.remote_max_concurrency,
                        max_connections=cfg.remote_max_concurrency,
                    ),
                )
                worker_client = create_ocr_worker_client(
                    cfg, http_client=_ocr_shared_http_client,
                )
                from app.core.deployment_profile import detect_deployment_profile
                _ocr_gateway = OCRGateway(
                    mode="gateway",
                    profile=detect_deployment_profile(),
                    worker_client=worker_client,
                )
                from app.services.ocr_service import set_gateway
                set_gateway(_ocr_gateway)
                logger.info(
                    "OCR Gateway initialized (role=%s mode=gateway exec_backend=%s profile=%s env=%s)",
                    role, cfg.execution_backend, cfg.profile, cfg.environment,
                )
            else:
                logger.info("OCR not enabled, skipping Gateway initialization")
        except Exception as e:
            _report_startup_failure("OCR Gateway", e)

    # ── Role: worker — pipeline processing + AI prewarm ──
    if role in ("worker", "all"):
        try:
            from app.services.task_queue_worker import run_dispatcher_v2
            _pipeline_worker_task = asyncio.create_task(
                run_dispatcher_v2(), name="pipeline-dispatcher-v2"
            )
        except Exception as e:
            _report_startup_failure("Pipeline dispatcher v2", e)

        try:
            from app.services.task_queue_worker import run_reaper_loop_v2
            _reaper_task = asyncio.create_task(
                run_reaper_loop_v2(), name="task-reaper-v2"
            )
        except Exception as e:
            _report_startup_failure("Reaper", e)

        # AI prewarm worker — uses DurableTaskQueue (moved from scheduler per P0-2)
        try:
            from app.services.ai_prewarm_worker import start_worker
            await start_worker()
            logger.info("AI prewarm worker started")
        except Exception as e:
            _report_startup_failure("AI prewarm worker", e)

    # ── Role: scheduler — periodic background tasks ──
    if role in ("scheduler", "all"):
        try:
            from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler
            await audit_log_cleanup_scheduler.start()
            logger.info("Audit log cleanup scheduler started")
        except Exception as e:
            logger.warning("Audit log cleanup scheduler start failed (non-fatal): %s", e)

        try:
            from app.services.recommendation_metrics_scheduler import (
                recommendation_metrics_scheduler,
            )
            await recommendation_metrics_scheduler.start()
            logger.info("Recommendation metrics scheduler started")
        except Exception as e:
            logger.warning("Recommendation metrics scheduler start failed (non-fatal): %s", e)

        # Periodic cleanup tasks belong in the scheduler role only
        cleanup_task = asyncio.create_task(_periodic_token_cleanup(), name="token-cleanup")
        _staging_cleanup_task = asyncio.create_task(
            _periodic_staging_cleanup(), name="staging-cleanup"
        )

        # Export processor + cleanup (scheduler role only)
        _export_processor_task = asyncio.create_task(
            _periodic_export_processor(), name="export-processor"
        )
        _export_cleanup_task = asyncio.create_task(
            _periodic_export_cleanup(), name="export-cleanup"
        )

        # Outbox dispatcher + reconciler (scheduler role only)
        # Reads pending outbox records and enqueues them to Redis v2 queue
        try:
            from app.services.outbox_service import (
                run_outbox_dispatcher,
                run_outbox_reconciler,
            )
            from app.services.task_queue_service import task_queue

            async def _enqueue_from_outbox(task_id: str, task_type: str, payload: dict) -> object:
                return await task_queue.enqueue_v2(
                    task_type, payload, task_id=task_id,
                )

            _outbox_dispatcher_task = asyncio.create_task(
                run_outbox_dispatcher(_enqueue_from_outbox), name="outbox-dispatcher"
            )
            _outbox_reconciler_task = asyncio.create_task(
                run_outbox_reconciler(), name="outbox-reconciler"
            )
            logger.info("Outbox dispatcher + reconciler started")
        except Exception as e:
            logger.warning("Outbox dispatcher start failed (non-fatal): %s", e)

    # Start resource reservation orphan reconciler (all roles)
    try:
        from app.core.resource_guard import resource_guard
        await resource_guard.start_orphan_reconciler()
    except Exception as e:
        logger.warning("Orphan reconciler start failed (non-fatal): %s", e)

    # ── Yield — application serves requests ──
    try:
        yield
    finally:
        # ══════════════════════════════════════════
        # Shutdown — ordered, resilient, logged
        # ══════════════════════════════════════════
        logger.info("=== Shutdown sequence started (role=%s) ===", role)

        # 1. Graceful shutdown for v2 worker: drain → shield → cancel
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
        else:
            # Non-worker roles still drain if any v1 tasks are active
            try:
                from app.services.task_queue_worker import set_draining_v2
                await set_draining_v2()
            except Exception as e:
                logger.warning("set_draining_v2 failed: %s", e)

        # 2. Stop event-loop lag monitor
        if _lag_monitor_task and not _lag_monitor_task.done():
            _lag_monitor_task.cancel()
            try:
                await _lag_monitor_task
            except asyncio.CancelledError:
                pass

        # 3b. Signal export processor to drain
        if role in ("scheduler", "all"):
            try:
                from app.services.export.processor import stop_processor
                await stop_processor()
                logger.info("export_processor_stopped role=%s", role)
            except Exception as e:
                logger.warning("Export processor stop signal failed: %s", e)

        # 4. Cancel and await background asyncio tasks with grace timeout
        _shutdown_tasks = []
        if cleanup_task and not cleanup_task.done():
            cleanup_task.cancel()
            _shutdown_tasks.append(("token-cleanup", cleanup_task))
        if _pipeline_worker_task and not _pipeline_worker_task.done():
            _pipeline_worker_task.cancel()
            _shutdown_tasks.append(("pipeline-dispatcher-v2", _pipeline_worker_task))
        if _reaper_task and not _reaper_task.done():
            _reaper_task.cancel()
            _shutdown_tasks.append(("task-reaper-v2", _reaper_task))
        if _staging_cleanup_task and not _staging_cleanup_task.done():
            _staging_cleanup_task.cancel()
            _shutdown_tasks.append(("staging-cleanup", _staging_cleanup_task))
        if _export_processor_task and not _export_processor_task.done():
            _export_processor_task.cancel()
            _shutdown_tasks.append(("export-processor", _export_processor_task))
        if _export_cleanup_task and not _export_cleanup_task.done():
            _export_cleanup_task.cancel()
            _shutdown_tasks.append(("export-cleanup", _export_cleanup_task))
        if _outbox_dispatcher_task and not _outbox_dispatcher_task.done():
            _outbox_dispatcher_task.cancel()
            _shutdown_tasks.append(("outbox-dispatcher", _outbox_dispatcher_task))
        if _outbox_reconciler_task and not _outbox_reconciler_task.done():
            _outbox_reconciler_task.cancel()
            _shutdown_tasks.append(("outbox-reconciler", _outbox_reconciler_task))

        if _shutdown_tasks:
            task_names = {task: name for name, task in _shutdown_tasks}
            done, pending = await asyncio.wait(task_names, timeout=30)
            for task in done:
                name = task_names[task]
                if task.cancelled():
                    logger.info("Task %s: cancelled", name)
                    continue
                try:
                    exc = task.exception()
                except asyncio.CancelledError:
                    logger.info("Task %s: cancelled", name)
                    continue
                if exc is None:
                    logger.info("Task %s: completed after cancel", name)
                else:
                    logger.warning("Task %s: cancel error: %s", name, exc)
            for task in pending:
                logger.warning(
                    "Task %s: did not stop within shared 30s grace period",
                    task_names[task],
                )
                task.cancel()

        # 4. Stop schedulers (if running in this role)
        if role in ("scheduler", "all"):
            try:
                from app.services.audit_cleanup_scheduler import (
                    audit_log_cleanup_scheduler,
                )
                await audit_log_cleanup_scheduler.stop()
                logger.info("Audit log cleanup scheduler stopped")
            except Exception as e:
                logger.warning("Audit log cleanup scheduler stop error: %s", e)

            try:
                from app.services.recommendation_metrics_scheduler import (
                    recommendation_metrics_scheduler,
                )
                await recommendation_metrics_scheduler.stop()
                logger.info("Recommendation metrics scheduler stopped")
            except Exception as e:
                logger.warning("Recommendation metrics scheduler stop error: %s", e)

        # 4b. Stop AI prewarm worker (runs in worker role, not scheduler)
        if role in ("worker", "all"):
            try:
                from app.services.ai_prewarm_worker import stop_worker
                await stop_worker()
                logger.info("AI prewarm worker stopped")
            except Exception as e:
                logger.warning("AI prewarm worker stop error: %s", e)

        # 5. Shutdown formula render ProcessPoolExecutor (common)
        try:
            from app.services.formula_graph_spec_renderer import (
                shutdown_formula_render_pool,
            )
            await asyncio.wait_for(
                asyncio.to_thread(
                    shutdown_formula_render_pool,
                    wait=True,
                    cancel_futures=False,
                ),
                timeout=30,
            )
            logger.info("Formula render pool shut down")
        except TimeoutError:
            logger.warning("Formula render pool shutdown timed out, forcing non-blocking")
            try:
                shutdown_formula_render_pool(wait=False, cancel_futures=True)
            except Exception as exc2:
                logger.exception("Formula render pool forced shutdown error: %s", exc2)
        except Exception:
            logger.exception("Formula render pool shutdown error")

        # 6. Shutdown OCR infrastructure (only if this role uses it)
        # Cloud profile: skip OCR executor shutdown — it imports local PaddleOCR modules.
        if role in ("web", "all"):
            try:
                from app.core.deployment_profile import (
                    DeploymentProfile,
                    detect_deployment_profile,
                )
                if detect_deployment_profile() != DeploymentProfile.CLOUD_API:
                    from app.services.ocr_executor_service import ocr_executor
                    await asyncio.wait_for(
                        ocr_executor.shutdown(wait=True),
                        timeout=30,
                    )
                    logger.info("OCR executor shut down")
                else:
                    logger.info("OCR executor shutdown skipped (cloud profile)")
            except TimeoutError:
                logger.warning("OCR executor shutdown timed out")
            except Exception:
                logger.exception("OCR executor shutdown error")

            try:
                from app.features.ocr_gateway import OCRGateway
                if _ocr_gateway is not None:
                    await _ocr_gateway.shutdown()
                    logger.info("OCR Gateway shut down")
            except Exception as e:
                logger.warning("OCR Gateway shutdown error: %s", e)

            # Close the shared httpx.AsyncClient used by OCR
            try:
                _ocr_shared_http_client
            except NameError:
                pass
            else:
                if _ocr_shared_http_client is not None:
                    await _ocr_shared_http_client.aclose()
                    logger.info("OCR shared httpx client closed")

        # 7. BoundedExecutors shutdown
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

        # 8. Close Redis client from task queue (common)
        try:
            from app.services.task_queue_service import task_queue
            await task_queue.close()
            logger.info("Task queue Redis client closed")
        except Exception as e:
            logger.warning("Task queue close error: %s", e)

        # 9. Dispose SQLAlchemy engine
        try:
            from app.core.database import engine
            await engine.dispose()
            logger.info("SQLAlchemy engine disposed")
        except Exception as e:
            logger.warning("Engine dispose error: %s", e)

        # ── Diagnostics ──
        # Stop resource reservation orphan reconciler
        try:
            from app.core.resource_guard import resource_guard
            await resource_guard.stop_orphan_reconciler()
        except Exception as e:
            logger.warning("Orphan reconciler stop error: %s", e)

        logger.info("=== Shutdown sequence completed (role=%s) ===", role)
        try:
            import multiprocessing
            children = multiprocessing.active_children()
            if children:
                logger.warning(
                    "Active child processes after shutdown: %s",
                    [c.pid for c in children],
                )
            else:
                logger.info("No active child processes after shutdown")
        except Exception as e:
            logger.warning("Active children check failed: %s", e)


_production_mode = settings.APP_ENV.strip().lower() == "production"
app = FastAPI(
    title="2240AI",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _production_mode else "/docs",
    redoc_url=None if _production_mode else "/redoc",
    openapi_url=None if _production_mode else "/openapi.json",
)

# --- 中间件 ---

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=()",
    )
    if _production_mode:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    if request.url.path.startswith(("/api/v1/auth", "/api/admin/v1/auth")):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Pragma", "no-cache")
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    from app.core.log_context import (
        bind_log_context,
        clear_log_context,
        generate_request_id,
        generate_trace_id,
        log_event,
    )

    access_logger = logging.getLogger("app.access")

    # Read or generate trace/request IDs
    trace_id = request.headers.get("x-trace-id") or generate_trace_id()
    request_id = request.headers.get("x-request-id") or generate_request_id()

    start = time.time()
    try:
        bind_log_context(trace_id=trace_id, request_id=request_id)

        # Extract safe request metadata (no Authorization, no full query values)
        try:
            query_keys = list(request.query_params.keys()) if request.query_params else []
        except Exception:
            query_keys = []
        client_ip = request.client.host if request.client else "-"
        user_agent = request.headers.get("user-agent", "-")[:200]
        content_type = request.headers.get("content-type", "-")
        content_length = request.headers.get("content-length", "-")

        log_event(
            access_logger,
            "http.request.start",
            method=request.method,
            path=request.url.path,
            query_keys=query_keys,
            client_ip=client_ip,
            user_agent=user_agent,
            content_type=content_type,
            content_length=content_length,
        )

        response = await call_next(request)
        elapsed_ms = round((time.time() - start) * 1000)

        # Set trace headers on the response (covers both success and exception-handler responses)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id

        log_event(
            access_logger,
            "http.request.finish",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=elapsed_ms,
            response_content_length=response.headers.get("content-length", "-"),
        )
        return response
    except Exception as exc:
        elapsed_ms = round((time.time() - start) * 1000)
        log_event(
            access_logger,
            "http.request.error",
            level="error",
            method=request.method,
            path=request.url.path,
            duration_ms=elapsed_ms,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
        )
        raise
    finally:
        clear_log_context()




@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    """Handle ApiError with structured JSON response."""
    status_code = _api_error_status(exc.code)
    return JSONResponse(
        status_code=status_code,
        content=exc.to_dict(),
    )


def _api_error_status(code: ErrorCode) -> int:
    codes_503 = {
        ErrorCode.QUEUE_UNAVAILABLE,
        ErrorCode.DB_UNAVAILABLE,
        ErrorCode.STAGING_UNAVAILABLE,
        ErrorCode.OCR_PROVIDER_ERROR,
    }
    codes_429 = {
        ErrorCode.QUEUE_FULL,
        ErrorCode.RESOURCE_QUEUE_FULL,
        ErrorCode.OCR_RATE_LIMIT,
        ErrorCode.AI_RATE_LIMIT,
        ErrorCode.RESOURCE_DB_POOL_BUSY,
    }
    codes_409 = {
        ErrorCode.DB_CONFLICT,
        ErrorCode.TASK_FENCING_REJECTED,
    }
    codes_404 = {
        ErrorCode.TASK_NOT_FOUND,
        ErrorCode.STAGING_OBJECT_MISSING,
    }
    codes_422 = {
        ErrorCode.REVIEW_REQUIRED,
    }

    if code in codes_503:
        return 503
    if code in codes_429:
        return 429
    if code in codes_409:
        return 409
    if code in codes_404:
        return 404
    if code in codes_422:
        return 422
    return 500


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # 兜底：未被 HTTPException 包装的异常，必须返回 JSON。
    # 否则前端 wx.uploadFile 拿到的是 "Internal Server Error" 纯文本，
    # JSON.parse 直接抛 "Unexpected token I in JSON at position 0"，错误信息全丢。
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)

    # Recover trace context (may have been cleared by middleware finally block)
    trace_id = request.headers.get("x-trace-id", "")
    request_id = request.headers.get("x-request-id", "")

    try:
        from app.core.log_context import bind_log_context, log_event
        if trace_id or request_id:
            bind_log_context(trace_id=trace_id, request_id=request_id)
        log_event(
            logging.getLogger("app.access"),
            "http.request.error",
            level="error",
            method=request.method,
            path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
        )
    except Exception:
        pass  # Never let logging crash the exception handler

    safe_detail = "服务器内部错误"
    if not _production_mode:
        safe_detail = f"{type(exc).__name__}: {exc}"

    response = JSONResponse(
        status_code=500,
        content={"detail": safe_detail, "code": "INTERNAL_ERROR"},
    )
    if trace_id:
        response.headers["X-Trace-ID"] = trace_id
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


# --- 健康检查和可观测性 ---

# Event-loop lag monitor (driven by lifespan task)
_elapsed_monitor_event_loop_lag_ms: float = 0.0


async def _event_loop_lag_monitor(interval: float = 1.0) -> None:
    """Measure event-loop scheduling delay by scheduling a callback.

    The actual delay between scheduled and actual wake-up time is a
    proxy for event-loop congestion. Updated in a module-level global.
    """
    global _elapsed_monitor_event_loop_lag_ms
    while True:
        scheduled = time.perf_counter()
        await asyncio.sleep(interval)
        actual = time.perf_counter()
        _elapsed_monitor_event_loop_lag_ms = round((actual - scheduled - interval) * 1000, 2)


def _get_db_pool_metrics() -> dict:
    """Return SQLAlchemy async engine pool status (sync, for health endpoint)."""
    try:
        from app.core.database import engine

        sync_engine = engine.sync_engine
        pool = sync_engine.pool
        return {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
        }
    except Exception as e:
        return {"error": str(e)}


# ── OCR readiness hysteresis ──
# Track consecutive remote OCR health-check failures.
# Crosses the degraded threshold at 3 consecutive failures.
_ocr_remote_consecutive_failures: int = 0


@app.get("/health")
async def health():
    """Legacy health endpoint — returns ok regardless of dependency state."""
    return {"status": "ok", "env": settings.APP_ENV}


@app.get("/health/live")
async def live_health():
    """Liveness probe — only checks the process is responsive.

    Suitable for container orchestration liveness checks.
    """
    return {"status": "ok"}


@app.get("/health/ready")
async def ready_health():
    """Readiness probe — checks all critical dependencies are healthy.

    Returns 503 (via JSONResponse status_code) when any critical
    dependency is unavailable. Non-critical issues are reported as
    "degraded" without failing the probe.

    Critical checks (→ 503 on failure):
    - PostgreSQL connectivity
    - Redis connectivity (mandatory in production, optional in dev)
    - Alembic at head revision
    - Staging directory writable
    - Role-specific dependencies
    - OCR configuration (in production — illegal config is a probe failure)
    - Worker draining (stop the load balancer)

    Non-critical (degraded, does not fail probe):
    - OCR external configuration (development only)
    - Queue status
    """
    db_ok = await _check_database()
    redis_ok = await _check_redis()
    alembic_ok = await _check_alembic_head()
    staging_ok = await _check_staging()
    staging_space = await _check_staging_space()
    role_ok = await _check_role_deps()

    # Non-critical checks (informational, don't fail probe)
    ocr_status = await _check_ocr_config()
    queue_status = await _check_queue()

    # Draining is critical — stop the load balancer from sending requests
    try:
        from app.services.task_queue_worker import is_draining_v2
        draining = is_draining_v2()
    except Exception:
        draining = False

    checks = {
        "database": "ok" if db_ok else "unavailable",
        "db_pool": _get_db_pool_metrics(),
        "alembic": "ok" if alembic_ok else "stale",
        "staging": "ok" if staging_ok else "unavailable",
        "role_deps": "ok" if role_ok else "unavailable",
        "event_loop_lag_ms": _elapsed_monitor_event_loop_lag_ms,
        "draining": "ok" if not draining else "draining",
    }
    if settings.REDIS_URL or _production_mode:
        checks["redis"] = "ok" if redis_ok else "unavailable"
    if ocr_status:
        checks["ocr"] = ocr_status
    if queue_status:
        checks["queue"] = queue_status
    if staging_space:
        checks["staging_space"] = staging_space

    critical_failures = [
        k for k, v in checks.items()
        if v == "unavailable" and k in (
            "database", "redis", "alembic", "staging", "role_deps", "ocr",
        )
    ]
    # Draining is also critical — produces 503 even though value is "draining"
    if draining:
        critical_failures.append("draining")
    all_ok = len(critical_failures) == 0

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "status": "ok" if all_ok else "unavailable",
            "degraded": ocr_status == "degraded" or queue_status == "degraded",
            "checks": checks,
        },
    )


async def _check_database() -> bool:
    """Check PostgreSQL is reachable."""
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _check_redis() -> bool:
    """Check Redis is reachable and responsive.

    In production, Redis is mandatory — returns False if not configured.
    """
    if not settings.REDIS_URL:
        from app.core.deployment_profile import (
            DeploymentProfile,
            detect_deployment_profile,
        )
        try:
            if detect_deployment_profile() == DeploymentProfile.CLOUD_API or _production_mode:
                return False
        except Exception:
            return False
        return True  # Not configured in dev — not a failure
    try:
        from app.core.cache import cache
        await cache.set("health:ping", "pong", ttl=10)
        pong = await cache.get("health:ping")
        return pong == "pong"
    except Exception:
        return False


async def _check_alembic_head() -> bool:
    """Verify the database migration is at the head revision."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        async with async_session() as session:
            row = (await session.execute(
                text("SELECT version_num FROM alembic_version")
            )).scalar_one_or_none()
            db_revision = row or ""

        alembic_cfg = Config()
        alembic_cfg.set_main_option(
            "script_location",
            os.path.join(os.path.dirname(__file__), "../alembic"),
        )
        script = ScriptDirectory.from_config(alembic_cfg)
        head_revision = script.get_current_head()

        return bool(db_revision and head_revision and db_revision == head_revision)
    except Exception:
        return False


async def _check_staging() -> bool:
    """Check the staging directory is writable."""
    from app.services.staging_storage import _STAGING_DIR
    try:
        path = _STAGING_DIR
        path.mkdir(parents=True, exist_ok=True)
        return os.access(str(path), os.W_OK)
    except Exception:
        return False


async def _check_staging_space() -> dict:
    """Return staging directory space info (free bytes, total bytes, used percent).

    Returns empty dict on failure (non-critical, informational only).
    """
    from app.services.staging_storage import _STAGING_DIR
    try:
        st = os.statvfs(str(_STAGING_DIR))
        free_bytes = st.f_frsize * st.f_bavail
        total_bytes = st.f_frsize * st.f_blocks
        used_percent = ((total_bytes - free_bytes) / total_bytes * 100) if total_bytes > 0 else 0
        return {
            "staging_free_bytes": free_bytes,
            "staging_total_bytes": total_bytes,
            "staging_used_percent": round(used_percent, 1),
        }
    except Exception:
        return {}


async def _check_role_deps() -> bool:
    """Check role-specific dependencies are available.

    Web:
      - If cloud_api, verify no local paddle/paddleocr in sys.modules
      - (DB, Redis, staging checked separately)

    Worker:
      - Must not be draining
      - If cloud_api, OCR execution backend must not be local_process

    Scheduler:
      - Pomodoro scheduler (removed)
      - Audit log cleanup scheduler loop running (if AUDIT_LOG_CLEANUP_ENABLED)
    """
    role = settings.PROCESS_ROLE
    is_cloud = is_restricted_ocr_environment()

    if role == "web":
        if is_cloud and loaded_local_ocr_modules():
            logger.warning(
                "role_deps: cloud web role detected banned OCR modules in sys.modules"
            )
            return False
        return True

    if role == "worker":
        # Draining check
        try:
            from app.services.task_queue_worker import is_draining_v2
            if is_draining_v2():
                logger.warning("role_deps: worker is draining")
                return False
        except Exception:
            pass

        # Cloud worker must not use local_process backend
        if is_cloud:
            exec_backend = (settings.OCR_EXECUTION_BACKEND or "").lower()
            if exec_backend == "local_process":
                logger.warning("role_deps: cloud worker with local_process OCR backend")
                return False

        return True

    if role == "scheduler":


        # Check audit log cleanup scheduler running (if enabled)
        try:
            from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler
            if settings.AUDIT_LOG_CLEANUP_ENABLED and not audit_log_cleanup_scheduler._running:
                logger.warning("role_deps: audit log cleanup scheduler not running")
                return False
        except ImportError:
            logger.warning("role_deps: audit_cleanup_scheduler import failed")
            return False
        except Exception as e:
            logger.warning("role_deps: audit cleanup scheduler check error: %s", e)
            return False

        return True

    return False  # Unknown role → fail probe


async def _check_ocr_config() -> str | None:
    """Check OCR configuration. Returns status string or None if not applicable.

    Returns "ok", "degraded", "unavailable", or None (no OCR configured).

    Config errors → immediate "unavailable" in cloud/production, "degraded" in dev.
    Remote connectivity errors → hysteresis: 3 consecutive failures → "degraded".
    Local paddle modules in cloud → "unavailable".
    """
    if not settings.OCR_ENABLED:
        return None

    exec_backend = (settings.OCR_EXECUTION_BACKEND or "").lower()
    issues: list[str] = []

    # Check for local paddle in sys.modules under cloud → immediate unavailable
    if exec_backend == "local_process":
        issues.append("local_process backend not allowed")

    if settings.OCR_USE_GPU is not False:
        issues.append("GPU should be disabled")

    if exec_backend == "paddlex_http" and not settings.OCR_REMOTE_TOKEN:
        issues.append("remote token not set")

    is_cloud = is_restricted_ocr_environment()

    # Local paddle in sys.modules under cloud → unavailable
    if is_cloud and loaded_local_ocr_modules():
        issues.append("local paddle modules loaded in cloud deployment")

    if issues:
        if is_cloud:
            return "unavailable"
        return "degraded"

    # Remote connectivity check with hysteresis (only for remote backends)
    if exec_backend == "paddlex_http":
        global _ocr_remote_consecutive_failures
        remote_ok = await _check_ocr_remote_connectivity()
        if remote_ok:
            _ocr_remote_consecutive_failures = 0
            return "ok"
        else:
            _ocr_remote_consecutive_failures += 1
            if _ocr_remote_consecutive_failures >= 3:
                return "degraded"
            # Transient failure — still ok until threshold
            return "ok"

    return "ok"


async def _check_ocr_remote_connectivity() -> bool:
    """Lightweight health check against remote OCR endpoint.

    Returns True if reachable, False on any failure.
    Does NOT update hysteresis counters — caller is responsible.
    """
    if not settings.OCR_ENABLED:
        return True
    exec_backend = (settings.OCR_EXECUTION_BACKEND or "").lower()
    if exec_backend != "paddlex_http" or not settings.OCR_REMOTE_URL:
        return True
    try:
        import httpx
        url = settings.OCR_REMOTE_URL
        timeout = httpx.Timeout(settings.OCR_REMOTE_HEALTH_TIMEOUT_SEC)
        headers = {}
        if settings.OCR_REMOTE_TOKEN:
            header_name = getattr(settings, "OCR_REMOTE_AUTH_HEADER", "Authorization")
            scheme = getattr(settings, "OCR_REMOTE_AUTH_SCHEME", "Bearer")
            headers[header_name] = f"{scheme} {settings.OCR_REMOTE_TOKEN}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            respiratory = url.rstrip("/") + "/health"
            resp = await client.get(respiratory, headers=headers)
            return resp.status_code < 500
    except Exception:
        return False


async def _check_queue() -> str | None:
    """Check durable queue health.

    Returns "ok" if queue is healthy, "degraded" if queue depth is high,
    "unavailable" if Redis is unreachable in production (no hysteresis
    for critical infrastructure deps), or None if Redis not configured.
    """
    if not settings.REDIS_URL:
        return None
    try:
        from app.services.task_queue_service import task_queue
        total = 0
        for tt in ("import_pipeline", "image_pipeline", "excel_pipeline"):
            total += await task_queue.ready_length_v2(tt)
            total += await task_queue.processing_length_v2(tt)
        if total > 100:
            return "degraded"
        return "ok"
    except Exception:
        # Redis error is a critical infrastructure failure — not "degraded"
        if _production_mode:
            return "unavailable"
        return "degraded"


# --- 路由（聚合 Router） ---


@app.get("/health/metrics")
async def metrics_endpoint():
    """Prometheus-compatible metrics endpoint.

    Returns text/plain metrics for scraping by Prometheus or similar.
    Aggregates: task queue state, system resources, event-loop lag,
    DB pool, SSE connections, scheduler stats.
    """
    from app.core.resource_guard import resource_guard
    from app.services.task_queue_service import queue_metrics

    lines: list[str] = []
    _append = lines.append

    # ── Task queue metrics ──
    task_types = ["import_pipeline", "image_pipeline", "excel_pipeline"]
    try:
        from app.services.task_queue_service import task_queue
        for tt in task_types:
            ready = await task_queue.ready_length_v2(tt)
            processing = await task_queue.processing_length_v2(tt)
            retry_count = await task_queue.retry_length_v2(tt)
            dead = await task_queue.dead_length_v2(tt)
            corrupt = await task_queue.corrupt_length_v2(tt)
            oldest_age = await task_queue.oldest_ready_age_v2(tt)
            _append(f'task_queue_ready{{type="{tt}"}} {ready}')
            _append(f'task_queue_processing{{type="{tt}"}} {processing}')
            _append(f'task_queue_retry{{type="{tt}"}} {retry_count}')
            _append(f'task_queue_dead{{type="{tt}"}} {dead}')
            _append(f'task_queue_corrupt{{type="{tt}"}} {corrupt}')
            _append(f'task_queue_oldest_ready_age_seconds{{type="{tt}"}} {oldest_age}')
    except Exception:
        for tt in task_types:
            _append(f'task_queue_ready{{type="{tt}"}} 0')
            _append(f'task_queue_processing{{type="{tt}"}} 0')
            _append(f'task_queue_retry{{type="{tt}"}} 0')
            _append(f'task_queue_dead{{type="{tt}"}} 0')
            _append(f'task_queue_corrupt{{type="{tt}"}} 0')
            _append(f'task_queue_oldest_ready_age_seconds{{type="{tt}"}} 0')

    # Cumulative counters from queue_metrics dict
    for key in ("lease_renewal_failure", "duplicate_enqueue_prevented",
                "reaper_reclaimed", "owner_fencing_rejected",
                "enqueue_rejected", "dead_purge_count", "corrupt_cleaned"):
        _append(f'task_queue_{key} {queue_metrics.get(key, 0)}')

    # ── System resource metrics ──
    sys_metrics = resource_guard.get_system_metrics()
    _append(f'system_rss_mb {sys_metrics.rss_mb:.1f}')
    _append(f'system_available_memory_mb {sys_metrics.available_memory_mb:.1f}')
    _append(f'system_active_pipelines {sys_metrics.active_pipelines}')
    _append(f'system_event_loop_lag_ms {_elapsed_monitor_event_loop_lag_ms:.2f}')

    # ── OCR Gateway / circuit breaker metrics ──
    try:
        from app.services.ocr_service import get_gateway
        gateway = get_gateway()
        if gateway is not None:
            wm = gateway.worker_metrics
            _append(f'ocr_circuit_state{{backend="{wm.get("backend","?")}"}} 1')
            state = wm.get("circuit_state", "unknown")
            _append(f'ocr_circuit{{backend="{wm.get("backend","?")}",state="{state}"}} 1')
            _append(f'ocr_circuit_breaker_rejected_total '
                    f'{wm.get("circuit_breaker_rejected", 0)}')
            _append(f'ocr_circuit_breaker_trips_total '
                    f'{wm.get("circuit_breaker_trips", 0)}')
            _append(f'ocr_accepted_total {wm.get("accepted", 0)}')
            _append(f'ocr_failed_total {wm.get("failed", 0)}')
            _append(f'ocr_timed_out_total {wm.get("timed_out", 0)}')
            _append(f'ocr_connection_errors_total {wm.get("connection_errors", 0)}')
    except Exception:
        _append('ocr_circuit 0')

    # ── Staging storage metrics ──
    try:
        from app.services.staging_storage import get_metrics
        sm = get_metrics()
        _append(f'staging_disk_usage_bytes {sm.get("disk_usage_bytes", 0)}')
        _append(f'staging_object_count {sm.get("object_count", 0)}')
        _append(f'staging_leased_count {sm.get("leased_count", 0)}')
    except Exception:
        _append('staging_disk_usage_bytes 0')

    # ── DB pool metrics ──
    pool_stats = _get_db_pool_metrics()
    for k, v in pool_stats.items():
        if isinstance(v, (int, float)):
            _append(f'db_pool_{k} {v}')

    # ── Process info ──
    _append(f'process_info{{role="{settings.PROCESS_ROLE}",env="{settings.APP_ENV}"}} 1')
    _append(f'process_uptime_seconds {time.time() - _startup_ts:.0f}')

    # ── SSE connections ──
    # ── SSE connections ──
    try:
        from app.services.sse_pubsub import check_health as _sse_health
        _sse_ok = await _sse_health()
        _append(f"sse_healthy {1 if _sse_ok else 0}")
    except Exception:
        _append("sse_healthy 0")
    try:
        from app.features import batch_image_import_service as _batch_svc_mod
        _active_sse = getattr(_batch_svc_mod, "_active_sse_connections", {})
        _total_sse = sum(_active_sse.values()) if isinstance(_active_sse, dict) else 0
        _append(f"sse_active_connections {_total_sse}")
    except Exception:
        _append("sse_active_connections 0")
    try:
        from app.api.v1.admin_imports import _sse_metrics as _sse_m
        if isinstance(_sse_m, dict):
            for _sk, _sv in _sse_m.items():
                _append(f"sse_{_sk} {_sv}")
    except Exception:
        pass

    # ── Draining status ──
    try:
        from app.services.task_queue_worker import is_draining_v2
        _append(f'worker_draining {1 if is_draining_v2() else 0}')
    except Exception:
        _append("worker_draining 0")

    try:
        from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler
        _lock = getattr(audit_log_cleanup_scheduler, "_lock", None)
        if _lock is not None:
            _append(f'distlock_acquired_total{{name="audit:cleanup"}} {_lock.acquired}')
            _append(f'distlock_skipped_total{{name="audit:cleanup"}} {_lock.skipped}')
            _append(f'distlock_failed_total{{name="audit:cleanup"}} {_lock.failed}')
            _append(f'distlock_duration_ms_total{{name="audit:cleanup"}} {_lock.duration_ms:.0f}')
    except Exception:
        _append('distlock_acquired_total{name="audit:cleanup"} 0')
        _append('distlock_skipped_total{name="audit:cleanup"} 0')
        _append('distlock_failed_total{name="audit:cleanup"} 0')
        _append('distlock_duration_ms_total{name="audit:cleanup"} 0')

    # ── Scheduler running state ──
    try:
        from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler
        _append(f'scheduler_running{{name="audit_cleanup"}} {1 if audit_log_cleanup_scheduler._running else 0}')
    except Exception:
        _append('scheduler_running{name="audit_cleanup"} 0')

    # ── Staging cleanup stats ──
    try:
        from app.services.staging_storage import get_metrics as _staging_metrics
        _sm = _staging_metrics()
        _append(f'staging_orphan_count {_sm.get("orphan_count", 0)}')
    except Exception:
        _append('staging_orphan_count 0')

    # Prometheus text format requires trailing newline
    lines.append("")
    return Response(content="\n".join(lines), media_type="text/plain; version=0.0.4")


_startup_ts: float = time.time()

app.include_router(api_router)

# 静态文件服务（开发用公式图片和题图）
os.makedirs("static/formulas", exist_ok=True)
os.makedirs("static/question-assets", exist_ok=True)
# Python 3.11 的 mimetypes 未注册 .webp，需显式注册以保证正确的 image/webp Content-Type
import mimetypes

mimetypes.add_type("image/webp", ".webp")
app.mount("/static/formulas", StaticFiles(directory="static/formulas", html=False), name="static_formulas")
app.mount("/static/question-assets", StaticFiles(directory="static/question-assets", html=False), name="static_question_assets")
