"""Infrastructure readiness probes, independent of application assembly."""

import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def get_db_pool_metrics() -> dict:
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


async def check_database(session_factory: SessionFactory) -> bool:
    """Check PostgreSQL is reachable."""
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def check_redis(*, redis_url: str, production_mode: bool) -> bool:
    """Check Redis is reachable and responsive.

    In production, Redis is mandatory — returns False if not configured.
    """
    if not redis_url:
        from app.core.deployment_profile import (
            DeploymentProfile,
            detect_deployment_profile,
        )

        try:
            if (
                detect_deployment_profile() == DeploymentProfile.CLOUD_API
                or production_mode
            ):
                return False
        except Exception:
            return False
        return True  # Not configured in dev — not a failure
    try:
        from app.core.cache import cache

        # Must be a real Redis PING: cache.set/get silently fall back to the
        # in-process cache, which would report "ok" during a Redis outage and
        # keep the instance in the load balancer.
        return await cache.ping()
    except Exception:
        return False


async def check_alembic_head(
    session_factory: SessionFactory, *, script_location: str,
) -> bool:
    """Verify the database migration is at the head revision."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        async with session_factory() as session:
            row = (
                await session.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
            db_revision = row or ""

        alembic_cfg = Config()
        alembic_cfg.set_main_option(
            "script_location",
            script_location,
        )
        script = ScriptDirectory.from_config(alembic_cfg)
        head_revision = script.get_current_head()

        return bool(db_revision and head_revision and db_revision == head_revision)
    except Exception:
        return False


async def check_staging() -> bool:
    """Check the staging directory is writable."""
    from app.services.staging_storage import _STAGING_DIR

    try:
        path = _STAGING_DIR
        path.mkdir(parents=True, exist_ok=True)
        return os.access(str(path), os.W_OK)
    except Exception:
        return False


async def check_staging_space() -> dict:
    """Return staging directory space info (free bytes, total bytes, used percent).

    Returns empty dict on failure (non-critical, informational only).
    """
    from app.services.staging_storage import _STAGING_DIR

    try:
        st = os.statvfs(str(_STAGING_DIR))
        free_bytes = st.f_frsize * st.f_bavail
        total_bytes = st.f_frsize * st.f_blocks
        used_percent = (
            ((total_bytes - free_bytes) / total_bytes * 100) if total_bytes > 0 else 0
        )
        return {
            "staging_free_bytes": free_bytes,
            "staging_total_bytes": total_bytes,
            "staging_used_percent": round(used_percent, 1),
        }
    except Exception:
        return {}


async def check_queue(*, redis_url: str, production_mode: bool) -> str | None:
    """Check durable queue health.

    Returns "ok" if queue is healthy, "degraded" if queue depth is high,
    "unavailable" if Redis is unreachable in production (no hysteresis
    for critical infrastructure deps), or None if Redis not configured.
    """
    if not redis_url:
        return None
    try:
        from app.services.task_queue_service import task_queue

        total = 0
        for tt in ("import_pipeline", "image_pipeline", "excel_pipeline"):
            total += await task_queue.ready_length_v2(tt)
            total += await task_queue.processing_length_v2(tt)
        if total > 100:
            return "degraded"
        return "ok"
    except Exception:
        # Redis error is a critical infrastructure failure — not "degraded"
        if production_mode:
            return "unavailable"
        return "degraded"
