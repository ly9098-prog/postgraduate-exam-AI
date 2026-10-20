import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import resolve_effective_process_role, settings
from app.core.database import async_session, init_db
from app.core.deployment_profile import is_restricted_environment
from app.core.event_loop_health import event_loop_health, monitor_event_loop_lag
from app.core.http_error_handlers import register_http_exception_handlers
from app.core.http_middleware import register_http_middleware
from app.core.logging_config import setup_logging
from app.core.observability_access import require_observability_access
from app.core.ocr_isolation import (
    is_restricted_ocr_environment,
    loaded_local_ocr_modules,
)
from app.core.readiness_response import ReadinessSnapshot, build_readiness_response
from app.core.runtime_resource_shutdown import (
    close_runtime_connections,
    shutdown_render_resources,
    stop_resource_reconciler,
)
from app.core.runtime_task_shutdown import cancel_and_wait_runtime_tasks
from app.core.sentry import init_sentry
from app.services.admin_bootstrap_service import ensure_dev_super_admin
from app.services.ocr_readiness import OcrReadinessState, check_ocr_config
from app.services.production_config_validator import (
    validate_production_config,
    validate_production_config_async,
)
from app.services.readiness_dependency_probes import (
    check_alembic_head,
    check_database,
    check_queue,
    check_redis,
    check_staging,
    check_staging_space,
    get_db_pool_metrics,
)
from app.services.role_readiness import check_role_dependencies
from app.services.runtime_inference_metrics import append_ai_metrics, append_ocr_metrics
from app.services.runtime_sse_metrics import append_sse_metrics
from app.services.runtime_system_metrics import (
    append_db_pool_metrics,
    append_db_query_metrics,
    append_process_metrics,
    append_staging_cleanup_metrics,
    append_staging_metrics,
    append_system_metrics,
    append_worker_scheduler_metrics,
)
from app.services.task_queue_metrics import (
    append_queue_counters,
    append_queue_depth_metrics,
)

setup_logging()
init_sentry()

logger = logging.getLogger("postgraduate-ai")


async def _run_registered_periodic_task(task_id: str, label: str) -> None:
    """Delegate periodic scheduling to the shared system-task runtime."""
    from app.services.system_task_service import run_registered_periodic_task

    await run_registered_periodic_task(task_id, label)


async def _periodic_token_cleanup() -> None:
    """Clean up expired refresh tokens on deterministic 6-hour UTC slots."""
    await _run_registered_periodic_task(
        "refresh_token_cleanup", "Refresh token cleanup"
    )


async def _periodic_staging_cleanup() -> None:
    """Clean up expired staging files at minute 00 of every UTC hour."""
    await _run_registered_periodic_task("staging_cleanup", "Staging cleanup")


async def _periodic_export_processor():
    """Background task: process pending export tasks (scheduler role only)."""
    try:
        from app.services.export.processor import run_export_processor

        await run_export_processor()
    except Exception as e:
        logger.warning("Export processor exited: %s", e)


async def _periodic_export_cleanup() -> None:
    """Clean up expired export tasks at minute 02 of every UTC hour."""
    await _run_registered_periodic_task("export_cleanup", "Export cleanup")


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
    configured_role = settings.PROCESS_ROLE
    role = resolve_effective_process_role(
        settings.APP_ENV,
        configured_role,
        settings.LOCAL_ASYNC_RUNTIME_ENABLED,
    )
    if role != configured_role:
        logger.info(
            "Local async runtime disabled: configured PROCESS_ROLE=%s -> effective role=%s. "
            "Set LOCAL_ASYNC_RUNTIME_ENABLED=true only for full local worker/scheduler debugging.",
            configured_role,
            role,
        )
        # Keep downstream role-aware code (metrics, DB pool diagnostics, health
        # checks) consistent with the process that is actually running.
        settings.PROCESS_ROLE = role
        os.environ["PROCESS_ROLE"] = role

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
    _scheduler_heartbeat_task = None
    _outbox_dispatcher_task = None
    _outbox_reconciler_task = None

    # A plain local ``uvicorn app.main:app`` process resolves to the web role
    # when LOCAL_ASYNC_RUNTIME_ENABLED is false. Export generation does not
    # depend on the Redis task runtime, so keep its lightweight DB-backed
    # processor available locally; otherwise export tasks remain pending forever
    # unless developers also start a separate scheduler process. Production
    # keeps the existing web/scheduler split.
    _local_web_export_processor = role == "web" and (
        settings.APP_ENV or ""
    ).strip().lower() in {"development", "dev", "local", "test", "testing"}

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
        settings.APP_ENV,
        role,
        profile.name,
        profile.use_gpu,
        profile.max_workers,
        profile.max_pdf_pages,
    )
    # Explicitly log which components are active per role. Keep ``all`` as a
    # separate branch so diagnostics never claim that its worker/scheduler are
    # disabled when they are actually running.
    if role == "web":
        logger.info(
            "Role=%s: API serving, OCR gateway active (no worker/dispatcher)", role
        )
    elif role == "worker":
        logger.info(
            "Role=%s: pipeline dispatcher, reaper, AI prewarm active (no API)", role
        )
    elif role == "scheduler":
        logger.info(
            "Role=%s: periodic tasks (token, staging, audit, recommendation metrics, "
            "export cleanup) active (no API, no worker)",
            role,
        )
    elif role == "all":
        logger.warning(
            "Role=%s: API + worker + scheduler components active in one process "
            "(development mode). In production, use web/worker/scheduler split.",
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
        logger.info(
            "export_processor_enabled=true process_role=%s redis_available=%s",
            role,
            _has_redis,
        )
    elif role == "web":
        logger.warning(
            "process_role=web export_processor_enabled=false export_processor_mode=external "
            " — pending export tasks will NOT be processed. "
            "Start a scheduler process (PROCESS_ROLE=scheduler) or use PROCESS_ROLE=all for local dev."
        )
    os.makedirs("static/formulas", exist_ok=True)
    os.makedirs("static/question-assets", exist_ok=True)
    os.makedirs("static/avatars", exist_ok=True)
    os.makedirs(settings.EXPORT_DIR, exist_ok=True)
    await init_db()

    # Fix residual UNIQUE constraint on export_tasks.idempotency_key.
    # The phase7_export_fixes migration attempted this but failed on SQLite
    # (table-level UNIQUE constraints can't be dropped via batch_op.drop_index).
    # This runtime DDL is a belt-and-suspenders fix alongside the application-level
    # IntegrityError handler in the create_export endpoint.
    try:
        from app.core.database import engine as _db_engine

        _dialect = _db_engine.dialect.name
        if _dialect == "sqlite":
            from sqlalchemy import inspect as _sa_inspect

            def _repair_export_idempotency_index(sync_conn) -> bool:
                """Inspect/repair SQLite through AsyncConnection.run_sync."""
                _inspector = _sa_inspect(sync_conn)
                if "export_tasks" not in _inspector.get_table_names():
                    return False
                _ix_list = _inspector.get_indexes("export_tasks")
                _unique_constraints = _inspector.get_unique_constraints("export_tasks")
                _unique_indexes = [
                    _ix
                    for _ix in _ix_list
                    if _ix.get("column_names", []) == ["idempotency_key"]
                    and _ix.get("unique")
                ]
                _matching_constraints = [
                    _constraint
                    for _constraint in _unique_constraints
                    if _constraint.get("column_names", []) == ["idempotency_key"]
                ]
                _has_plain_index = any(
                    _ix.get("column_names", []) == ["idempotency_key"]
                    and not _ix.get("unique")
                    for _ix in _ix_list
                )
                if not _unique_indexes and not _matching_constraints:
                    return False

                # Alembic batch mode recreates SQLite tables when a table-level
                # UNIQUE constraint cannot be removed with DROP INDEX.
                from alembic.runtime.migration import MigrationContext

                from alembic import op

                _ctx = MigrationContext.configure(sync_conn)
                _op = op.Operations(_ctx)
                # Naming convention gives SQLite's unnamed column-level UNIQUE
                # constraint a deterministic reflected name in batch mode.
                naming_convention = {
                    "uq": "uq_%(table_name)s_%(column_0_name)s",
                }
                with _op.batch_alter_table(
                    "export_tasks", naming_convention=naming_convention
                ) as _batch:
                    for _constraint in _matching_constraints:
                        _batch.drop_constraint(
                            _constraint.get("name")
                            or "uq_export_tasks_idempotency_key",
                            type_="unique",
                        )
                    for _ix in _unique_indexes:
                        _batch.drop_index(_ix["name"])
                    if not _has_plain_index:
                        _batch.create_index(
                            "ix_export_tasks_idempotency_key", ["idempotency_key"]
                        )
                return True

            # Never drive AsyncEngine.sync_engine directly from the event loop:
            # aiosqlite requires the greenlet adapter and synchronous drivers
            # would otherwise block startup.
            async with _db_engine.begin() as _conn:
                _sqlite_index_repaired = await _conn.run_sync(
                    _repair_export_idempotency_index
                )
            if _sqlite_index_repaired:
                logger.info(
                    "Fixed residual UNIQUE constraint on export_tasks.idempotency_key (SQLite)"
                )
        elif _dialect == "postgresql":
            # PostgreSQL: drop the UNIQUE constraint if it exists and replace with index
            async with async_session() as _s:
                _row = (
                    await _s.execute(
                        text("""
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'export_tasks'::regclass
                    AND conname LIKE '%idempotency_key%'
                    AND contype = 'u'
                """)
                    )
                ).scalar_one_or_none()
                if _row:
                    # Constraint names come from PostgreSQL metadata, but still
                    # escape identifier quotes before interpolating into DDL.
                    _quoted_constraint = str(_row).replace('"', '""')
                    await _s.execute(
                        text(
                            f'ALTER TABLE export_tasks DROP CONSTRAINT "{_quoted_constraint}"'
                        )
                    )
                    await _s.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_export_tasks_idempotency_key "
                            "ON export_tasks (idempotency_key)"
                        )
                    )
                    await _s.commit()
                    logger.info(
                        "Fixed residual UNIQUE constraint on export_tasks.idempotency_key (PostgreSQL)"
                    )
    except Exception as _exc:
        logger.warning(
            "Failed to fix idempotency_key UNIQUE constraint (%s: %s) "
            "(non-fatal, application-level fallback active)",
            type(_exc).__name__,
            _exc,
        )

    # Schema divergence diagnostic: detect missing runtime-DDL columns on PostgreSQL.
    # Lightweight startup check — warns if known columns are absent.
    try:
        from app.core.database import engine

        _sync_engine = engine.sync_engine
        if _sync_engine.dialect.name == "postgresql":
            _runtime_ddl_checks: dict[str, list[str]] = {
                "questions": ["question_hash", "sync_uuid", "sync_version"],
                "question_imports": [
                    "question_hash",
                    "duplicate_status",
                    "duplicate_of_question_id",
                    "duplicate_of_import_id",
                ],
                "users": ["is_banned", "deleted_at"],
            }
            _divergence: list[str] = []
            async with async_session() as _s:
                for _tbl, _cols in _runtime_ddl_checks.items():
                    try:
                        _row = (
                            await _s.execute(
                                text(
                                    "SELECT column_name FROM information_schema.columns "
                                    "WHERE table_name=:tbl AND column_name=ANY(:cols)"
                                ),
                                {"tbl": _tbl, "cols": _cols},
                            )
                        ).all()
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
                    seed_result.get("created"),
                    seed_result.get("updated"),
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
                    ai_check.enabled_count,
                    ai_check.providers,
                    ai_check.features,
                )
            else:
                logger.info(
                    "AI model config healthy: enabled_count=%d default_count=%d providers=%s features=%s",
                    ai_check.enabled_count,
                    ai_check.default_count,
                    ai_check.providers,
                    ai_check.features,
                )
    except Exception as e:
        logger.warning(
            "AI model config self-check failed (non-fatal, DB may not be ready): %s", e
        )

    # ── Resource references populated by role ──
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
            role,
            {k: v.name for k, v in _executors.items()},
        )
    except Exception as e:
        _report_startup_failure("Executors", e)
    _pipeline_worker_task: asyncio.Task | None = None
    _reaper_task: asyncio.Task | None = None
    _lag_monitor_task: asyncio.Task | None = None

    # Event-loop lag monitor (always runs — lightweight, all roles)
    _lag_monitor_task = asyncio.create_task(
        monitor_event_loop_lag(event_loop_health), name="event-loop-lag-monitor"
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
                    cfg,
                    http_client=_ocr_shared_http_client,
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
                    role,
                    cfg.execution_backend,
                    cfg.profile,
                    cfg.environment,
                )
            else:
                logger.info("OCR not enabled, skipping Gateway initialization")
        except Exception as e:
            _report_startup_failure("OCR Gateway", e)

    # Local web development still needs a runnable export processor. Starting
    # only this processor avoids enabling the full Redis-dependent async runtime
    # while making the documented single-process uvicorn workflow functional.
    if _local_web_export_processor:
        _export_processor_task = asyncio.create_task(
            _periodic_export_processor(), name="export-processor-local"
        )
        logger.info("Local web export processor started")

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
            from app.services.system_task_service import run_scheduler_heartbeat

            _scheduler_heartbeat_task = asyncio.create_task(
                run_scheduler_heartbeat(), name="scheduler-heartbeat"
            )
        except Exception as e:
            _report_startup_failure("Scheduler heartbeat", e)

        try:
            from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler

            await audit_log_cleanup_scheduler.start()
            logger.info("Audit log cleanup scheduler started")
        except Exception as e:
            _report_startup_failure("Audit log cleanup scheduler", e)

        try:
            from app.services.recommendation_metrics_scheduler import (
                recommendation_metrics_scheduler,
            )

            await recommendation_metrics_scheduler.start()
            logger.info("Recommendation metrics scheduler started")
        except Exception as e:
            _report_startup_failure("Recommendation metrics scheduler", e)

        # Periodic cleanup tasks belong in the scheduler role only
        cleanup_task = asyncio.create_task(
            _periodic_token_cleanup(), name="token-cleanup"
        )
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

        # 3b. Signal export processor to drain (scheduler/all or local-web fallback)
        if _export_processor_task is not None:
            try:
                from app.services.export.processor import stop_processor

                await stop_processor()
                logger.info("export_processor_stopped role=%s", role)
            except Exception as e:
                logger.warning("Export processor stop signal failed: %s", e)

        # 4. Cancel and await background asyncio tasks with grace timeout
        await cancel_and_wait_runtime_tasks([
            ("token-cleanup", cleanup_task),
            ("pipeline-dispatcher-v2", _pipeline_worker_task),
            ("task-reaper-v2", _reaper_task),
            ("staging-cleanup", _staging_cleanup_task),
            ("export-processor", _export_processor_task),
            ("export-cleanup", _export_cleanup_task),
            ("scheduler-heartbeat", _scheduler_heartbeat_task),
            ("outbox-dispatcher", _outbox_dispatcher_task),
            ("outbox-reconciler", _outbox_reconciler_task),
        ])

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
            logger.warning(
                "Formula render pool shutdown timed out, forcing non-blocking"
            )
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

        await shutdown_render_resources()
        await close_runtime_connections()
        await stop_resource_reconciler()

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


_production_mode = is_restricted_environment()
app = FastAPI(
    title="2240AI",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _production_mode else "/docs",
    redoc_url=None if _production_mode else "/redoc",
    openapi_url=None if _production_mode else "/openapi.json",
)

register_http_middleware(
    app,
    allowed_hosts=settings.ALLOWED_HOSTS,
    cors_origins=settings.CORS_ORIGINS,
    production_mode=_production_mode,
)

register_http_exception_handlers(app)


# --- 健康检查和可观测性 ---


# ── OCR readiness hysteresis ──
# Track consecutive remote OCR health-check failures.
# Crosses the degraded threshold at 3 consecutive failures.
ocr_readiness_state = OcrReadinessState()


@app.get("/health")
async def health():
    """Legacy public health endpoint with no environment disclosure."""
    return {"status": "ok"}


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
    db_ok = await check_database(async_session)
    redis_ok = await check_redis(redis_url=settings.REDIS_URL, production_mode=_production_mode)
    alembic_ok = await check_alembic_head(
        async_session, script_location=os.path.join(os.path.dirname(__file__), "../alembic"),
    )
    staging_ok = await check_staging()
    staging_space = await check_staging_space()
    role_ok = await check_role_dependencies(settings)

    # Non-critical checks (informational, don't fail probe)
    ocr_status = await check_ocr_config(settings, ocr_readiness_state)
    queue_status = await check_queue(redis_url=settings.REDIS_URL, production_mode=_production_mode)

    # Draining is critical — stop the load balancer from sending requests
    try:
        from app.services.task_queue_worker import is_draining_v2

        draining = is_draining_v2()
    except Exception:
        draining = False

    status_code, response_content = build_readiness_response(
        ReadinessSnapshot(
            database_ok=db_ok,
            redis_ok=redis_ok,
            alembic_ok=alembic_ok,
            staging_ok=staging_ok,
            staging_space=staging_space,
            role_ok=role_ok,
            ocr_status=ocr_status,
            queue_status=queue_status,
            draining=draining,
            db_pool=get_db_pool_metrics(),
            event_loop_lag_ms=event_loop_health.lag_ms,
        ),
        redis_configured=bool(settings.REDIS_URL),
        production_mode=_production_mode,
    )
    return JSONResponse(status_code=status_code, content=response_content)


# --- 路由（聚合 Router） ---


@app.get("/health/metrics")
async def metrics_endpoint(request: Request):
    """Prometheus-compatible metrics endpoint.

    Returns text/plain metrics for scraping by Prometheus or similar.
    Aggregates: task queue state, system resources, event-loop lag,
    DB pool, SSE connections, scheduler stats.
    """
    require_observability_access(
        request, production_mode=_production_mode, token=settings.OBSERVABILITY_TOKEN,
    )
    from app.core.resource_guard import resource_guard
    from app.services.task_queue_service import queue_metrics

    lines: list[str] = []
    await append_queue_depth_metrics(lines)
    append_queue_counters(lines, queue_metrics)
    append_system_metrics(
        lines, resource_guard.get_system_metrics(),
        event_loop_lag_ms=event_loop_health.lag_ms,
    )
    append_ocr_metrics(lines)
    await append_ai_metrics(lines)
    append_staging_metrics(lines)
    append_db_pool_metrics(lines, get_db_pool_metrics())
    append_db_query_metrics(lines)
    append_process_metrics(
        lines, role=settings.PROCESS_ROLE, environment=settings.APP_ENV,
        uptime_seconds=time.time() - _startup_ts,
    )
    await append_sse_metrics(lines)
    append_worker_scheduler_metrics(lines)
    append_staging_cleanup_metrics(lines)

    # Prometheus text format requires trailing newline
    lines.append("")
    return Response(content="\n".join(lines), media_type="text/plain; version=0.0.4")


_startup_ts: float = time.time()

app.include_router(api_router)

# 静态文件服务（开发用公式图片和题图）
os.makedirs("static/formulas", exist_ok=True)
os.makedirs("static/question-assets", exist_ok=True)
os.makedirs("static/avatars", exist_ok=True)
# Python 3.11 的 mimetypes 未注册 .webp，需显式注册以保证正确的 image/webp Content-Type
import mimetypes

mimetypes.add_type("image/webp", ".webp")
app.mount(
    "/static/formulas",
    StaticFiles(directory="static/formulas", html=False),
    name="static_formulas",
)
app.mount(
    "/static/question-assets",
    StaticFiles(directory="static/question-assets", html=False),
    name="static_question_assets",
)
app.mount(
    "/static/avatars",
    StaticFiles(directory="static/avatars", html=False),
    name="static_avatars",
)
