from datetime import datetime, date, time, timedelta

from fastapi import Request
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.core.admin_security import AdminPrincipal
from app.models.admin import AdminAISettings, AdminAIUsageMonthly, Role
from app.models.ai_generation_log import AiGenerationLog
from app.schemas.admin_ai_settings import AdminAISettingsPatchRequest, AdminAISettingsResponse, AdminAIUsageMonthlyResponse, AdminAIStatsResponse, DailyTrendPoint
from app.services.admin_audit_service import write_admin_audit

DEFAULT_MONTHLY_CALL_LIMIT = 1000


def current_year_month() -> str:
    return utcnow().strftime("%Y-%m")


async def get_or_create_ai_settings(db: AsyncSession) -> AdminAISettings:
    result = await db.execute(select(AdminAISettings).order_by(AdminAISettings.id.asc()).limit(1))
    settings = result.scalar_one_or_none()
    if settings:
        return settings
    settings = AdminAISettings(ai_parse_enabled=True, monthly_call_limit=DEFAULT_MONTHLY_CALL_LIMIT)
    db.add(settings)
    await db.flush()
    return settings


async def get_or_create_monthly_usage(db: AsyncSession, year_month: str | None = None, limit_snapshot: int | None = None) -> AdminAIUsageMonthly:
    month = year_month or current_year_month()
    usage = await db.get(AdminAIUsageMonthly, month)
    if usage:
        return usage
    usage = AdminAIUsageMonthly(year_month=month, call_count=0, limit_snapshot=limit_snapshot)
    db.add(usage)
    await db.flush()
    return usage


async def _get_ai_settings_snapshot(db: AsyncSession) -> AdminAISettings | None:
    result = await db.execute(select(AdminAISettings).order_by(AdminAISettings.id.asc()).limit(1))
    return result.scalar_one_or_none()


async def _get_ai_usage_snapshot(db: AsyncSession, year_month: str) -> AdminAIUsageMonthly | None:
    return await db.get(AdminAIUsageMonthly, year_month)


def build_ai_settings_response(settings: AdminAISettings, usage: AdminAIUsageMonthly) -> AdminAISettingsResponse:
    remaining = None if settings.monthly_call_limit == 0 else max(settings.monthly_call_limit - usage.call_count, 0)
    return AdminAISettingsResponse(
        id=settings.id,
        ai_parse_enabled=settings.ai_parse_enabled,
        monthly_call_limit=settings.monthly_call_limit,
        current_usage=AdminAIUsageMonthlyResponse.model_validate(usage),
        remaining_calls=remaining,
        updated_by=settings.updated_by,
        updated_at=settings.updated_at,
    )


async def get_ai_settings(db: AsyncSession) -> AdminAISettingsResponse:
    settings = await get_or_create_ai_settings(db)
    usage = await get_or_create_monthly_usage(db, limit_snapshot=settings.monthly_call_limit)
    return build_ai_settings_response(settings, usage)


async def update_ai_settings(
    db: AsyncSession,
    data: AdminAISettingsPatchRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> AdminAISettingsResponse:
    if data.ai_parse_enabled is None and data.monthly_call_limit is None:
        raise ValueError("至少提交一个设置项")

    settings = await get_or_create_ai_settings(db)
    before = {
        "ai_parse_enabled": settings.ai_parse_enabled,
        "monthly_call_limit": settings.monthly_call_limit,
    }
    if data.ai_parse_enabled is not None:
        settings.ai_parse_enabled = data.ai_parse_enabled
    if data.monthly_call_limit is not None:
        settings.monthly_call_limit = data.monthly_call_limit
    settings.updated_by = operator.id
    settings.updated_at = utcnow()

    usage = await get_or_create_monthly_usage(db, limit_snapshot=settings.monthly_call_limit)
    if usage.limit_snapshot is None:
        usage.limit_snapshot = settings.monthly_call_limit
    usage.updated_at = utcnow()

    after = {
        "ai_parse_enabled": settings.ai_parse_enabled,
        "monthly_call_limit": settings.monthly_call_limit,
    }
    await write_admin_audit(
        db,
        operator,
        "ai_setting.disable" if before["ai_parse_enabled"] and not settings.ai_parse_enabled else "ai_setting.update",
        "ai_setting",
        settings.id,
        severity="important",
        detail={"before": before, "after": after, "scope": "global", "year_month": usage.year_month},
        request=request,
    )
    await db.flush()
    return build_ai_settings_response(settings, usage)


async def get_ai_usage(db: AsyncSession, year_month: str | None = None) -> AdminAIUsageMonthlyResponse:
    settings = await get_or_create_ai_settings(db)
    usage = await get_or_create_monthly_usage(db, year_month=year_month, limit_snapshot=settings.monthly_call_limit)
    return AdminAIUsageMonthlyResponse.model_validate(usage)


async def is_super_admin(db: AsyncSession, operator: AdminPrincipal) -> bool:
    result = await db.execute(select(Role.name).where(Role.id == operator.role_id))
    return result.scalar_one_or_none() == "super_admin"


async def ensure_ai_parse_allowed(
    db: AsyncSession,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> None:
    settings = await _get_ai_settings_snapshot(db)
    usage = await _get_ai_usage_snapshot(db, current_year_month())
    ai_parse_enabled = settings.ai_parse_enabled if settings else True
    monthly_call_limit = settings.monthly_call_limit if settings else DEFAULT_MONTHLY_CALL_LIMIT
    year_month = usage.year_month if usage else current_year_month()
    call_count = usage.call_count if usage else 0

    if not ai_parse_enabled:
        await write_admin_audit(
            db,
            operator,
            "ai_parse.blocked",
            "ai_setting",
            settings.id if settings else None,
            detail={"reason": "disabled", "scope": "global", "year_month": year_month},
            request=request,
            status="failed",
            error_message="AI 解析已全局关闭",
        )
        await db.commit()
        raise PermissionError("AI 解析已全局关闭")

    if monthly_call_limit > 0 and call_count >= monthly_call_limit and not await is_super_admin(db, operator):
        await write_admin_audit(
            db,
            operator,
            "ai_quota.exhausted",
            "ai_usage",
            year_month,
            detail={
                "year_month": year_month,
                "call_count": call_count,
                "monthly_call_limit": monthly_call_limit,
                "scope": "global",
            },
            request=request,
            status="failed",
            error_message="AI 解析月度额度已用尽",
        )
        await db.commit()
        raise PermissionError("AI 解析月度额度已用尽")


async def get_ai_stats(db: AsyncSession, days: int = 7) -> AdminAIStatsResponse:
    """从 AiGenerationLog 聚合统计数据和趋势。"""
    now = utcnow()
    today_start = datetime.combine(now.date(), time.min)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    trend_start = today_start - timedelta(days=days - 1)

    dialect_name = db.bind.dialect.name if db.bind else "postgresql"
    bucket_expr = func.date(AiGenerationLog.created_at) if dialect_name == "sqlite" else cast(AiGenerationLog.created_at, Date)

    # 当日统计
    today_row = (
        await db.execute(
            select(
                func.count().label("calls"),
                func.sum(AiGenerationLog.tokens_used).label("tokens"),
                func.avg(AiGenerationLog.duration_ms).label("latency"),
                func.sum(AiGenerationLog.success).label("success_count"),
            )
            .where(AiGenerationLog.created_at >= today_start, AiGenerationLog.created_at < today_start + timedelta(days=1))
        )
    ).one()

    # 本月统计
    month_row = (
        await db.execute(
            select(
                func.count().label("calls"),
                func.sum(AiGenerationLog.tokens_used).label("tokens"),
                func.avg(AiGenerationLog.duration_ms).label("latency"),
                func.sum(AiGenerationLog.success).label("success_count"),
            )
            .where(AiGenerationLog.created_at >= month_start)
        )
    ).one()

    # 日趋势
    trend_rows = (
        await db.execute(
            select(
                bucket_expr.label("day"),
                func.count().label("calls"),
                func.sum(AiGenerationLog.tokens_used).label("tokens"),
                func.avg(AiGenerationLog.duration_ms).label("latency"),
                func.sum(AiGenerationLog.success).label("success_count"),
                func.count().label("total"),
            )
            .where(AiGenerationLog.created_at >= trend_start, AiGenerationLog.created_at < today_start + timedelta(days=1))
            .group_by(bucket_expr)
            .order_by(bucket_expr)
        )
    ).all()

    trend_map = {}
    for row in trend_rows:
        raw_day = row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day)
        total_calls = int(row.calls or 0)
        success_count = int(row.success_count or 0)
        trend_map[str(raw_day)] = {
            "date": str(raw_day)[5:].replace("-", "/"),  # "2026-06-10" → "06/10"
            "calls": total_calls,
            "tokens": int(row.tokens or 0),
            "success_rate": round(success_count / total_calls * 100, 1) if total_calls > 0 else 0.0,
            "avg_latency_ms": round(float(row.latency or 0), 1),
        }

    daily_trends = []
    current = trend_start
    while current < today_start + timedelta(days=1):
        key = current.strftime("%m/%d")
        iso_key = current.date().isoformat()
        if iso_key in trend_map:
            daily_trends.append(trend_map[iso_key])
        else:
            daily_trends.append({"date": key, "calls": 0, "tokens": 0, "success_rate": 0.0, "avg_latency_ms": 0.0})
        current += timedelta(days=1)

    today_calls = int(today_row.calls or 0)
    month_calls = int(month_row.calls or 0)
    month_success = int(month_row.success_count or 0)
    month_tokens = int(month_row.tokens or 0)
    month_latency = float(month_row.latency or 0)

    success_rate = round(month_success / month_calls * 100, 1) if month_calls > 0 else 0.0
    avg_latency_ms = round(month_latency, 1) if month_calls > 0 else 0.0

    # 费用估算：假设输入占 75%，输出占 25%
    # 输入: ¥1/1M tokens, 输出: ¥2/1M tokens
    input_tokens_est = int(month_tokens * 0.75)
    output_tokens_est = month_tokens - input_tokens_est
    estimated_cost = round((input_tokens_est / 1_000_000 * 1.0 + output_tokens_est / 1_000_000 * 2.0) * 100) / 100

    return AdminAIStatsResponse(
        today_calls=today_calls,
        monthly_calls=month_calls,
        success_rate=success_rate,
        avg_latency_ms=avg_latency_ms,
        total_tokens=month_tokens,
        estimated_cost=estimated_cost,
        daily_trends=[DailyTrendPoint(**d) for d in daily_trends],
    )
