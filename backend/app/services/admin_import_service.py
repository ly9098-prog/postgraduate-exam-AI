from datetime import datetime
from math import ceil
from uuid import uuid4

from fastapi import Request
from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.cache import cache
from app.models.question_import import QuestionImport
from app.schemas.admin_imports import AdminImportBatchDetail, AdminImportEnrichResponse, AdminImportQuestionItem
from app.services.admin_audit_service import write_admin_audit

_TASK_TTL_SECONDS = 86400


async def list_import_batches(
    db: AsyncSession,
    page: int,
    page_size: int,
    status: str | None = None,
    source_type: str | None = None,
    keyword: str | None = None,
) -> tuple[list[dict], int]:
    conditions = _batch_conditions(status, source_type, keyword)
    total_query = select(func.count()).select_from(select(QuestionImport.batch_id).where(*conditions).group_by(QuestionImport.batch_id).subquery())
    total = await db.scalar(total_query)

    result = await db.execute(
        _batch_summary_query(conditions)
        .order_by(desc("updated_at"), desc("created_at"), QuestionImport.batch_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [_batch_row_to_dict(row) for row in result.all()], int(total or 0)


async def get_import_batch_detail(
    db: AsyncSession,
    batch_id: str,
    page: int,
    page_size: int,
    status: str | None = None,
) -> AdminImportBatchDetail:
    batch_conditions = [QuestionImport.batch_id == batch_id]
    summary_result = await db.execute(_batch_summary_query(batch_conditions))
    summary_row = summary_result.first()
    if not summary_row:
        raise ValueError("导入批次不存在")

    item_conditions = [QuestionImport.batch_id == batch_id]
    if status:
        item_conditions.append(QuestionImport.status == status)
    total = await db.scalar(select(func.count()).select_from(QuestionImport).where(*item_conditions))
    item_result = await db.execute(
        select(QuestionImport)
        .where(*item_conditions)
        .order_by(QuestionImport.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [AdminImportQuestionItem.model_validate(item) for item in item_result.scalars().all()]
    summary = _batch_row_to_dict(summary_row)
    return AdminImportBatchDetail(
        **summary,
        items=items,
        page=page,
        page_size=page_size,
        total_pages=max(ceil(int(total or 0) / page_size), 1) if total else 0,
    )


async def create_enrich_task(
    db: AsyncSession,
    batch_id: str,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> AdminImportEnrichResponse:
    summary_result = await db.execute(_batch_summary_query([QuestionImport.batch_id == batch_id]))
    summary_row = summary_result.first()
    if not summary_row:
        raise ValueError("导入批次不存在")

    task_id = f"admin-ai-{uuid4().hex}"
    now = datetime.utcnow()
    payload = {
        "task_id": task_id,
        "batch_id": batch_id,
        "status": "pending",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "total_count": int(summary_row.total_count or 0),
        "processed_count": 0,
        "error_message": None,
    }
    await cache.set(_task_key(task_id), payload, ttl=_TASK_TTL_SECONDS)
    await cache.set(_batch_task_key(batch_id), task_id, ttl=_TASK_TTL_SECONDS)
    await write_admin_audit(
        db,
        operator,
        "import.enrich",
        "import_batch",
        batch_id,
        severity="important",
        detail={"task_id": task_id, "batch_id": batch_id, "total_count": payload["total_count"]},
        request=request,
    )
    return AdminImportEnrichResponse(task_id=task_id, batch_id=batch_id, status="pending", created_at=now)


async def get_enrich_status(batch_id: str) -> dict:
    task_id = await cache.get(_batch_task_key(batch_id))
    if not task_id:
        raise ValueError("AI任务不存在")
    payload = await cache.get(_task_key(task_id))
    if not payload:
        raise ValueError("AI任务不存在")
    return payload


def _batch_conditions(status: str | None, source_type: str | None, keyword: str | None) -> list:
    conditions = []
    if status:
        conditions.append(QuestionImport.status == status)
    if source_type:
        conditions.append(QuestionImport.source_type == source_type)
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(or_(QuestionImport.batch_id.ilike(pattern), QuestionImport.source_file.ilike(pattern)))
    return conditions


def _batch_summary_query(conditions: list):
    return (
        select(
            QuestionImport.batch_id.label("batch_id"),
            func.min(QuestionImport.source_type).label("source_type"),
            func.min(QuestionImport.source_file).label("source_file"),
            func.count().label("total_count"),
            func.sum(case((QuestionImport.status == "pending", 1), else_=0)).label("pending_count"),
            func.sum(case((QuestionImport.status == "approved", 1), else_=0)).label("approved_count"),
            func.sum(case((QuestionImport.status == "rejected", 1), else_=0)).label("rejected_count"),
            func.sum(case((QuestionImport.status == "published", 1), else_=0)).label("published_count"),
            func.sum(case((QuestionImport.ai_generated.is_(True), 1), else_=0)).label("ai_count"),
            func.min(QuestionImport.created_at).label("created_at"),
            func.max(QuestionImport.updated_at).label("updated_at"),
        )
        .where(*conditions)
        .group_by(QuestionImport.batch_id)
    )


def _row_get(data, key: str):
    if isinstance(data, dict):
        return data[key]
    try:
        return data[key]
    except TypeError:
        return getattr(data, key)


def _batch_row_to_dict(row) -> dict:
    data = row._mapping if hasattr(row, "_mapping") else row
    return {
        "batch_id": _row_get(data, "batch_id"),
        "source_type": _row_get(data, "source_type"),
        "source_file": _row_get(data, "source_file"),
        "total_count": int(_row_get(data, "total_count") or 0),
        "pending_count": int(_row_get(data, "pending_count") or 0),
        "approved_count": int(_row_get(data, "approved_count") or 0),
        "rejected_count": int(_row_get(data, "rejected_count") or 0),
        "published_count": int(_row_get(data, "published_count") or 0),
        "ai_count": int(_row_get(data, "ai_count") or 0),
        "created_at": _row_get(data, "created_at"),
        "updated_at": _row_get(data, "updated_at"),
    }


def _task_key(task_id: str) -> str:
    return f"admin:ai:task:{task_id}"


def _batch_task_key(batch_id: str) -> str:
    return f"admin:ai:batch:{batch_id}:task"
