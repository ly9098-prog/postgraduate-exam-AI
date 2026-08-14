"""System health check service — AI model config check.

Used by:
- GET /api/admin/v1/system/health endpoint
- App startup lifespan self-check
- Batch image import pre-check trace events
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
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




def check_ai_runtime_health() -> dict:
    """Return process-local AI admission/circuit health without external I/O."""
    try:
        from app.core.ai_runtime_guard import ai_runtime_guard
        from app.core.config import settings

        metrics = ai_runtime_guard.metrics_snapshot()
        open_circuits = int(metrics.get("open_circuits") or 0)
        severity = "warning" if open_circuits > 0 else "ok"
        return {
            "ok": open_circuits == 0,
            "severity": severity,
            "code": "AI_PROVIDER_CIRCUIT_OPEN" if open_circuits else "AI_RUNTIME_OK",
            "message": (
                f"AI 提供方熔断中：{open_circuits} 个端点"
                if open_circuits
                else "AI 运行时资源保护正常"
            ),
            "open_circuits": open_circuits,
            "in_flight": int(metrics.get("in_flight") or 0),
            "rejected_rate_limit": int(metrics.get("rejected_rate_limit") or 0),
            "rejected_overload": int(metrics.get("rejected_overload") or 0),
            "max_concurrency": int(settings.AI_MAX_CONCURRENCY),
            "user_rpm_limit": int(settings.AI_USER_RPM_LIMIT),
            "single_max_tokens": int(settings.AI_SINGLE_MAX_TOKENS),
        }
    except Exception as exc:
        logger.warning("AI runtime health check failed: %s", exc)
        return {
            "ok": False,
            "severity": "warning",
            "code": "AI_RUNTIME_HEALTH_CHECK_FAILED",
            "message": "AI 运行时健康检查失败",
        }


async def check_async_task_health(db: AsyncSession) -> dict:
    """Return a compact async-task SLI summary for the system health endpoint."""
    try:
        from app.services.task_observability_service import collect_task_diagnostics

        snapshot = await collect_task_diagnostics(db)
        health = snapshot["health"]
        outbox = snapshot["outbox"]
        redis = snapshot["redis"]
        projection = snapshot["projection"]
        issues = health.get("issues") or []
        if health["severity"] == "ok":
            message = (
                "异步任务链路正常"
                if snapshot.get("async_runtime_expected")
                else "本地 Web-only 模式：异步任务运行时未启用"
            )
        else:
            message = "；".join(str(item.get("message") or "") for item in issues[:3])
        return {
            "ok": bool(health["ok"]),
            "severity": health["severity"],
            "code": issues[0]["code"] if issues else "ASYNC_TASKS_OK",
            "message": message,
            "issues": issues,
            "redis_available": bool(redis.get("available")),
            "outbox_unpublished": int(outbox.get("unpublished") or 0),
            "outbox_oldest_seconds": int(outbox.get("oldest_unpublished_seconds") or 0),
            "queue_ready": int((redis.get("totals") or {}).get("ready", 0)),
            "queue_dead": int((redis.get("totals") or {}).get("dead", 0)),
            "projection_unprojected": int(projection.get("unprojected") or 0),
        }
    except Exception as exc:
        logger.warning("async task health check failed: %s", exc)
        return {
            "ok": False,
            "severity": "error",
            "code": "ASYNC_TASK_HEALTH_CHECK_FAILED",
            "message": "异步任务健康检查失败",
            "issues": [],
        }


async def check_system_health(db: AsyncSession) -> SystemHealthResult:
    """Run all health checks and return aggregate result."""
    ai_config = await check_ai_model_config(db)
    ai_runtime = check_ai_runtime_health()
    async_tasks = await check_async_task_health(db)

    result = SystemHealthResult(
        checks={
            "ai_model_config": asdict(ai_config),
            "ai_runtime": ai_runtime,
            "async_tasks": async_tasks,
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
