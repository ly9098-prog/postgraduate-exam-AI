import logging
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.models.admin import QuestionVersion, Subject
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.schemas.admin_questions import (
    AdminQuestionBatchFailure,
    AdminQuestionBatchResult,
    AdminQuestionPatchRequest,
    AdminQuestionToggleActiveRequest,
)
from app.services.admin_audit_service import write_admin_audit

logger = logging.getLogger(__name__)


_EDIT_FIELDS = (
    "subject_id",
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

_CONTENT_PREVIEW_MAX_LENGTH = 200


def build_question_audit_snapshot(question: Question) -> dict[str, Any]:
    """Build a complete snapshot of a question for audit logging."""
    # Attempt to resolve subject info
    subject_name = None
    subject_code = None
    if hasattr(question, "subject_ref") and question.subject_ref is not None:
        subject_name = question.subject_ref.name
        subject_code = question.subject_ref.code

    return {
        "id": question.id,
        "subject_id": question.subject_id,
        "subject_code": subject_code,
        "subject_name": subject_name,
        "question_type": question.question_type,
        "content": question.content,
        "options": question.options,
        "answer": question.answer,
        "analysis": question.analysis,
        "knowledge_points": question.knowledge_points,
        "difficulty": question.difficulty,
        "source": question.source,
        "source_type": question.source_type,
        "source_file": question.source_file,
        "import_batch_id": question.import_batch_id,
        "year": question.year,
        "review_status": question.review_status,
        "is_active": question.is_active,
    }


def _content_preview(content: dict | str | None) -> str | None:
    """Extract a short text preview from question content."""
    if content is None:
        return None
    if isinstance(content, str):
        text = content
    elif isinstance(content, dict):
        # Common patterns: {"text": "..."} or {"en": "...", "cn": "..."}
        text = content.get("text")
        if text is None:
            text = content.get("cn")
        if text is None:
            text = content.get("en")
        if text is None:
            text = str(content)
    else:
        text = str(content)
    return text[:_CONTENT_PREVIEW_MAX_LENGTH]


def _question_summary(question: Question) -> dict[str, Any]:
    """Build a light-weight question summary for audit display (no full content)."""
    subject_name = None
    if hasattr(question, "subject_ref") and question.subject_ref is not None:
        subject_name = question.subject_ref.name

    content = getattr(question, "content", None)
    content_preview = _content_preview(content)

    return {
        "id": question.id,
        "content_preview": content_preview,
        "subject_name": subject_name,
        "question_type": question.question_type,
    }


async def _resolve_question_subject(db: AsyncSession, question: Question) -> None:
    """Ensure subject_ref is loaded for a question."""
    if question.subject_ref is None and question.subject_id:
        result = await db.execute(select(Subject).where(Subject.id == question.subject_id))
        question.subject_ref = result.scalar_one_or_none()


async def list_admin_questions(
    db: AsyncSession,
    page: int,
    page_size: int,
    subject_id: int | None = None,
    review_status: str | None = None,
    is_active: bool | None = None,
    question_type: str | None = None,
    keyword: str | None = None,
    year: int | None = None,
    import_batch_id: str | None = None,
) -> tuple[list[Question], int]:
    conditions = []
    if subject_id is not None:
        conditions.append(Question.subject_id == subject_id)
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
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        query.options(selectinload(Question.subject_ref))
        .order_by(Question.updated_at.desc(), Question.id.desc())
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
    await _resolve_question_subject(db, question)

    update_data = data.model_dump(exclude_unset=True)
    edit_reason = update_data.pop("edit_reason", None)

    # Compute which fields actually changed (compare old vs new values)
    before_full = _question_edit_state(question)
    changed_fields = []
    for f in _EDIT_FIELDS:
        if f in update_data:
            old_val = getattr(question, f)
            new_val = update_data[f]
            if old_val != new_val:
                changed_fields.append(f)

    # No actual changes — skip version creation and audit
    if not changed_fields:
        return question

    # Create version snapshot (only when real changes exist)
    before_changed = {f: before_full[f] for f in changed_fields}
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

    # Apply changes
    for field in changed_fields:
        setattr(question, field, update_data[field])

    await db.flush()
    await _resolve_question_subject(db, question)

    after_changed = {f: getattr(question, f) for f in changed_fields}

    await write_admin_audit(
        db,
        operator,
        "question.update",
        "question",
        question.id,
        severity="important",
        detail={
            "question": _question_summary(question),
            "changed_fields": changed_fields,
            "before": before_changed,
            "after": after_changed,
            "edit_reason": edit_reason,
        },
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
    await _resolve_question_subject(db, question)

    # Take full snapshot before deletion
    full_snapshot = build_question_audit_snapshot(question)

    before = {"is_active": question.is_active}
    question.is_active = False

    await write_admin_audit(
        db,
        operator,
        "question.delete",
        "question",
        question.id,
        severity="critical",
        detail={
            "question": full_snapshot,
            "before": before,
            "after": {"is_active": question.is_active},
            "delete_mode": "soft",
            "question_summary": _question_summary(question),
        },
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
    questions_summary: list[dict] = []

    for qid in ids:
        try:
            question = await soft_delete_admin_question(db, qid, operator, request)
            success_ids.append(qid)
            questions_summary.append(_question_summary(question))
        except ValueError as exc:
            failed_items.append(AdminQuestionBatchFailure(id=qid, error=str(exc)))

    # Also write a batch summary log
    await write_admin_audit(
        db,
        operator,
        "question.batch_delete",
        "question_batch",
        None,
        severity="critical",
        detail={
            "requested_ids": ids,
            "success_ids": success_ids,
            "failed_items": [
                {"id": f.id, "error": f.error} for f in failed_items
            ],
            "success_count": len(success_ids),
            "failed_count": len(failed_items),
            "questions": questions_summary,
        },
        request=request,
    )

    return AdminQuestionBatchResult(success_ids=success_ids, failed_items=failed_items)


async def toggle_active_admin_question(
    db: AsyncSession,
    question_id: int,
    data: AdminQuestionToggleActiveRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Question:
    question = await get_admin_question(db, question_id)
    await _resolve_question_subject(db, question)

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
        detail={
            "question": _question_summary(question),
            "before": before,
            "after": {"is_active": question.is_active},
        },
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
