from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text

from app.core.admin_security import require_permissions
from app.core.cache import CacheUnavailableError, cache
from app.core.database import async_session

router = APIRouter(prefix="/api/admin/v1/health", tags=["admin-health"])


@router.get("/live")
async def live_health():
    return {"status": "ok"}


@router.get("/ready")
async def ready_health(_=Depends(require_permissions("dashboard:read"))):
    db_status = "ok"
    redis_status = "degraded"

    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "unavailable"

    if db_status == "ok":
        try:
            await cache.set_strict("admin:health:ping", "pong", ttl=10)
            pong = await cache.get_strict("admin:health:ping")
            if pong == "pong":
                redis_status = "ok"
        except CacheUnavailableError:
            redis_status = "degraded"

    status_value = "ok" if db_status == "ok" else "degraded"
    payload = {"status": status_value, "db": db_status}
    if db_status == "ok":
        payload["redis"] = redis_status
    else:
        payload["redis"] = "degraded"
    return payload


@router.get("/export")
async def export_health(_=Depends(require_permissions("dashboard:read"))):
    """Export subsystem health — protected, no secrets exposed."""
    from app.models.export_task import ExportTask
    from app.schemas.export_task import ExportTaskStatus
    from app.services.export.export_metrics import get_metrics
    from app.services.export.push_service import get_active_connections

    now = datetime.now(UTC).replace(tzinfo=None)
    result = {"status": "unknown", "database": "unknown", "processor": {}, "tasks": {}, "pubsub": {}}

    # DB checks
    try:
        async with async_session() as db:
            # Pending count
            pending_count = (
                await db.execute(
                    select(func.count(ExportTask.id)).where(
                        ExportTask.status == ExportTaskStatus.PENDING
                    )
                )
            ).scalar() or 0

            # Processing count
            processing_count = (
                await db.execute(
                    select(func.count(ExportTask.id)).where(
                        ExportTask.status == ExportTaskStatus.PROCESSING
                    )
                )
            ).scalar() or 0

            # Zombie count (processing without recent heartbeat)
            zombie_cutoff = now - timedelta(seconds=900)
            zombie_count = 0
            if processing_count > 0:
                zombie_count = (
                    await db.execute(
                        select(func.count(ExportTask.id)).where(
                            ExportTask.status == ExportTaskStatus.PROCESSING,
                            ExportTask.heartbeat_at.isnot(None),
                            ExportTask.heartbeat_at < zombie_cutoff,
                        )
                    )
                ).scalar() or 0

            result["database"] = "ok"
            result["tasks"] = {
                "pending": pending_count,
                "processing": processing_count,
                "zombie": zombie_count,
            }

    except Exception as e:
        result["database"] = str(e)[:100]

    # Redis / PubSub
    try:
        if cache.is_enabled:
            result["pubsub"] = {"subscribed": True}
        else:
            result["pubsub"] = {"subscribed": False, "note": "Redis not configured"}
    except Exception:
        result["pubsub"] = {"subscribed": False}

    # Processor state (from metrics)
    metrics = get_metrics()
    result["processor"] = {
        "healthy": metrics["export_tasks_processing"] < 10,  # heuristic
        "ws_connections": metrics["export_ws_connections"],
        "active_ws": get_active_connections(),
    }

    # Overall status
    if result["database"] == "ok":
        result["status"] = "ok"
    else:
        result["status"] = "degraded"

    return result


@router.get("/export/metrics")
async def export_metrics(_=Depends(require_permissions("dashboard:read"))):
    """Export metrics in application/json format."""
    from app.services.export.export_metrics import get_metrics
    return get_metrics()
