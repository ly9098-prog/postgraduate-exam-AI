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
from app.core.config import settings
from app.core.database import init_db
from app.core.logging_config import setup_logging
from app.core.sentry import init_sentry

setup_logging()
init_sentry()

logger = logging.getLogger("2240ai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting 2240AI — env=%s", settings.APP_ENV)
    os.makedirs("static/formulas", exist_ok=True)
    await init_db()
    yield
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

# 静态文件服务（开发用公式图片）
os.makedirs("static/formulas", exist_ok=True)
app.mount("/static/formulas", StaticFiles(directory="static/formulas", html=False), name="static_formulas")
