import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    role = settings.PROCESS_ROLE
    is_dev = settings.APP_ENV == "development"

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
    from app.core.ocr_profile import get_ocr_profile
    profile = get_ocr_profile()
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
    _ocr_gateway = None
    _pipeline_worker_task: asyncio.Task | None = None
    _reaper_task: asyncio.Task | None = None
    _lag_monitor_task: asyncio.Task | None = None

    # Event-loop lag monitor (always runs — lightweight, all roles)
    _lag_monitor_task = asyncio.create_task(
        _event_loop_lag_monitor(), name="event-loop-lag-monitor"
    )

    # ── Role: web — HTTP + enqueue + token cleanup ──
    if role in ("web", "all"):
        cleanup_task = asyncio.create_task(_periodic_token_cleanup(), name="token-cleanup")

        # Initialize OCR Gateway (needed for API enqueue endpoints)
        try:
            from app.core.ocr_runtime_config import get_runtime_config
            from app.features.ocr_gateway import OCRGateway
            from app.services.ocr_worker_client import create_ocr_worker_client

            cfg = get_runtime_config()
            if cfg.enabled:
                worker_client = create_ocr_worker_client(cfg)
                _ocr_gateway = OCRGateway(
                    mode="gateway",
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
            logger.warning("OCR Gateway init failed (non-fatal): %s", e)

    # ── Role: worker — pipeline processing ──
    if role in ("worker", "all"):
        try:
            from app.services.task_queue_worker import run_pipeline_worker
            _pipeline_worker_task = asyncio.create_task(
                run_pipeline_worker(), name="pipeline-worker"
            )
        except Exception as e:
            logger.warning("Pipeline worker start failed (non-fatal): %s", e)
        try:
            from app.services.task_queue_worker import run_reaper_loop
            _reaper_task = asyncio.create_task(
                run_reaper_loop(), name="task-reaper"
            )
        except Exception as e:
            logger.warning("Reaper start failed (non-fatal): %s", e)

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

        try:
            from app.services.ai_prewarm_worker import start_worker
            await start_worker()
            logger.info("AI prewarm worker started")
        except Exception as e:
            logger.warning("AI prewarm worker start failed (non-fatal): %s", e)

        # Scheduler also needs token cleanup if web role isn't running
        if role == "scheduler" and cleanup_task is None:
            cleanup_task = asyncio.create_task(_periodic_token_cleanup(), name="token-cleanup")

    # ── Yield — application serves requests ──
    try:
        yield
    finally:
        # ══════════════════════════════════════════
        # Shutdown — ordered, resilient, logged
        # ══════════════════════════════════════════
        logger.info("=== Shutdown sequence started (role=%s) ===", role)

        # 1. Stop receiving new background work

        # 2. Stop event-loop lag monitor
        if _lag_monitor_task and not _lag_monitor_task.done():
            _lag_monitor_task.cancel()
            try:
                await _lag_monitor_task
            except asyncio.CancelledError:
                pass

        # 3. Stop pipeline worker + reaper (if running in this role)
        if role in ("worker", "all"):
            try:
                from app.services.task_queue_worker import stop_worker, stop_reaper
                stop_worker()
                stop_reaper()
            except Exception as e:
                logger.warning("Worker/reaper stop signal failed: %s", e)

        # 3. Cancel and await background asyncio tasks
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

        for name, task in _shutdown_tasks:
            try:
                await task
                logger.info("Task %s: completed after cancel", name)
            except asyncio.CancelledError:
                logger.info("Task %s: cancelled", name)
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
        except asyncio.TimeoutError:
            logger.warning("Formula render pool shutdown timed out, forcing non-blocking")
            try:
                shutdown_formula_render_pool(wait=False, cancel_futures=True)
            except Exception as exc2:
                logger.exception("Formula render pool forced shutdown error: %s", exc2)
        except Exception:
            logger.exception("Formula render pool shutdown error")

        # 6. Shutdown OCR executor (process pool) — common
        try:
            from app.services.ocr_executor_service import ocr_executor
            await asyncio.wait_for(
                ocr_executor.shutdown(wait=True),
                timeout=30,
            )
            logger.info("OCR executor shut down")
        except asyncio.TimeoutError:
            logger.warning("OCR executor shutdown timed out, forcing non-blocking")
            try:
                from app.core.ocr_process_pool import ocr_process_pool
                await asyncio.to_thread(
                    ocr_process_pool.shutdown, wait=False,
                )
            except Exception as exc2:
                logger.exception("OCR executor forced shutdown error: %s", exc2)
        except Exception:
            logger.exception("OCR executor shutdown error")

        # 7. Shutdown OCR Gateway (if initialized)
        try:
            if _ocr_gateway is not None:
                await _ocr_gateway.shutdown()
                logger.info("OCR Gateway shut down")
        except Exception as e:
            logger.warning("OCR Gateway shutdown error: %s", e)

        # 8. Shutdown PDF renderer (thread pool) — common
        try:
            from app.services.pdf_renderer_service import pdf_renderer
            await pdf_renderer.shutdown()
            logger.info("PDF renderer shut down")
        except Exception as e:
            logger.warning("PDF renderer shutdown error: %s", e)

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
    dependency is unavailable. Now includes DB pool metrics and
    event-loop lag.
    """
    db_ok = False
    redis_ok = False

    # Database check
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    # Redis check (only if configured)
    if settings.REDIS_URL:
        try:
            from app.core.cache import cache
            await cache.set("health:ping", "pong", ttl=10)
            pong = await cache.get("health:ping")
            redis_ok = pong == "pong"
        except Exception:
            redis_ok = False

    checks = {
        "database": "ok" if db_ok else "unavailable",
        "db_pool": _get_db_pool_metrics(),
        "event_loop_lag_ms": _elapsed_monitor_event_loop_lag_ms,
    }
    if settings.REDIS_URL:
        checks["redis"] = "ok" if redis_ok else "unavailable"

    all_ok = db_ok and (not settings.REDIS_URL or redis_ok)

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "status": "ok" if all_ok else "unavailable",
            "checks": checks,
        },
    )


# --- 路由（聚合 Router） ---

app.include_router(api_router)

# 静态文件服务（开发用公式图片和题图）
os.makedirs("static/formulas", exist_ok=True)
os.makedirs("static/question-assets", exist_ok=True)
app.mount("/static/formulas", StaticFiles(directory="static/formulas", html=False), name="static_formulas")
app.mount("/static/question-assets", StaticFiles(directory="static/question-assets", html=False), name="static_question_assets")
