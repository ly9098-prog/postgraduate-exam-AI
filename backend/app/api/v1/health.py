"""健康检查与版本信息端点。"""

import os
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.cache import cache
from app.core.config import settings
from app.core.database import async_session
from app.core.runtime_paths import API_V1_PREFIX

router = APIRouter(prefix=f"{API_V1_PREFIX}", tags=["health"])


def _build_version() -> str:
    return os.environ.get("APP_VERSION", "1.0.0")


@router.get("/health")
async def health_check():
    service_ok: list[bool] = []

    # Database
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        service_ok.append(True)
    except Exception:
        service_ok.append(False)

    # Redis
    if settings.REDIS_URL:
        try:
            await cache.set_strict("health:ping", "pong", ttl=10)
            pong = await cache.get_strict("health:ping")
            if pong == "pong":
                service_ok.append(True)
            else:
                service_ok.append(False)
        except Exception:
            service_ok.append(False)
    else:
        service_ok.append(settings.APP_ENV.lower() in {"development", "local", "test"})

    all_ok = all(service_ok)

    # Public health output is intentionally minimal: no database errors,
    # topology, latency, environment, commit hashes or dependency details.
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "status": "ok" if all_ok else "degraded",
            "version": _build_version(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )


@router.get("/version")
async def version():
    return {"version": _build_version()}
