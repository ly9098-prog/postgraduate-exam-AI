import logging
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.secret_crypto import sanitise_dict
from app.core.time_utils import utcnow
from app.models.admin import AuditLog

logger = logging.getLogger(__name__)

try:
    from app.core.log_context import log_event
except ImportError:  # pragma: no cover
    def log_event(_lg, _ev, **_kw):  # type: ignore[misc]
        pass


def _sanitize_detail(detail: dict | None) -> dict | None:
    """Remove sensitive values from audit detail recursively.

    Sensitive field values are replaced with ``[REDACTED]``.
    Uses ``secret_crypto.sanitise_dict`` for recursive redaction.
    """
    if detail is None:
        return None
    result = sanitise_dict(detail)
    assert isinstance(result, dict | None)  # nosec — type narrowing
    return result


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
        detail=_sanitize_detail(detail),
        ip=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
        status=status,
        error_message=error_message,
        created_at=utcnow(),
    )
    db.add(audit_log)

    try:
        log_event(
            logger, "admin.audit.write", "info",
            operator_id=operator.id if operator else None,
            operator_name=operator.username if operator else None,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            severity=severity,
            status=status,
        )
    except Exception:
        pass  # Never let logging failure crash audit write

    return audit_log


async def write_failed_admin_audit_safely(
    operator: AdminPrincipal | None,
    action: str,
    resource_type: str,
    resource_id: str | int | None,
    severity: str = "normal",
    detail: dict | None = None,
    request: Request | None = None,
    error_message: str | None = None,
) -> AuditLog | None:
    """Write a failed-operation audit log using an independent session.

    This is intended for use inside exception handlers where the original
    business DB session may have been rolled back or is in an unusable
    state.  A *separate* session is created so the failed audit is
    committed independently and is never affected by the outer transaction
    rollback.

    If the audit write itself fails, the exception is logged and
    swallowed — it must never mask the original business exception.
    """
    from app.core.database import async_session

    detail = _sanitize_detail(detail)

    try:
        async with async_session() as fail_db:
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
                status="failed",
                error_message=error_message,
                created_at=utcnow(),
            )
            fail_db.add(audit_log)
            await fail_db.commit()
            await fail_db.refresh(audit_log)
            return audit_log
    except Exception:
        logger.exception("Failed to record failed audit log (non-fatal)")
        return None


def _normalize_audit_range(created_from, created_to):
    """Normalize a date range to [start, end_exclusive) semi-open interval.

    Returns (start, end_exclusive).
    - *created_to* is used directly as the **exclusive** upper bound.
      No midnight adjustment is performed — the caller is responsible
      for passing the correct exclusive-end value.
    - Default: last 183 days.
    - Span must not exceed 365 days.
    """
    now = utcnow()
    start = created_from or now - timedelta(days=183)
    end_exclusive = created_to or now

    if start >= end_exclusive:
        raise ValueError("开始时间不能晚于结束时间")
    if end_exclusive - start > timedelta(days=365):
        raise ValueError("审计日志查询跨度不能超过 1 年")
    return start, end_exclusive


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
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    keyword: str | None = None,
) -> tuple[list[AuditLog], int]:
    start, end_exclusive = _normalize_audit_range(created_from, created_to)
    conditions = [AuditLog.created_at >= start, AuditLog.created_at < end_exclusive]
    if operator_id is not None:
        conditions.append(AuditLog.operator_id == operator_id)
    if action:
        pattern = action.replace("*", "%")
        if "%" in pattern:
            conditions.append(AuditLog.action.like(pattern, escape="\\"))
        else:
            conditions.append(AuditLog.action == action)
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if resource_id:
        conditions.append(AuditLog.resource_id == resource_id)
    if severity:
        conditions.append(AuditLog.severity == severity)
    if log_status:
        conditions.append(AuditLog.status == log_status)
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            or_(
                AuditLog.action.ilike(pattern, escape="\\"),
                AuditLog.resource_type.ilike(pattern, escape="\\"),
                AuditLog.resource_id.ilike(pattern, escape="\\"),
                AuditLog.operator_name.ilike(pattern, escape="\\"),
            )
        )

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


async def cleanup_expired_admin_audit_logs(
    db: AsyncSession,
    retention_days: int,
    batch_size: int,
) -> int:
    """Delete audit logs older than *retention_days* in batches.

    Returns total number of deleted rows.
    """
    from sqlalchemy import delete as sa_delete

    cutoff = utcnow() - timedelta(days=retention_days)
    total_deleted = 0

    while True:
        # Fetch batch of IDs to delete
        batch_ids = (
            await db.execute(
                select(AuditLog.id)
                .where(AuditLog.created_at < cutoff)
                .order_by(AuditLog.id)
                .limit(batch_size)
            )
        ).scalars().all()

        if not batch_ids:
            break

        await db.execute(sa_delete(AuditLog).where(AuditLog.id.in_(batch_ids)))
        await db.commit()
        total_deleted += len(batch_ids)

    return total_deleted
