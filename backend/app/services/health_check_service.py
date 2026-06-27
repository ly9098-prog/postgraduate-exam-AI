"""System health check service — AI model config check.

Used by:
- GET /api/admin/v1/system/health endpoint
- App startup lifespan self-check
- Batch image import pre-check trace events
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict

from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_ai_config import AdminAiModelConfig

logger = logging.getLogger(__name__)


@dataclass
class AiModelConfigCheck:
    """Health check result for admin_ai_model_configs."""
    ok: bool = True
    severity: str = "ok"  # "ok" | "warning" | "error"
    code: str = ""
    message: str = "AI 模型配置正常"
    enabled_count: int = 0
    default_count: int = 0
    providers: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)


@dataclass
class SystemHealthResult:
    """Top-level health check response."""
    ok: bool = True
    checks: dict = field(default_factory=dict)


async def check_ai_model_config(db: AsyncSession) -> AiModelConfigCheck:
    """Check admin_ai_model_configs for enabled/default model availability.

    Does NOT fall back to env vars — the purpose is to detect whether the
    admin-managed model config is complete, regardless of env var presence.
    """
    result = await db.execute(
        select(AdminAiModelConfig).order_by(
            AdminAiModelConfig.is_default.desc(),
            AdminAiModelConfig.sort_order.asc(),
        )
    )
    all_models = result.scalars().all()

    enabled = [m for m in all_models if m.is_enabled]
    default = [m for m in enabled if m.is_default]

    enabled_count = len(enabled)
    default_count = len(default)

    providers: list[str] = []
    feature_set: set[str] = set()
    for m in enabled:
        if m.provider and m.provider not in providers:
            providers.append(m.provider)
        if m.features and isinstance(m.features, list):
            feature_set.update(m.features)
        elif m.feature:
            feature_set.add(m.feature)

    check = AiModelConfigCheck(
        enabled_count=enabled_count,
        default_count=default_count,
        providers=sorted(providers),
        features=sorted(feature_set),
    )

    if enabled_count == 0:
        check.ok = False
        check.severity = "error"
        check.code = "AI_MODEL_NOT_CONFIGURED"
        check.message = "AI 模型未配置：OCR 纠错、AI 修复和视觉兜底可能不可用"
    elif default_count == 0:
        check.ok = False
        check.severity = "warning"
        check.code = "AI_MODEL_DEFAULT_MISSING"
        check.message = "AI 模型未设置默认项：系统将按排序选择模型，建议设置默认模型"
    else:
        check.ok = True
        check.severity = "ok"
        check.code = "AI_MODEL_CONFIG_OK"
        check.message = "AI 模型配置正常"

    return check


async def check_system_health(db: AsyncSession) -> SystemHealthResult:
    """Run all health checks and return aggregate result."""
    ai_config = await check_ai_model_config(db)

    result = SystemHealthResult(
        checks={
            "ai_model_config": asdict(ai_config),
        }
    )

    # Overall ok = no error-level checks
    result.ok = all(
        c.get("severity") != "error"
        for c in result.checks.values()
    )

    return result


async def check_ai_model_config_summary(db: AsyncSession) -> dict | None:
    """Lightweight check — returns a dict summary or None if no enabled model.

    Used by batch image import to decide whether to emit a warning trace event.
    Returns None when the check should be skipped (DB unavailable, etc.).
    """
    try:
        check = await check_ai_model_config(db)
        if not check.ok:
            return asdict(check)
        return None
    except Exception as exc:
        logger.warning("AI model config check failed (non-fatal): %s", exc)
        return None
