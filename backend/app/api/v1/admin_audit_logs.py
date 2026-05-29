from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.admin_audit import AdminAuditLogDetail, AdminAuditLogListItem
from app.schemas.common import paginated_response
from app.services.admin_audit_service import get_admin_audit_log, list_admin_audit_logs

router = APIRouter(prefix="/api/admin/v1/audit-logs", tags=["admin-audit-logs"])


@router.get("")
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    operator_id: int | None = Query(default=None, alias="operatorId"),
    action: str | None = None,
    resource_type: str | None = Query(default=None, alias="resourceType"),
    resource_id: str | None = Query(default=None, alias="resourceId"),
    severity: str | None = Query(default=None, pattern="^(critical|important|normal|low)$"),
    log_status: str | None = Query(default=None, alias="status", pattern="^(success|failed)$"),
    created_from: datetime | None = Query(default=None, alias="from"),
    created_to: datetime | None = Query(default=None, alias="to"),
    _=Depends(require_permissions("audit:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        logs, total = await list_admin_audit_logs(
            db,
            page,
            page_size,
            operator_id=operator_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            severity=severity,
            log_status=log_status,
            created_from=created_from,
            created_to=created_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return paginated_response([AdminAuditLogListItem.model_validate(log) for log in logs], total, page, page_size)


@router.get("/{audit_log_id}", response_model=AdminAuditLogDetail)
async def get_audit_log(
    audit_log_id: int,
    _=Depends(require_permissions("audit:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_admin_audit_log(db, audit_log_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
