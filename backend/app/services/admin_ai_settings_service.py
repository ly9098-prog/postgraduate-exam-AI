from datetime import timedelta

from fastapi import Request
from sqlalchemy import Date, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.time_utils import (
    shanghai_date_utc_range,
    shanghai_now,
    shanghai_today,
    utcnow,
)
from app.models.admin import AdminAISettings, AdminAIUsageMonthly, Role
from app.models.ai_chat import AiChat
from app.models.ai_generation_log import AiGenerationLog
from app.schemas.admin_ai_settings import (
    AdminAISettingsPatchRequest,
    AdminAISettingsResponse,
    AdminAIStatsResponse,
    AdminAIUsageMonthlyResponse,
    DailyTrendPoint,
)
from app.services.admin_audit_service import write_admin_audit

DEFAULT_MONTHLY_CALL_LIMIT = 1000


def current_year_month() -> str:
    return shanghai_now().strftime("%Y-%m")


async def get_or_create_ai_settings(db: AsyncSession) -> AdminAISettings:
    result = await db.execute(
        select(AdminAISettings).order_by(AdminAISettings.id.asc()).limit(1)
    )
    settings = result.scalar_one_or_none()
    if settings:
        return settings
    settings = AdminAISettings(
        ai_parse_enabled=True, monthly_call_limit=DEFAULT_MONTHLY_CALL_LIMIT
    )
    db.add(settings)
    await db.flush()
    return settings


async def get_or_create_monthly_usage(
    db: AsyncSession, year_month: str | None = None, limit_snapshot: int | None = None
) -> AdminAIUsageMonthly:
    month = year_month or current_year_month()
    usage = await db.get(AdminAIUsageMonthly, month)
    if usage:
        return usage
    usage = AdminAIUsageMonthly(
        year_month=month, call_count=0, limit_snapshot=limit_snapshot
    )
    db.add(usage)
    await db.flush()
    return usage


async def _get_ai_settings_snapshot(db: AsyncSession) -> AdminAISettings | None:
    result = await db.execute(
        select(AdminAISettings).order_by(AdminAISettings.id.asc()).limit(1)
    )
    return result.scalar_one_or_none()


async def _get_ai_usage_snapshot(
    db: AsyncSession, year_month: str
) -> AdminAIUsageMonthly | None:
    return await db.get(AdminAIUsageMonthly, year_month)


def build_ai_settings_response(
    settings: AdminAISettings, usage: AdminAIUsageMonthly
) -> AdminAISettingsResponse:
    remaining = (
        None
        if settings.monthly_call_limit == 0
        else max(settings.monthly_call_limit - usage.call_count, 0)
    )
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
    usage = await get_or_create_monthly_usage(
        db, limit_snapshot=settings.monthly_call_limit
    )
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

    usage = await get_or_create_monthly_usage(
        db, limit_snapshot=settings.monthly_call_limit
    )
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
        "ai_setting.disable"
        if before["ai_parse_enabled"] and not settings.ai_parse_enabled
        else "ai_setting.update",
        "ai_setting",
        settings.id,
        severity="important",
        detail={
            "before": before,
            "after": after,
            "scope": "global",
            "year_month": usage.year_month,
        },
        request=request,
    )
    await db.flush()
    return build_ai_settings_response(settings, usage)


async def get_ai_usage(
    db: AsyncSession, year_month: str | None = None
) -> AdminAIUsageMonthlyResponse:
    settings = await get_or_create_ai_settings(db)
    usage = await get_or_create_monthly_usage(
        db, year_month=year_month, limit_snapshot=settings.monthly_call_limit
    )
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
    monthly_call_limit = (
        settings.monthly_call_limit if settings else DEFAULT_MONTHLY_CALL_LIMIT
    )
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

    if (
        monthly_call_limit > 0
        and call_count >= monthly_call_limit
        and not await is_super_admin(db, operator)
    ):
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


async def get_ai_stats(
    db: AsyncSession,
    days: int = 7,
    *,
    summary_days: int | None = None,
) -> AdminAIStatsResponse:
    """聚合持久化的 AI 调用统计和趋势。

    ``AiGenerationLog`` 覆盖导题/题目处理类调用，``AiChat`` 覆盖学习分析、
    错题分析等对话类调用。仪表盘需要展示完整 AI 运行情况，因此两类日志必须
    合并统计；仅统计 ``AiGenerationLog`` 会在只有对话类 AI 调用时长期显示 0。

    默认汇总指标（成功率、耗时、Token、费用）保持“本月”语义，兼容 AI 设置
    页面。仪表盘可传 ``summary_days``，让这些汇总指标与“最近 N 天”卡片口径一致。
    """
    today_date = shanghai_today()
    today_start = shanghai_date_utc_range(today_date)[0]
    month_start = shanghai_date_utc_range(today_date.replace(day=1))[0]
    trend_first_date = today_date - timedelta(days=days - 1)
    trend_start = shanghai_date_utc_range(trend_first_date)[0]
    tomorrow_start = shanghai_date_utc_range(today_date + timedelta(days=1))[0]

    if summary_days is not None:
        summary_first_date = today_date - timedelta(days=max(1, summary_days) - 1)
        summary_start = shanghai_date_utc_range(summary_first_date)[0]
    else:
        summary_start = month_start

    dialect_name = db.bind.dialect.name if db.bind else "postgresql"

    def bucket_expr(model):
        if dialect_name == "sqlite":
            return func.date(model.created_at, "+8 hours")
        return cast(model.created_at + text("INTERVAL '8 hours'"), Date)

    async def aggregate(
        model, start, end=None, *, has_success: bool
    ) -> dict[str, int]:
        conditions = [model.created_at >= start]
        if end is not None:
            conditions.append(model.created_at < end)
        success_expr = func.sum(model.success) if has_success else func.count()
        row = (
            await db.execute(
                select(
                    func.count().label("calls"),
                    func.sum(model.tokens_used).label("tokens"),
                    func.sum(model.duration_ms).label("duration_ms"),
                    success_expr.label("success_count"),
                ).where(*conditions)
            )
        ).one()
        return {
            "calls": int(row.calls or 0),
            "tokens": int(row.tokens or 0),
            "duration_ms": int(row.duration_ms or 0),
            "success_count": int(row.success_count or 0),
        }

    async def daily_rows(model, *, has_success: bool):
        bucket = bucket_expr(model)
        success_expr = func.sum(model.success) if has_success else func.count()
        return (
            await db.execute(
                select(
                    bucket.label("day"),
                    func.count().label("calls"),
                    func.sum(model.tokens_used).label("tokens"),
                    func.sum(model.duration_ms).label("duration_ms"),
                    success_expr.label("success_count"),
                )
                .where(
                    model.created_at >= trend_start,
                    model.created_at < tomorrow_start,
                )
                .group_by(bucket)
                .order_by(bucket)
            )
        ).all()

    today_generation = await aggregate(
        AiGenerationLog, today_start, tomorrow_start, has_success=True
    )
    today_chat = await aggregate(AiChat, today_start, tomorrow_start, has_success=False)
    month_generation = await aggregate(AiGenerationLog, month_start, has_success=True)
    month_chat = await aggregate(AiChat, month_start, has_success=False)
    summary_generation = await aggregate(
        AiGenerationLog, summary_start, tomorrow_start, has_success=True
    )
    summary_chat = await aggregate(
        AiChat, summary_start, tomorrow_start, has_success=False
    )

    trend_map: dict[str, dict[str, int]] = {}
    for rows in (
        await daily_rows(AiGenerationLog, has_success=True),
        await daily_rows(AiChat, has_success=False),
    ):
        for row in rows:
            raw_day = (
                row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day)
            )
            item = trend_map.setdefault(
                str(raw_day),
                {"calls": 0, "tokens": 0, "duration_ms": 0, "success_count": 0},
            )
            item["calls"] += int(row.calls or 0)
            item["tokens"] += int(row.tokens or 0)
            item["duration_ms"] += int(row.duration_ms or 0)
            item["success_count"] += int(row.success_count or 0)

    daily_trends = []
    current_date = trend_first_date
    while current_date <= today_date:
        iso_key = current_date.isoformat()
        item = trend_map.get(iso_key)
        if item:
            total_calls = item["calls"]
            daily_trends.append(
                {
                    "date": current_date.strftime("%m/%d"),
                    "calls": total_calls,
                    "tokens": item["tokens"],
                    "success_rate": round(item["success_count"] / total_calls * 100, 1)
                    if total_calls > 0
                    else 0.0,
                    "avg_latency_ms": round(item["duration_ms"] / total_calls, 1)
                    if total_calls > 0
                    else 0.0,
                }
            )
        else:
            daily_trends.append(
                {
                    "date": current_date.strftime("%m/%d"),
                    "calls": 0,
                    "tokens": 0,
                    "success_rate": 0.0,
                    "avg_latency_ms": 0.0,
                }
            )
        current_date += timedelta(days=1)

    today_calls = today_generation["calls"] + today_chat["calls"]
    month_calls = month_generation["calls"] + month_chat["calls"]
    summary_calls = summary_generation["calls"] + summary_chat["calls"]
    summary_success = (
        summary_generation["success_count"] + summary_chat["success_count"]
    )
    summary_tokens = summary_generation["tokens"] + summary_chat["tokens"]
    summary_duration_ms = (
        summary_generation["duration_ms"] + summary_chat["duration_ms"]
    )

    success_rate = (
        round(summary_success / summary_calls * 100, 1) if summary_calls > 0 else 0.0
    )
    avg_latency_ms = (
        round(summary_duration_ms / summary_calls, 1) if summary_calls > 0 else 0.0
    )

    # 费用估算：假设输入占 75%，输出占 25%
    # 输入: ¥1/1M tokens, 输出: ¥2/1M tokens
    input_tokens_est = int(summary_tokens * 0.75)
    output_tokens_est = summary_tokens - input_tokens_est
    estimated_cost = (
        round(
            (input_tokens_est / 1_000_000 * 1.0 + output_tokens_est / 1_000_000 * 2.0)
            * 100
        )
        / 100
    )

    return AdminAIStatsResponse(
        today_calls=today_calls,
        monthly_calls=month_calls,
        success_rate=success_rate,
        avg_latency_ms=avg_latency_ms,
        total_tokens=summary_tokens,
        estimated_cost=estimated_cost,
        daily_trends=[DailyTrendPoint(**d) for d in daily_trends],
    )

