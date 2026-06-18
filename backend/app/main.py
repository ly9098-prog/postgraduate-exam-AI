import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.auth import router as auth_router
from app.api.v1.questions import router as questions_router
from app.api.v1.practice import router as practice_router
from app.api.v1.wrong_questions import router as wrong_questions_router
from app.api.v1.ai import router as ai_router
from app.api.v1.rag import router as rag_router
from app.api.v1.imports import router as imports_router
from app.api.v1.behavior import router as behavior_router
from app.api.v1.review import router as review_router
from app.api.v1.stats import router as stats_router
from app.api.v1.knowledge_points import router as knowledge_points_router
from app.api.v1.ai_import import router as ai_import_router
from app.api.v1.cache import router as cache_router
from app.api.v1.health import router as health_router
from app.api.v1.pomodoro import router as pomodoro_router
from app.api.v1.admin_ai_settings import router as admin_ai_settings_router
from app.api.v1.admin_audit_logs import router as admin_audit_logs_router
from app.api.v1.admin_auth import router as admin_auth_router
from app.api.v1.admin_app_users import router as admin_app_users_router
from app.api.v1.admin_dashboard import router as admin_dashboard_router
from app.api.v1.admin_health import router as admin_health_router
from app.api.v1.admin_imports import router as admin_imports_router
from app.api.v1.admin_questions import router as admin_questions_router
from app.api.v1.admin_rbac import router as admin_rbac_router
from app.api.v1.admin_subjects import router as admin_subjects_router
from app.api.v1.admin_users import router as admin_users_router
from app.api.v1.admin_watermark_rules import router as admin_watermark_rules_router
from app.api.v1.admin_ai_config import router as admin_ai_config_router
from app.api.v1.sync import router as sync_router
from app.core.config import settings
from app.core.database import init_db
from app.core.logging_config import setup_logging
from app.core.sentry import init_sentry
from app.services.admin_bootstrap_service import ensure_dev_super_admin

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
    from app.core.ocr_profile import get_ocr_profile
    profile = get_ocr_profile()
    logger.info(
        "Starting 2240AI — env=%s, ocr_profile=%s (gpu=%s, workers=%d, max_pdf_pages=%d)",
        settings.APP_ENV, profile.name, profile.use_gpu, profile.max_workers, profile.max_pdf_pages,
    )
    os.makedirs("static/formulas", exist_ok=True)
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

    cleanup_task = asyncio.create_task(_periodic_token_cleanup(), name="token-cleanup")

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
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
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    logger.info(
        "%s %s → %s (%.0fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed * 1000,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # 兜底：未被 HTTPException 包装的异常，必须返回 JSON。
    # 否则前端 wx.uploadFile 拿到的是 "Internal Server Error" 纯文本，
    # JSON.parse 直接抛 "Unexpected token I in JSON at position 0"，错误信息全丢。
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


# --- 健康检查 ---


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.APP_ENV}


# --- 路由 ---

app.include_router(auth_router)
app.include_router(questions_router)
app.include_router(practice_router)
app.include_router(wrong_questions_router)
app.include_router(ai_router)
app.include_router(rag_router)
app.include_router(imports_router)
app.include_router(behavior_router)
app.include_router(review_router)
app.include_router(stats_router)
app.include_router(knowledge_points_router)
app.include_router(ai_import_router)
app.include_router(cache_router)
app.include_router(health_router)
app.include_router(admin_auth_router)
app.include_router(admin_ai_settings_router)
app.include_router(admin_app_users_router)
app.include_router(admin_audit_logs_router)
app.include_router(admin_dashboard_router)
app.include_router(admin_health_router)
app.include_router(admin_imports_router)
app.include_router(admin_questions_router)
app.include_router(admin_rbac_router)
app.include_router(admin_subjects_router)
app.include_router(admin_users_router)
app.include_router(admin_watermark_rules_router)
app.include_router(admin_ai_config_router)
app.include_router(sync_router)
app.include_router(pomodoro_router)

# 静态文件服务（开发用公式图片）
os.makedirs("static/formulas", exist_ok=True)
app.mount("/static/formulas", StaticFiles(directory="static/formulas", html=False), name="static_formulas")
