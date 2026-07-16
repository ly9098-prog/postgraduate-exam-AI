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
    # Production configuration fail-fast check (sync part)
    try:
        validate_production_config()
    except SystemError as e:
        logger.critical("Production configuration validation FAILED: %s", e)
        raise
    except Exception as e:
        logger.warning("Production config validation error (non-fatal): %s", e)
    # Async production config checks (Redis ping, DB type, Alembic head)
    try:
        await validate_production_config_async()
    except SystemError as e:
        logger.critical("Production async configuration validation FAILED: %s", e)
        raise
    from app.core.ocr_profile import get_ocr_profile
    profile = get_ocr_profile()
    logger.info(
        "Starting 2240AI — env=%s, ocr_profile=%s (gpu=%s, workers=%d, max_pdf_pages=%d)",
        settings.APP_ENV, profile.name, profile.use_gpu, profile.max_workers, profile.max_pdf_pages,
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

    # --- AI 模型配置启动自检 ---
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

    cleanup_task = asyncio.create_task(_periodic_token_cleanup(), name="token-cleanup")

    try:
        await pomodoro_scheduler.start()
    except Exception as e:
        logger.warning("Pomodoro scheduler start failed (non-fatal): %s", e)

    try:
        from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler
        await audit_log_cleanup_scheduler.start()
    except Exception as e:
        logger.warning("Audit log cleanup scheduler start failed (non-fatal): %s", e)

    try:
        from app.services.ai_prewarm_worker import start_worker
        await start_worker()
    except Exception as e:
        logger.warning("AI prewarm worker start failed (non-fatal): %s", e)

    # Start the durable task queue pipeline worker (background task processing)
    _pipeline_worker_task: asyncio.Task | None = None
    try:
        from app.services.task_queue_worker import run_pipeline_worker, run_reaper_loop
        _pipeline_worker_task = asyncio.create_task(
            run_pipeline_worker(), name="pipeline-worker"
        )
        asyncio.create_task(
            run_reaper_loop(), name="task-reaper"
        )
    except Exception as e:
        logger.warning("Pipeline worker start failed (non-fatal): %s", e)

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    try:
        await pomodoro_scheduler.stop()
    except Exception:
        logger.exception("Pomodoro scheduler stop failed")
    try:
        from app.services.audit_cleanup_scheduler import audit_log_cleanup_scheduler
        await audit_log_cleanup_scheduler.stop()
    except Exception:
        logger.exception("Audit log cleanup scheduler stop failed")
    try:
        from app.services.ai_prewarm_worker import stop_worker
        await stop_worker()
    except Exception:
        logger.exception("AI prewarm worker stop failed")
    try:
        from app.services.ocr_executor_service import ocr_executor
        await ocr_executor.shutdown(wait=False)
    except Exception:
        logger.exception("OCR executor shutdown failed")
    try:
        from app.services.pdf_renderer_service import pdf_renderer
        await pdf_renderer.shutdown()
    except Exception:
        logger.exception("PDF renderer shutdown failed")
    logger.info("Shutting down 2240AI")


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


# --- 健康检查 ---


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

    Returns 503 (via status_code override in JSONResponse) when any
    critical dependency is unavailable. Suitable for container readiness
    checks and load balancer health checks.
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
