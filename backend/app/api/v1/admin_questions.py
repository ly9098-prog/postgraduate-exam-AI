from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.admin_questions import (
    AdminQuestionBatchRejectRequest,
    AdminQuestionBatchRequest,
    AdminQuestionBatchResult,
    AdminQuestionDetail,
    AdminQuestionListItem,
    AdminQuestionPatchRequest,
    AdminQuestionRejectRequest,
    AdminQuestionToggleActiveRequest,
    AdminQuestionVersionDetail,
    AdminQuestionVersionListItem,
)
from app.schemas.common import paginated_response
from app.services.admin_question_service import (
    approve_admin_question,
    batch_approve_admin_questions,
    batch_delete_admin_questions,
    batch_reject_admin_questions,
    get_admin_question_detail,
    get_question_version_detail,
    list_admin_questions,
    list_question_versions,
    reject_admin_question,
    soft_delete_admin_question,
    toggle_active_admin_question,
    update_admin_question,
)

router = APIRouter(prefix="/api/admin/v1/questions", tags=["admin-questions"])


def _raise_question_error(exc: ValueError) -> None:
    if str(exc) == "题目不存在":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("")
async def list_questions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    subject: str | None = None,
    review_status: str | None = None,
    is_active: bool | None = None,
    question_type: str | None = None,
    keyword: str | None = None,
    year: int | None = None,
    import_batch_id: str | None = None,
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    questions, total = await list_admin_questions(
        db,
        page,
        page_size,
        subject,
        review_status,
        is_active,
        question_type,
        keyword,
        year,
        import_batch_id,
    )
    return paginated_response([AdminQuestionListItem.model_validate(question) for question in questions], total, page, page_size)


@router.post("/batch-delete", response_model=AdminQuestionBatchResult)
async def batch_delete_questions(
    data: AdminQuestionBatchRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:delete")),
    db: AsyncSession = Depends(get_db),
):
    result = await batch_delete_admin_questions(db, data.ids, current_admin, request)
    await db.commit()
    return result


@router.post("/batch-approve", response_model=AdminQuestionBatchResult)
async def batch_approve_questions(
    data: AdminQuestionBatchRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:batch_review")),
    db: AsyncSession = Depends(get_db),
):
    result = await batch_approve_admin_questions(db, data, current_admin, request)
    await db.commit()
    return result


@router.post("/batch-reject", response_model=AdminQuestionBatchResult)
async def batch_reject_questions(
    data: AdminQuestionBatchRejectRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:batch_review")),
    db: AsyncSession = Depends(get_db),
):
    result = await batch_reject_admin_questions(db, data, current_admin, request)
    await db.commit()
    return result


@router.get("/{question_id}", response_model=AdminQuestionDetail)
async def get_question(
    question_id: int,
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_admin_question_detail(db, question_id)
    except ValueError as exc:
        _raise_question_error(exc)


@router.patch("/{question_id}", response_model=AdminQuestionListItem)
async def patch_question(
    question_id: int,
    data: AdminQuestionPatchRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        question = await update_admin_question(db, question_id, data, current_admin, request)
        await db.commit()
        await db.refresh(question)
        return question
    except ValueError as exc:
        await db.rollback()
        _raise_question_error(exc)
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.delete("/{question_id}")
async def delete_question(
    question_id: int,
    request: Request,
    current_admin=Depends(require_permissions("question:delete")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await soft_delete_admin_question(db, question_id, current_admin, request)
        await db.commit()
        return {"status": "ok"}
    except ValueError as exc:
        await db.rollback()
        _raise_question_error(exc)


@router.post("/{question_id}/approve", response_model=AdminQuestionListItem)
async def approve_question(
    question_id: int,
    request: Request,
    current_admin=Depends(require_permissions("question:review")),
    db: AsyncSession = Depends(get_db),
):
    try:
        question = await approve_admin_question(db, question_id, current_admin, request)
        await db.commit()
        await db.refresh(question)
        return question
    except ValueError as exc:
        await db.rollback()
        _raise_question_error(exc)


@router.post("/{question_id}/reject", response_model=AdminQuestionListItem)
async def reject_question(
    question_id: int,
    data: AdminQuestionRejectRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:review")),
    db: AsyncSession = Depends(get_db),
):
    try:
        question = await reject_admin_question(db, question_id, data, current_admin, request)
        await db.commit()
        await db.refresh(question)
        return question
    except ValueError as exc:
        await db.rollback()
        _raise_question_error(exc)


@router.patch("/{question_id}/toggle-active", response_model=AdminQuestionListItem)
async def toggle_active_question(
    question_id: int,
    data: AdminQuestionToggleActiveRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        question = await toggle_active_admin_question(db, question_id, data, current_admin, request)
        await db.commit()
        await db.refresh(question)
        return question
    except ValueError as exc:
        await db.rollback()
        _raise_question_error(exc)


@router.get("/{question_id}/versions")
async def list_versions(
    question_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        versions, total = await list_question_versions(db, question_id, page, page_size)
        return paginated_response([AdminQuestionVersionListItem.model_validate(item) for item in versions], total, page, page_size)
    except ValueError as exc:
        _raise_question_error(exc)


@router.get("/{question_id}/versions/{version}", response_model=AdminQuestionVersionDetail)
async def get_version(
    question_id: int,
    version: int,
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_question_version_detail(db, question_id, version)
    except ValueError as exc:
        _raise_question_error(exc)
