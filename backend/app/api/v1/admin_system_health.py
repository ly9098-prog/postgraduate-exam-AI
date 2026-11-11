"""Admin system health check API.

GET /api/admin/v1/system/health — aggregated health status including AI model config.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.core.runtime_paths import API_ADMIN_V1_PREFIX
from app.schemas.observability import SystemHealthResponse
from app.services.health_check_service import check_system_health

logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{API_ADMIN_V1_PREFIX}/system", tags=["admin-system-health"])


@router.get("/health", response_model=SystemHealthResponse)
async def system_health(
    _=Depends(require_permissions("system:read")),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated system health check.

    Returns structured health information for each subsystem.
    The overall ``ok`` field is ``true`` only when no error-level check fails.
    """
    # DB connectivity probe (fast, non-blocking)
    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    result = await check_system_health(db)
    result.checks["database"] = {
        "ok": db_ok,
        "severity": "ok" if db_ok else "error",
        "message": "数据库连接正常" if db_ok else "数据库连接异常",
    }

    if not db_ok:
        result.ok = False

    return result
