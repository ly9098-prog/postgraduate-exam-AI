import logging
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.core.admin_security import AdminPrincipal
from app.models.admin import Permission, QuestionVersion, RolePermission
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.features.question_pipeline import normalizer
from app.schemas.admin_questions import (
    AdminQuestionBatchFailure,
    AdminQuestionBatchRejectRequest,
    AdminQuestionBatchRequest,
    AdminQuestionBatchResult,
    AdminQuestionPatchRequest,
    AdminQuestionRejectRequest,
    AdminQuestionToggleActiveRequest,
)
from app.services.admin_audit_service import write_admin_audit


logger = logging.getLogger(__name__)


_EDIT_FIELDS = (
    "subject",
    "question_type",
    "content",
    "options",
    "answer",
    "analysis",
    "knowledge_points",
    "difficulty",
    "source",
    "source_type",
    "source_file",
    "import_batch_id",
    "raw_content",
    "image_url",
    "year",
)


async def list_admin_questions(
    db: AsyncSession,
    page: int,
    page_size: int,
    subject: str | None = None,
    review_status: str | None = None,
    is_active: bool | None = None,
    question_type: str | None = None,
    keyword: str | None = None,
    year: int | None = None,
    import_batch_id: str | None = None,
) -> tuple[list[Question], int]:
    conditions = []
    if subject:
        conditions.append(Question.subject == subject)
    if review_status:
        conditions.append(Question.review_status == review_status)
    if is_active is not None:
        conditions.append(Question.is_active.is_(is_active))
    if question_type:
        conditions.append(Question.question_type == question_type)
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(or_(Question.answer.ilike(pattern), Question.analysis.ilike(pattern), Question.raw_content.ilike(pattern)))
    if year is not None:
        conditions.append(Question.year == year)
    if import_batch_id:
        conditions.append(Question.import_batch_id == import_batch_id)

    query = select(Question)
    count_query = select(func.count()).select_from(Question)
    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = await db.scalar(count_query)
    result = await db.execute(
        query.order_by(Question.updated_at.desc(), Question.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_admin_question(db: AsyncSession, question_id: int) -> Question:
    question = await db.get(Question, question_id)
    if not question:
        raise ValueError("题目不存在")
    return question


async def get_admin_question_detail(db: AsyncSession, question_id: int) -> dict[str, Any]:
    question = await get_admin_question(db, question_id)
    result = await db.execute(select(QuestionImport).where(QuestionImport.question_id == question.id).order_by(QuestionImport.id.desc()))
    import_record = result.scalars().first()
    if import_record:
        import_record = {
            field: getattr(import_record, field)
            for field in import_record.__mapper__.columns.keys()
        }
        if not import_record.get("duplicate_status"):
            import_record["duplicate_status"] = "normal"
    data = {field: getattr(question, field) for field in question.__mapper__.columns.keys()}
    data["import_record"] = import_record
    return data


async def admin_has_permission(db: AsyncSession, operator: AdminPrincipal, permission_name: str) -> bool:
    result = await db.execute(
        select(Permission.name)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == operator.role_id, Permission.name == permission_name)
    )
    return result.scalar_one_or_none() == permission_name


async def _next_question_version(db: AsyncSession, question_id: int) -> int:
    version = await db.scalar(select(func.max(QuestionVersion.version)).where(QuestionVersion.question_id == question_id))
    return int(version or 0) + 1


def _question_snapshot(question: Question) -> dict[str, Any]:
    return {
        "content": question.content,
        "options": question.options,
        "answer": question.answer,
        "analysis": question.analysis,
        "difficulty": question.difficulty,
        "knowledge_points": question.knowledge_points,
    }


def _question_edit_state(question: Question) -> dict[str, Any]:
    return {field: getattr(question, field) for field in _EDIT_FIELDS} | {
        "review_status": question.review_status,
        "is_active": question.is_active,
    }


async def update_admin_question(
    db: AsyncSession,
    question_id: int,
    data: AdminQuestionPatchRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Question:
    question = await get_admin_question(db, question_id)
    update_data = data.model_dump(exclude_unset=True)
    edit_reason = update_data.pop("edit_reason", None)
    before = _question_edit_state(question)

    snapshot = _question_snapshot(question)
    db.add(
        QuestionVersion(
            question_id=question.id,
            version=await _next_question_version(db, question.id),
            edited_by=operator.id,
            edit_reason=edit_reason,
            **snapshot,
        )
    )

    for field in _EDIT_FIELDS:
        if field in update_data:
            setattr(question, field, update_data[field])

    if not await admin_has_permission(db, operator, "question:review"):
        question.review_status = "re_pending"
        question.is_active = False

    await db.flush()
    await write_admin_audit(
        db,
        operator,
        "question.update",
        "question",
        question.id,
        severity="important",
        detail={"before": before, "after": _question_edit_state(question)},
        request=request,
    )
    return question


async def soft_delete_admin_question(
    db: AsyncSession,
    question_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Question:
    question = await get_admin_question(db, question_id)
    before = {"is_active": question.is_active}
    question.is_active = False
    await write_admin_audit(
        db,
        operator,
        "question.delete",
        "question",
        question.id,
        severity="critical",
        detail={"before": before, "after": {"is_active": question.is_active}},
        request=request,
    )
    return question


async def batch_delete_admin_questions(
    db: AsyncSession,
    ids: list[int],
    operator: AdminPrincipal,
    request: Request | None = None,
) -> AdminQuestionBatchResult:
    success_ids: list[int] = []
    failed_items: list[AdminQuestionBatchFailure] = []
    for qid in ids:
        try:
            await soft_delete_admin_question(db, qid, operator, request)
            success_ids.append(qid)
        except ValueError as exc:
            failed_items.append(AdminQuestionBatchFailure(id=qid, error=str(exc)))
    return AdminQuestionBatchResult(success_ids=success_ids, failed_items=failed_items)


async def _sync_import_review(
    db: AsyncSession,
    question: Question,
    operator: AdminPrincipal,
    status: str,
    reject_reason: str | None = None,
) -> None:
    result = await db.execute(select(QuestionImport).where(QuestionImport.question_id == question.id))
    now = utcnow()
    for item in result.scalars().all():
        item.status = status
        item.reject_reason = reject_reason
        item.reviewed_by = operator.id
        item.reviewed_at = now


async def _find_duplicate_question_by_hash(db: AsyncSession, question: Question) -> Question | None:
    question_hash = question.question_hash or normalizer.build_question_hash(
        (question.content or {}).get("text", ""),
        question.options,
        question.answer,
    )
    if not question_hash:
        return None
    if question.question_hash != question_hash:
        question.question_hash = question_hash
    result = await db.execute(
        select(Question).where(
            Question.subject == question.subject,
            Question.question_hash == question_hash,
            Question.id != question.id,
            Question.is_active == True,
            Question.review_status == "approved",
        )
    )
    duplicate = result.scalars().first()
    logger.info(
        "[DuplicateCheck] questionId=%s importId=%s hash=%s result=%s matchedId=%s",
        question.id,
        None,
        question_hash,
        "matched_question" if duplicate else "normal",
        duplicate.id if duplicate else None,
    )
    return duplicate


async def _ensure_no_admin_duplicate(db: AsyncSession, question: Question) -> None:
    duplicate = await _find_duplicate_question_by_hash(db, question)
    if duplicate:
        raise ValueError(f"发现重复题目，重复题ID：{duplicate.id}")


async def approve_admin_question(
    db: AsyncSession,
    question_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Question:
    question = await get_admin_question(db, question_id)
    await _ensure_no_admin_duplicate(db, question)
    before = {"review_status": question.review_status, "is_active": question.is_active}
    question.review_status = "approved"
    question.is_active = True
    await _sync_import_review(db, question, operator, "approved")
    await write_admin_audit(
        db,
        operator,
        "question.approve",
        "question",
        question.id,
        severity="important",
        detail={"before": before, "after": {"review_status": question.review_status, "is_active": question.is_active}},
        request=request,
    )
    return question


async def reject_admin_question(
    db: AsyncSession,
    question_id: int,
    data: AdminQuestionRejectRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Question:
    question = await get_admin_question(db, question_id)
    before = {"review_status": question.review_status, "is_active": question.is_active}
    question.review_status = "rejected"
    question.is_active = False
    await _sync_import_review(db, question, operator, "rejected", data.reason)
    await write_admin_audit(
        db,
        operator,
        "question.reject",
        "question",
        question.id,
        severity="important",
        detail={"before": before, "after": {"review_status": question.review_status, "is_active": question.is_active, "reject_reason": data.reason}},
        request=request,
    )
    return question


async def toggle_active_admin_question(
    db: AsyncSession,
    question_id: int,
    data: AdminQuestionToggleActiveRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Question:
    question = await get_admin_question(db, question_id)
    if data.is_active and question.review_status != "approved":
        raise ValueError("非已审核题目不能激活")
    before = {"is_active": question.is_active}
    question.is_active = data.is_active
    await write_admin_audit(
        db,
        operator,
        "question.toggle_active",
        "question",
        question.id,
        severity="important",
        detail={"before": before, "after": {"is_active": question.is_active}},
        request=request,
    )
    return question


async def list_question_versions(db: AsyncSession, question_id: int, page: int, page_size: int) -> tuple[list[QuestionVersion], int]:
    await get_admin_question(db, question_id)
    count_query = select(func.count()).select_from(QuestionVersion).where(QuestionVersion.question_id == question_id)
    total = await db.scalar(count_query)
    result = await db.execute(
        select(QuestionVersion)
        .where(QuestionVersion.question_id == question_id)
        .order_by(QuestionVersion.version.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_question_version_detail(db: AsyncSession, question_id: int, version: int) -> QuestionVersion:
    await get_admin_question(db, question_id)
    result = await db.execute(select(QuestionVersion).where(QuestionVersion.question_id == question_id, QuestionVersion.version == version))
    question_version = result.scalar_one_or_none()
    if not question_version:
        raise ValueError("版本不存在")
    return question_version


async def batch_approve_admin_questions(
    db: AsyncSession,
    data: AdminQuestionBatchRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> AdminQuestionBatchResult:
    success_ids = []
    failed_items = []
    for question_id in data.ids:
        try:
            await approve_admin_question(db, question_id, operator, request)
            await db.commit()
            success_ids.append(question_id)
        except ValueError as exc:
            await db.rollback()
            failed_items.append({"id": question_id, "error": str(exc)})
    await write_admin_audit(
        db,
        operator,
        "question.batch_approve",
        "question",
        None,
        severity="critical",
        detail={"success_ids": success_ids, "failed_items": failed_items},
        request=request,
    )
    return AdminQuestionBatchResult(success_ids=success_ids, failed_items=failed_items)


async def batch_reject_admin_questions(
    db: AsyncSession,
    data: AdminQuestionBatchRejectRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> AdminQuestionBatchResult:
    success_ids = []
    failed_items = []
    reject_data = AdminQuestionRejectRequest(reason=data.reason)
    for question_id in data.ids:
        try:
            await reject_admin_question(db, question_id, reject_data, operator, request)
            await db.commit()
            success_ids.append(question_id)
        except ValueError as exc:
            await db.rollback()
            failed_items.append({"id": question_id, "error": str(exc)})
    await write_admin_audit(
        db,
        operator,
        "question.batch_reject",
        "question",
        None,
        severity="critical",
        detail={"success_ids": success_ids, "failed_items": failed_items, "reason": data.reason},
        request=request,
    )
    return AdminQuestionBatchResult(success_ids=success_ids, failed_items=failed_items)
