import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import settings
from app.core.database import async_session, init_db
from app.core.logging_config import setup_logging
from app.core.sentry import init_sentry
from app.services.admin_bootstrap_service import ensure_dev_super_admin
from app.services.pomodoro_scheduler_service import pomodoro_scheduler
from app.services.production_config_validator import (
    validate_production_config,
    validate_production_config_async,
)

setup_logging()
init_sentry()

logger = logging.getLogger("postgraduate-ai")


_INTERVAL_SEC = 6 * 3600  # 6 hours


async def _periodic_token_cleanup():
    """Background task: clean up expired refresh tokens every 6 hours."""
    while True:
        await asyncio.sleep(_INTERVAL_SEC)
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


def _report_startup_failure(component: str, exc: Exception) -> None:
    """Log component startup failure.

    In production, any core component startup failure is fatal.
    """
    from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
    try:
        is_prod = (
            detect_deployment_profile() == DeploymentProfile.CLOUD_API
            or settings.APP_ENV == "production"
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

    # ── Common startup (all roles) ──
    try:
        validate_production_config()
    except SystemError as e:
        logger.critical("Production configuration validation FAILED: %s", e)
        raise
    except Exception as e:
        logger.warning("Production config validation error (non-fatal): %s", e)
    try:
        await validate_production_config_async()
    except SystemError as e:
        logger.critical("Production async configuration validation FAILED: %s", e)
        raise

    # Check sys.modules for banned OCR packages in cloud_api
    try:
        from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
        if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
            banned = {"paddle", "paddleocr"}
            loaded = {mod for mod in banned if mod in sys.modules}
            if loaded:
                logger.critical(
                    "cloud_api deployment detected banned modules in sys.modules: %s. "
                    "The process must not import local OCR packages.",
                    loaded,
                )
                raise SystemError(
                    f"Banned modules loaded in cloud_api: {loaded}. "
                    "Remove paddle/paddleocr from the deployment image."
                )
    except SystemError:
        raise
    except Exception as e:
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
    os.makedirs("static/formulas", exist_ok=True)
    os.makedirs("static/question-assets", exist_ok=True)
    await init_db()
    try:
        from app.core.database import async_session
        async with async_session() as db:
            created_admin = await ensure_dev_super_admin(db, settings.APP_ENV)
            await db.commit()
            if created_admin:
                logger.info("Development super admin initialized")
    except Exception as e:
        logger.warning("Development super admin init failed (non-fatal): %s", e)

    # AI model config self-check (common)
    try:
        from app.core.database import async_session
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
            from app.core.ocr_runtime_config import get_runtime_config
            from app.features.ocr_gateway import OCRGateway
            from app.services.ocr_worker_client import create_ocr_worker_client

            cfg = get_runtime_config()
            if cfg.enabled:
                worker_client = create_ocr_worker_client(cfg)
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
            from app.services.task_queue_worker import run_pipeline_worker
            _pipeline_worker_task = asyncio.create_task(
                run_pipeline_worker(), name="pipeline-worker"
            )
        except Exception as e:
            _report_startup_failure("Pipeline worker", e)

        try:
            from app.services.task_queue_worker import run_reaper_loop
            _reaper_task = asyncio.create_task(
                run_reaper_loop(), name="task-reaper"
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
            await pomodoro_scheduler.start()
            logger.info("Pomodoro scheduler started")
        except Exception as e:
            logger.warning("Pomodoro scheduler start failed (non-fatal): %s", e)

        try:
            from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler
            await audit_log_cleanup_scheduler.start()
            logger.info("Audit log cleanup scheduler started")
        except Exception as e:
            logger.warning("Audit log cleanup scheduler start failed (non-fatal): %s", e)

        # Periodic cleanup tasks belong in the scheduler role only
        cleanup_task = asyncio.create_task(_periodic_token_cleanup(), name="token-cleanup")
        _staging_cleanup_task = asyncio.create_task(
            _periodic_staging_cleanup(), name="staging-cleanup"
        )

    # ── Yield — application serves requests ──
    try:
        yield
    finally:
        # ══════════════════════════════════════════
        # Shutdown — ordered, resilient, logged
        # ══════════════════════════════════════════
        logger.info("=== Shutdown sequence started (role=%s) ===", role)

        # 1. Set draining — stop claiming new work
        try:
            from app.services.task_queue_worker import set_draining
            await set_draining()
        except Exception:
            pass

        # 2. Stop event-loop lag monitor
        if _lag_monitor_task and not _lag_monitor_task.done():
            _lag_monitor_task.cancel()
            try:
                await _lag_monitor_task
            except asyncio.CancelledError:
                pass

        # 3. Signal worker + reaper to stop (graceful, no cancel yet)
        if role in ("worker", "all"):
            try:
                from app.services.task_queue_worker import stop_reaper, stop_worker
                await stop_worker()
                await stop_reaper()
            except Exception as e:
                logger.warning("Worker/reaper stop signal failed: %s", e)

        # 4. Cancel and await background asyncio tasks with grace timeout
        _shutdown_tasks = []
        if cleanup_task and not cleanup_task.done():
            cleanup_task.cancel()
            _shutdown_tasks.append(("token-cleanup", cleanup_task))
        if _pipeline_worker_task and not _pipeline_worker_task.done():
            _pipeline_worker_task.cancel()
            _shutdown_tasks.append(("pipeline-worker", _pipeline_worker_task))
        if _reaper_task and not _reaper_task.done():
            _reaper_task.cancel()
            _shutdown_tasks.append(("task-reaper", _reaper_task))
        if _staging_cleanup_task and not _staging_cleanup_task.done():
            _staging_cleanup_task.cancel()
            _shutdown_tasks.append(("staging-cleanup", _staging_cleanup_task))

        for name, task in _shutdown_tasks:
            try:
                await asyncio.wait_for(task, timeout=30)
                logger.info("Task %s: completed after cancel", name)
            except asyncio.CancelledError:
                logger.info("Task %s: cancelled", name)
            except TimeoutError:
                logger.warning("Task %s: did not stop within 30s grace period", name)
            except Exception as e:
                logger.warning("Task %s: cancel error: %s", name, e)

        # 4. Stop schedulers (if running in this role)
        if role in ("scheduler", "all"):
            try:
                await pomodoro_scheduler.stop()
                logger.info("Pomodoro scheduler stopped")
            except Exception as e:
                logger.warning("Pomodoro scheduler stop error: %s", e)

            try:
                from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler
                await audit_log_cleanup_scheduler.stop()
                logger.info("Audit log cleanup scheduler stopped")
            except Exception as e:
                logger.warning("Audit log cleanup scheduler stop error: %s", e)

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
            from app.services.formula_graph_spec_renderer import shutdown_formula_render_pool
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
        if role in ("web", "all"):
            try:
                from app.services.ocr_executor_service import ocr_executor
                await asyncio.wait_for(
                    ocr_executor.shutdown(wait=True),
                    timeout=30,
                )
                logger.info("OCR executor shut down")
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

        # 7. PDF renderer shutdown (common)
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


app = FastAPI(title="2240AI", version="0.1.0", lifespan=lifespan)

# --- 中间件 ---

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    if settings.APP_ENV != "production":
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
    role_ok = await _check_role_deps()

    # Non-critical checks (informational, don't fail probe)
    ocr_status = await _check_ocr_config()
    queue_status = await _check_queue()

    # Draining is critical — stop the load balancer from sending requests
    try:
        from app.services.task_queue_worker import is_draining
        draining = is_draining()
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
    if settings.REDIS_URL or settings.APP_ENV == "production":
        checks["redis"] = "ok" if redis_ok else "unavailable"
    if ocr_status:
        checks["ocr"] = ocr_status
    if queue_status:
        checks["queue"] = queue_status

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
        from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
        try:
            if detect_deployment_profile() == DeploymentProfile.CLOUD_API or settings.APP_ENV == "production":
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


async def _check_role_deps() -> bool:
    """Check role-specific dependencies are available."""
    role = settings.PROCESS_ROLE
    if role == "web":
        # Web needs DB and Redis (already checked separately)
        return True
    elif role in ("worker", "scheduler"):
        # Worker/scheduler need DB, Redis, staging
        return True
    return False  # Unknown role → fail probe


async def _check_ocr_config() -> str | None:
    """Check OCR configuration. Returns status string or None if not applicable.

    Returns "ok", "degraded", "unavailable", or None (no OCR configured).
    In production, illegal OCR config returns "unavailable" (fails probe).
    """
    if not settings.OCR_ENABLED:
        return None

    exec_backend = (settings.OCR_EXECUTION_BACKEND or "").lower()
    issues = []

    if exec_backend == "local_process":
        issues.append("local_process backend not allowed")
    if settings.OCR_USE_GPU is not False:
        issues.append("GPU should be disabled")
    if exec_backend == "paddlex_http" and not settings.OCR_REMOTE_TOKEN:
        issues.append("remote token not set")

    if not issues:
        return "ok"

    from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
    try:
        if detect_deployment_profile() == DeploymentProfile.CLOUD_API or settings.APP_ENV == "production":
            return "unavailable"
    except Exception:
        pass
    return "degraded"


async def _check_queue() -> str | None:
    """Check durable queue health."""
    if not settings.REDIS_URL:
        return None
    try:
        from app.services.task_queue_service import task_queue
        total = 0
        for tt in ("import_pipeline", "image_pipeline", "excel_pipeline"):
            total += await task_queue.queue_length(tt)
            total += await task_queue.processing_length(tt)
        if total > 100:
            return "degraded"
        return "ok"
    except Exception:
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
            ready = await task_queue.queue_length(tt)
            processing = await task_queue.processing_length(tt)
            retry_count = await task_queue.retry_length(tt)
            dead = await task_queue.dead_length(tt)
            _append(f'task_queue_ready{{type="{tt}"}} {ready}')
            _append(f'task_queue_processing{{type="{tt}"}} {processing}')
            _append(f'task_queue_retry{{type="{tt}"}} {retry_count}')
            _append(f'task_queue_dead{{type="{tt}"}} {dead}')
    except Exception:
        for tt in task_types:
            _append(f'task_queue_ready{{type="{tt}"}} 0')
            _append(f'task_queue_processing{{type="{tt}"}} 0')
            _append(f'task_queue_retry{{type="{tt}"}} 0')
            _append(f'task_queue_dead{{type="{tt}"}} 0')

    # Cumulative counters from queue_metrics dict
    for key in ("lease_renewal_failure", "duplicate_enqueue_prevented",
                "reaper_reclaimed", "owner_fencing_rejected"):
        _append(f'task_queue_{key} {queue_metrics.get(key, 0)}')

    # ── System resource metrics ──
    sys_metrics = resource_guard.get_system_metrics()
    _append(f'system_rss_mb {sys_metrics.rss_mb:.1f}')
    _append(f'system_available_memory_mb {sys_metrics.available_memory_mb:.1f}')
    _append(f'system_active_pipelines {sys_metrics.active_pipelines}')
    _append(f'system_event_loop_lag_ms {_elapsed_monitor_event_loop_lag_ms:.2f}')

    # ── DB pool metrics ──
    pool_stats = _get_db_pool_metrics()
    for k, v in pool_stats.items():
        if isinstance(v, (int, float)):
            _append(f'db_pool_{k} {v}')

    # ── Process info ──
    _append(f'process_info{{role="{settings.PROCESS_ROLE}",env="{settings.APP_ENV}"}} 1')
    _append(f'process_uptime_seconds {time.time() - _startup_ts:.0f}')

    # ── SSE connections ──
    try:
        from app.api.v1 import admin_imports as _admin_imports_mod
        _active_sse = getattr(_admin_imports_mod, "_active_sse_connections", 0)
        _append(f'sse_active_connections {_active_sse}')
    except Exception:
        _append("sse_active_connections 0")

    # ── Draining status ──
    try:
        from app.services.task_queue_worker import is_draining
        _append(f'worker_draining {1 if is_draining() else 0}')
    except Exception:
        _append("worker_draining 0")

    # ── Distributed lock metrics (scheduler role) ──
    try:
        from app.services.pomodoro_scheduler_service import pomodoro_scheduler
        _lock = getattr(pomodoro_scheduler, "_lock", None)
        if _lock is not None:
            _append(f'distlock_acquired_total{{name="pomodoro:tick"}} {_lock.acquired}')
            _append(f'distlock_skipped_total{{name="pomodoro:tick"}} {_lock.skipped}')
            _append(f'distlock_failed_total{{name="pomodoro:tick"}} {_lock.failed}')
            _append(f'distlock_duration_ms_total{{name="pomodoro:tick"}} {_lock.duration_ms:.0f}')
    except Exception:
        _append('distlock_acquired_total{name="pomodoro:tick"} 0')
        _append('distlock_skipped_total{name="pomodoro:tick"} 0')
        _append('distlock_failed_total{name="pomodoro:tick"} 0')
        _append('distlock_duration_ms_total{name="pomodoro:tick"} 0')

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

    # Prometheus text format requires trailing newline
    lines.append("")
    return Response(content="\n".join(lines), media_type="text/plain; version=0.0.4")


_startup_ts: float = time.time()

app.include_router(api_router)

# 静态文件服务（开发用公式图片和题图）
os.makedirs("static/formulas", exist_ok=True)
os.makedirs("static/question-assets", exist_ok=True)
app.mount("/static/formulas", StaticFiles(directory="static/formulas", html=False), name="static_formulas")
app.mount("/static/question-assets", StaticFiles(directory="static/question-assets", html=False), name="static_question_assets")
