from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.core.admin_security import AdminPrincipal
from app.models.admin import AuditLog


async def write_admin_audit(
    db: AsyncSession,
    operator: AdminPrincipal | None,
    action: str,
    resource_type: str,
    resource_id: str | int | None,
    severity: str = "normal",
    detail: dict | None = None,
    request: Request | None = None,
    status: str = "success",
    error_message: str | None = None,
) -> AuditLog:
    audit_log = AuditLog(
        operator_id=operator.id if operator else None,
        operator_name=operator.username if operator else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        severity=severity,
        detail=detail,
        ip=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
        status=status,
        error_message=error_message,
    )
    db.add(audit_log)
    return audit_log


def _normalize_audit_range(created_from, created_to):
    from datetime import datetime, timedelta

    now = utcnow()
    start = created_from or now - timedelta(days=183)
    end = created_to or now
    if start > end:
        raise ValueError("开始时间不能晚于结束时间")
    if end - start > timedelta(days=365):
        raise ValueError("审计日志查询跨度不能超过 1 年")
    return start, end


async def list_admin_audit_logs(
    db: AsyncSession,
    page: int,
    page_size: int,
    operator_id: int | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    severity: str | None = None,
    log_status: str | None = None,
    created_from=None,
    created_to=None,
) -> tuple[list[AuditLog], int]:
    from sqlalchemy import func, select

    start, end = _normalize_audit_range(created_from, created_to)
    conditions = [AuditLog.created_at >= start, AuditLog.created_at <= end]
    if operator_id is not None:
        conditions.append(AuditLog.operator_id == operator_id)
    if action:
        pattern = action.replace("*", "%")
        conditions.append(AuditLog.action.like(pattern) if "%" in pattern else AuditLog.action == action)
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if resource_id:
        conditions.append(AuditLog.resource_id == resource_id)
    if severity:
        conditions.append(AuditLog.severity == severity)
    if log_status:
        conditions.append(AuditLog.status == log_status)

    query = select(AuditLog)
    count_query = select(func.count()).select_from(AuditLog)
    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = await db.scalar(count_query)
    result = await db.execute(
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_admin_audit_log(db: AsyncSession, audit_log_id: int) -> AuditLog:
    audit_log = await db.get(AuditLog, audit_log_id)
    if not audit_log:
        raise ValueError("审计日志不存在")
    return audit_log
