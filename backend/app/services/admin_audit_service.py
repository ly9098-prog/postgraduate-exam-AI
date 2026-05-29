from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

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
