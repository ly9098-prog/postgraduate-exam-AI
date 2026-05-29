from fastapi import APIRouter
from sqlalchemy import text

from app.core.cache import cache
from app.core.database import async_session

router = APIRouter(prefix="/api/admin/v1/health", tags=["admin-health"])


@router.get("/live")
async def live_health():
    return {"status": "ok"}


@router.get("/ready")
async def ready_health():
    db_status = "ok"
    redis_status = "degraded"

    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "unavailable"

    if db_status == "ok":
        try:
            await cache.set("admin:health:ping", "pong", ttl=10)
            pong = await cache.get("admin:health:ping")
            if pong == "pong":
                redis_status = "ok"
        except Exception:
            redis_status = "degraded"

    status_value = "ok" if db_status == "ok" else "degraded"
    payload = {"status": status_value, "db": db_status}
    if db_status == "ok":
        payload["redis"] = redis_status
    else:
        payload["redis"] = "degraded"
    return payload
