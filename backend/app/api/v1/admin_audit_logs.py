from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.core.runtime_paths import API_ADMIN_V1_PREFIX
from app.core.time_utils import normalize_to_naive_utc
from app.models.admin import AuditLog
from app.schemas.admin_audit import AdminAuditLogDetail, AdminAuditLogListItem
from app.schemas.common import paginated_response
from app.services.admin_audit_service import get_admin_audit_log, list_admin_audit_logs

router = APIRouter(prefix=f"{API_ADMIN_V1_PREFIX}/audit-logs", tags=["admin-audit-logs"])


def _build_detail_summary(log: AuditLog) -> dict | None:
    """Extract a safe display summary from the audit log."""
    detail = getattr(log, "detail", None)
    if not detail or not isinstance(detail, dict):
        return None

    summary = {}
    if "question" in detail and isinstance(detail["question"], dict):
        q = detail["question"]
        for key in ("id", "content_preview", "subject_name", "question_type"):
            if key in q:
                summary[key] = q[key]
    if "content_preview" in detail:
        summary["content_preview"] = detail["content_preview"]
    if "subject_name" in detail:
        summary["subject_name"] = detail["subject_name"]
    if "question_type" in detail:
        summary["question_type"] = detail["question_type"]

    resource_type = getattr(log, "resource_type", None)
    resource_id = getattr(log, "resource_id", None)
    if resource_type and resource_id and not summary:
        summary["resource_label"] = f"{resource_type}#{resource_id}"

    return summary if summary else None


@router.get("", response_model=None)  # response_model handled by paginated_response
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    operator_id: int | None = Query(default=None, alias="operatorId"),
    action: str | None = None,
    resource_type: str | None = Query(default=None, alias="resourceType"),
    resource_id: str | None = Query(default=None, alias="resourceId"),
    severity: str | None = Query(
        default=None, pattern="^(critical|important|normal|low)$"
    ),
    log_status: str | None = Query(
        default=None, alias="status", pattern="^(success|failed)$"
    ),
    created_from: datetime | None = Query(default=None, alias="from"),
    created_to: datetime | None = Query(default=None, alias="to"),
    keyword: str | None = Query(default=None),
    _=Depends(require_permissions("audit:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        # Normalize input datetimes: treat any received datetime as UTC
        norm_from = normalize_to_naive_utc(created_from) if created_from else None
        norm_to = normalize_to_naive_utc(created_to) if created_to else None

        # Sanitize keyword
        safe_keyword = keyword.strip()[:200] if keyword else None
        # Escape LIKE special chars
        if safe_keyword:
            safe_keyword = safe_keyword.replace("%", "\\%").replace("_", "\\_")

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
            created_from=norm_from,
            created_to=norm_to,
            keyword=safe_keyword,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    items = []
    for log in logs:
        item = AdminAuditLogListItem.model_validate(log)
        item.detail_summary = _build_detail_summary(log)
        items.append(item)
    return paginated_response(items, total, page, page_size)


@router.get("/{audit_log_id}", response_model=AdminAuditLogDetail)
async def get_audit_log(
    audit_log_id: int,
    _=Depends(require_permissions("audit:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        log = await get_admin_audit_log(db, audit_log_id)
        result = AdminAuditLogDetail.model_validate(log)

        from app.services.audit_question_resolver import resolve_question_audit_detail

        result.question_detail = await resolve_question_audit_detail(
            db,
            audit_log_action=log.action,
            audit_log_resource_type=log.resource_type,
            audit_log_resource_id=log.resource_id,
            detail=log.detail,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
