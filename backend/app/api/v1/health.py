"""健康检查与版本信息端点。"""
import os
import time

from fastapi import APIRouter
from sqlalchemy import text

from app.core.cache import cache
from app.core.config import settings
from app.core.database import async_session

router = APIRouter(prefix="/api/v1", tags=["health"])

_START_TIME = time.time()


def _build_version() -> str:
    return os.environ.get("APP_VERSION", "1.0.0")


def _build_commit() -> str:
    return os.environ.get("APP_COMMIT", "unknown")


def _build_at() -> str:
    return os.environ.get("APP_BUILD_AT", "")


@router.get("/health")
async def health_check():
    services: dict[str, dict] = {}

    # Database
    try:
        t0 = time.perf_counter()
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        latency = round((time.perf_counter() - t0) * 1000, 1)
        services["database"] = {"status": "ok", "latency_ms": latency}
    except Exception as e:
        services["database"] = {"status": "unavailable", "error": str(e)}

    # Redis
    if settings.REDIS_URL:
        try:
            t0 = time.perf_counter()
            await cache.set("health:ping", "pong", ttl=10)
            pong = await cache.get("health:ping")
            latency = round((time.perf_counter() - t0) * 1000, 1)
            if pong == "pong":
                services["redis"] = {"status": "ok", "latency_ms": latency}
            else:
                services["redis"] = {"status": "unavailable"}
        except Exception as e:
            services["redis"] = {"status": "unavailable", "error": str(e)}
    else:
        services["redis"] = {"status": "disabled"}

    all_ok = all(s.get("status") == "ok" for s in services.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "version": _build_version(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "uptime": int(time.time() - _START_TIME),
        "services": services,
    }


@router.get("/version")
async def version():
    return {
        "version": _build_version(),
        "build_at": _build_at(),
        "commit": _build_commit(),
        "environment": settings.APP_ENV,
    }
