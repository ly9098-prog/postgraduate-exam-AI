import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import resolve_effective_process_role, settings
from app.core.database import async_session, init_db
from app.core.deployment_profile import is_restricted_environment
from app.core.event_loop_health import event_loop_health, monitor_event_loop_lag
from app.core.http_error_handlers import register_http_exception_handlers
from app.core.http_middleware import register_http_middleware
from app.core.http_runtime_policy import (
    assert_http_ocr_isolation,
    prepare_http_runtime_role,
    report_http_startup_failure,
)
from app.core.logging_config import setup_logging
from app.core.observability_access import require_observability_access
from app.core.ocr_isolation import (
    is_restricted_ocr_environment,
    loaded_local_ocr_modules,
)
from app.core.readiness_response import ReadinessSnapshot, build_readiness_response
from app.core.runtime_http_shutdown import (
    raise_after_http_shutdown,
    stop_export_processor,
    stop_lag_monitor,
)
from app.core.runtime_resource_shutdown import (
    close_runtime_connections,
    log_active_children,
    shutdown_formula_pool,
    shutdown_http_ocr_gateway,
    shutdown_ocr_executor,
    shutdown_render_resources,
    stop_resource_reconciler,
)
from app.core.runtime_resource_startup import (
    ensure_http_runtime_directories,
    initialize_role_executors,
    start_resource_reconciler,
)
from app.core.runtime_role_shutdown import drain_queue_for_role, stop_role_services
from app.core.runtime_task_shutdown import cancel_and_wait_runtime_tasks
from app.core.sentry import init_sentry
from app.services.admin_bootstrap_service import ensure_dev_super_admin
from app.services.export.schema_compatibility import repair_export_idempotency_schema
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
from app.services.runtime_http_scheduler_startup import (
    HttpSchedulerTasks,
    start_http_scheduler_tasks,
)
from app.services.runtime_http_startup_diagnostics import (
    log_http_export_startup,
    log_http_startup,
)
from app.services.runtime_http_worker_startup import (
    HttpWorkerTasks,
    start_http_worker_tasks,
)
from app.services.runtime_inference_metrics import append_ai_metrics, append_ocr_metrics
from app.services.runtime_ocr_startup import (
    HttpOcrResources,
    initialize_http_ocr_gateway,
)
from app.services.runtime_periodic_tasks import (
    run_export_processor_loop,
)
from app.services.runtime_schema_diagnostics import log_runtime_schema_divergence
from app.services.runtime_sse_metrics import append_sse_metrics
from app.services.runtime_staging_startup import sweep_staging_on_startup
from app.services.runtime_startup_checks import (
    initialize_dev_admin,
    log_ai_model_configuration,
    seed_recommendation_strategies,
)
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    role = prepare_http_runtime_role(settings, resolve_effective_process_role)

    worker_tasks = HttpWorkerTasks()
    scheduler_tasks = HttpSchedulerTasks()
    ocr_resources = HttpOcrResources()
    lag_monitor_task: asyncio.Task | None = None
    shutdown_error: Exception | None = None

    try:
        # A plain local ``uvicorn app.main:app`` process resolves to the web role
        # when LOCAL_ASYNC_RUNTIME_ENABLED is false. Export generation does not
        # depend on the Redis task runtime, so keep its lightweight DB-backed
        # processor available locally; otherwise export tasks remain pending forever
        # unless developers also start a separate scheduler process. Production
        # keeps the existing web/scheduler split.
        local_web_export_processor = role == "web" and (
            settings.APP_ENV or ""
        ).strip().lower() in {"development", "dev", "local", "test", "testing"}

        # ── Common startup (all roles) ──
        validate_production_config()
        await validate_production_config_async()

        assert_http_ocr_isolation(
            loaded_local_ocr_modules, is_restricted_ocr_environment
        )

        from app.core.ocr_profile import get_ocr_profile

        profile = get_ocr_profile()

        # Staging storage: sweep stale temp files on startup
        await sweep_staging_on_startup(logger)
        log_http_startup(settings, role, profile, logger)
        log_http_export_startup(role, settings, logger)
        ensure_http_runtime_directories(settings)
        await init_db()

        await repair_export_idempotency_schema(async_session)
        await log_runtime_schema_divergence(async_session)
        await initialize_dev_admin(async_session, ensure_dev_super_admin, settings)
        await seed_recommendation_strategies(async_session)
        await log_ai_model_configuration(async_session)

        # ── Role-aware BoundedExecutors ──
        try:
            initialize_role_executors(role)
        except Exception as e:
            report_http_startup_failure("Executors", e, _production_mode)

        # Event-loop lag monitor (always runs — lightweight, all roles)
        lag_monitor_task = asyncio.create_task(
            monitor_event_loop_lag(event_loop_health),
            name="event-loop-lag-monitor",
        )

        # ── Role: web — HTTP + enqueue ──
        # Periodic cleanup tasks (token, staging) belong exclusively to the
        # scheduler role. The web role only handles request serving and enqueue.
        if role in ("web", "all"):
            # Initialize OCR Gateway (needed for API enqueue endpoints)
            try:
                initialize_http_ocr_gateway(ocr_resources, role)
            except Exception as e:
                report_http_startup_failure("OCR Gateway", e, _production_mode)

        # Local web development still needs a runnable export processor. Starting
        # only this processor avoids enabling the full Redis-dependent async runtime
        # while making the documented single-process uvicorn workflow functional.
        if local_web_export_processor:
            scheduler_tasks.export_processor_task = asyncio.create_task(
                run_export_processor_loop(logger), name="export-processor-local"
            )
            logger.info("Local web export processor started")

        # ── Role: worker — pipeline processing + AI prewarm ──
        if role in ("worker", "all"):
            await start_http_worker_tasks(
                worker_tasks,
                _production_mode,
                logger,
                report_http_startup_failure,
            )

        # ── Role: scheduler — periodic background tasks ──
        if role in ("scheduler", "all"):
            await start_http_scheduler_tasks(
                scheduler_tasks,
                _production_mode,
                logger,
                report_http_startup_failure,
            )

        # Start resource reservation orphan reconciler (all roles)
        await start_resource_reconciler()

        # ── Yield — application serves requests ──
        yield
    finally:
        # ══════════════════════════════════════════
        # Shutdown — ordered, resilient, logged
        # ══════════════════════════════════════════
        logger.info("=== Shutdown sequence started (role=%s) ===", role)

        try:
            await drain_queue_for_role(role)
        except Exception as e:
            shutdown_error = shutdown_error or e

        # 2. Stop event-loop lag monitor
        try:
            await stop_lag_monitor(lag_monitor_task)
        except Exception as e:
            shutdown_error = shutdown_error or e

        # 3b. Signal export processor to drain (scheduler/all or local-web fallback)
        if scheduler_tasks.export_processor_task is not None:
            try:
                await stop_export_processor(role)
            except Exception as e:
                shutdown_error = shutdown_error or e

        # 4. Cancel and await background asyncio tasks with grace timeout
        try:
            await cancel_and_wait_runtime_tasks([
                ("token-cleanup", scheduler_tasks.cleanup_task),
                ("pipeline-dispatcher-v2", worker_tasks.pipeline_worker_task),
                ("task-reaper-v2", worker_tasks.reaper_task),
                ("staging-cleanup", scheduler_tasks.staging_cleanup_task),
                ("export-processor", scheduler_tasks.export_processor_task),
                ("export-cleanup", scheduler_tasks.export_cleanup_task),
                ("scheduler-heartbeat", scheduler_tasks.scheduler_heartbeat_task),
                ("outbox-dispatcher", scheduler_tasks.outbox_dispatcher_task),
                ("outbox-reconciler", scheduler_tasks.outbox_reconciler_task),
                ("answer-projection-reconciler", scheduler_tasks.answer_projection_task),
                ("async-task-health-monitor", scheduler_tasks.health_monitor_task),
            ], grace_seconds=settings.WORKER_SHUTDOWN_GRACE_SEC)
        except Exception as e:
            shutdown_error = shutdown_error or e

        try:
            await stop_role_services(role)
        except Exception as e:
            shutdown_error = shutdown_error or e

        try:
            await shutdown_formula_pool()
        except Exception as e:
            shutdown_error = shutdown_error or e

        # 6. Shutdown OCR infrastructure (only if this role uses it)
        # Cloud profile: skip OCR executor shutdown — it imports local PaddleOCR modules.
        if role in ("web", "all"):
            try:
                await shutdown_ocr_executor()
            except Exception as e:
                shutdown_error = shutdown_error or e
            try:
                await shutdown_http_ocr_gateway(ocr_resources)
            except Exception as e:
                shutdown_error = shutdown_error or e

        try:
            await shutdown_render_resources()
        except Exception as e:
            shutdown_error = shutdown_error or e
        try:
            await close_runtime_connections()
        except Exception as e:
            shutdown_error = shutdown_error or e
        try:
            await stop_resource_reconciler()
        except Exception as e:
            shutdown_error = shutdown_error or e

        logger.info("=== Shutdown sequence completed (role=%s) ===", role)
        log_active_children()
        raise_after_http_shutdown(shutdown_error)


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
