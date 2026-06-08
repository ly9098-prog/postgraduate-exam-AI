from datetime import datetime
from math import ceil
from uuid import uuid4

from fastapi import Request
from sqlalchemy import case, delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.cache import cache
from app.features import question_pipeline
from app.models.question_import import QuestionImport
from app.schemas.admin_imports import (
    AdminImportBatchDetail,
    AdminImportEnrichResponse,
    AdminImportQuestionItem,
    AdminImportQuestionUpdateRequest,
)
from app.services.admin_ai_settings_service import ensure_ai_parse_allowed
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


async def list_review_queue(
    db: AsyncSession,
    page: int,
    page_size: int,
    status: str | None = "pending",
    batch_id: str | None = None,
    subject: str | None = None,
    source_type: str | None = None,
    keyword: str | None = None,
) -> tuple[list[AdminImportQuestionItem], int]:
    conditions = _question_conditions(status, batch_id, subject, source_type, keyword)
    total = await db.scalar(select(func.count()).select_from(QuestionImport).where(*conditions))
    result = await db.execute(
        select(QuestionImport)
        .where(*conditions)
        .order_by(QuestionImport.created_at.desc(), QuestionImport.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [AdminImportQuestionItem.model_validate(item) for item in result.scalars().all()], int(total or 0)


async def update_import_question(
    db: AsyncSession,
    import_id: int,
    data: AdminImportQuestionUpdateRequest,
) -> AdminImportQuestionItem:
    qi = await _get_import_question(db, import_id)
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可编辑")

    payload = data.model_dump(exclude_none=True)
    if "stem" in payload:
        content = dict(qi.parsed_content or {})
        content["text"] = payload.pop("stem")
        qi.parsed_content = content
    if "options" in payload:
        options = payload.pop("options")
        qi.parsed_options = {str(item.get("key") or item.get("label")): item.get("text") or item.get("value") for item in options if isinstance(item, dict)} if isinstance(options, list) else options
    if "answer" in payload:
        qi.parsed_answer = payload.pop("answer")
    if "analysis" in payload:
        qi.parsed_analysis = payload.pop("analysis")

    for field in (
        "subject",
        "question_type",
        "raw_data",
        "parsed_content",
        "parsed_options",
        "parsed_answer",
        "parsed_analysis",
        "review_note",
    ):
        if field in payload:
            setattr(qi, field, payload[field])
    await db.flush()
    await db.refresh(qi)
    return AdminImportQuestionItem.model_validate(qi)


async def approve_import_question(db: AsyncSession, import_id: int, operator_id: int) -> AdminImportQuestionItem:
    qi = await _get_import_question(db, import_id)
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可重复审核")
    qi.status = "approved"
    qi.reject_reason = None
    qi.reviewed_by = operator_id
    qi.reviewed_at = datetime.utcnow()
    await db.flush()
    await db.refresh(qi)
    return AdminImportQuestionItem.model_validate(qi)


async def reject_import_question(db: AsyncSession, import_id: int, operator_id: int, reason: str | None = None) -> AdminImportQuestionItem:
    qi = await _get_import_question(db, import_id)
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可驳回")
    qi.status = "rejected"
    qi.reject_reason = reason
    qi.review_note = reason or qi.review_note
    qi.reviewed_by = operator_id
    qi.reviewed_at = datetime.utcnow()
    await db.flush()
    await db.refresh(qi)
    return AdminImportQuestionItem.model_validate(qi)


async def approve_import_batch(db: AsyncSession, batch_id: str, operator_id: int) -> int:
    records = await _get_batch_records(db, batch_id, statuses={"pending", "rejected"})
    now = datetime.utcnow()
    for qi in records:
        if qi.question_id is None:
            qi.status = "approved"
            qi.reject_reason = None
            qi.reviewed_by = operator_id
            qi.reviewed_at = now
    await db.flush()
    return len(records)


async def reject_import_batch(db: AsyncSession, batch_id: str, operator_id: int, reason: str | None = None) -> int:
    records = await _get_batch_records(db, batch_id, statuses={"pending", "approved"})
    now = datetime.utcnow()
    for qi in records:
        if qi.question_id is None:
            qi.status = "rejected"
            qi.reject_reason = reason
            qi.review_note = reason or qi.review_note
            qi.reviewed_by = operator_id
            qi.reviewed_at = now
    await db.flush()
    return len(records)


async def delete_import_question(db: AsyncSession, import_id: int) -> int:
    qi = await _get_import_question(db, import_id)
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可删除")
    await db.delete(qi)
    await db.flush()
    return 1


async def delete_import_batch(db: AsyncSession, batch_id: str) -> int:
    records = await _get_batch_records(db, batch_id)
    if any(qi.status == "published" or qi.question_id is not None for qi in records):
        raise ValueError("已发布批次不可删除")
    result = await db.execute(delete(QuestionImport).where(QuestionImport.batch_id == batch_id))
    await db.flush()
    return int(result.rowcount or 0)


async def complete_import_question(
    db: AsyncSession,
    import_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> dict:
    qi = await _get_import_question(db, import_id)
    if qi.status != "pending":
        raise ValueError("仅支持对 pending 记录使用 AI 补全")
    await ensure_ai_parse_allowed(db, operator, request)

    result = await question_pipeline.complete_import(db, operator.id, import_id)
    refreshed = await _get_import_question(db, import_id)
    await write_admin_audit(
        db,
        operator,
        "import.complete",
        "question_import",
        str(import_id),
        severity="important",
        detail={
            "import_id": import_id,
            "batch_id": refreshed.batch_id,
            "missing": result.get("missing", []),
            "from_fallback": result.get("from_fallback", False),
        },
        request=request,
    )
    return {
        "missing": result.get("missing", []),
        "from_fallback": result.get("from_fallback", False),
        "ai_metadata": result.get("ai_metadata", {}),
        "tokens_used": result.get("tokens_used", 0),
        "duration_ms": result.get("duration_ms", 0),
        "item": AdminImportQuestionItem.model_validate(refreshed),
    }


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
    await ensure_ai_parse_allowed(db, operator, request)

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


def _question_conditions(
    status: str | None,
    batch_id: str | None,
    subject: str | None,
    source_type: str | None,
    keyword: str | None,
) -> list:
    conditions = []
    if status:
        conditions.append(QuestionImport.status == status)
    if batch_id:
        conditions.append(QuestionImport.batch_id == batch_id)
    if subject:
        conditions.append(QuestionImport.subject == subject)
    if source_type:
        conditions.append(QuestionImport.source_type == source_type)
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            or_(
                QuestionImport.batch_id.ilike(pattern),
                QuestionImport.source_file.ilike(pattern),
                QuestionImport.parsed_answer.ilike(pattern),
                QuestionImport.parsed_analysis.ilike(pattern),
            )
        )
    return conditions


async def _get_import_question(db: AsyncSession, import_id: int) -> QuestionImport:
    result = await db.execute(select(QuestionImport).where(QuestionImport.id == import_id))
    qi = result.scalar_one_or_none()
    if qi is None:
        raise ValueError("导入题目不存在")
    return qi


async def _get_batch_records(
    db: AsyncSession,
    batch_id: str,
    statuses: set[str] | None = None,
) -> list[QuestionImport]:
    conditions = [QuestionImport.batch_id == batch_id]
    if statuses:
        conditions.append(QuestionImport.status.in_(statuses))
    result = await db.execute(select(QuestionImport).where(*conditions).order_by(QuestionImport.id.asc()))
    records = list(result.scalars().all())
    if not records:
        raise ValueError("导入批次不存在")
    return records
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
