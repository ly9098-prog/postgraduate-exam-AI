from datetime import datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.models.admin import AdminAISettings, AdminAIUsageMonthly, Role
from app.schemas.admin_ai_settings import AdminAISettingsPatchRequest, AdminAISettingsResponse, AdminAIUsageMonthlyResponse
from app.services.admin_audit_service import write_admin_audit

DEFAULT_MONTHLY_CALL_LIMIT = 1000


def current_year_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


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
    settings.updated_at = datetime.utcnow()

    usage = await get_or_create_monthly_usage(db, limit_snapshot=settings.monthly_call_limit)
    if usage.limit_snapshot is None:
        usage.limit_snapshot = settings.monthly_call_limit
    usage.updated_at = datetime.utcnow()

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
