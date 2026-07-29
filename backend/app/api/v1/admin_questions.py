from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.admin_questions import (
    AdminQuestionBatchRequest,
    AdminQuestionBatchResult,
    AdminQuestionDetail,
    AdminQuestionListItem,
    AdminQuestionPatchRequest,
    AdminQuestionToggleActiveRequest,
    AdminQuestionVersionDetail,
    AdminQuestionVersionListItem,
)
from app.schemas.common import paginated_response
from app.schemas.vector import EmbeddingBackfillRequest
from app.services.admin_question_service import (
    batch_delete_admin_questions,
    get_admin_question_detail,
    get_question_version_detail,
    list_admin_questions,
    list_question_versions,
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
    subject_id: int | None = None,
    review_status: str | None = None,
    is_active: bool | None = Query(True),
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
        subject_id,
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


@router.post("/embeddings/backfill")
async def backfill_embeddings(
    data: EmbeddingBackfillRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """批量回填题目 embedding 向量。

    支持游标分页：传入 after_id 从上次停止的位置继续。
    事务边界：API 层负责批次级提交，单条失败通过 savepoint 隔离。
    """
    from app.schemas.vector import EmbeddingBackfillResponse
    from app.services import vector_retrieval_service
    from app.services.admin_audit_service import write_admin_audit

    try:
        result = await vector_retrieval_service.backfill_question_embeddings(
            db=db,
            subject=data.subject,
            limit=data.limit,
            force=data.force,
            after_id=data.after_id,
        )
        await write_admin_audit(
            db,
            current_admin,
            "question.backfill_embeddings",
            "question",
            None,
            severity="normal",
            detail={
                "subject": data.subject,
                "limit": data.limit,
                "force": data.force,
                "after_id": data.after_id or 0,
                "processed": result.get("total", 0),
                "success_count": (
                    result.get("created", 0)
                    + result.get("updated", 0)
                    + result.get("skipped", 0)
                ),
                "failed_count": result.get("failed", 0),
            },
            request=request,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return EmbeddingBackfillResponse(**result)


@router.get("/embeddings/status")
async def embedding_status(
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    """查看向量功能状态和 embedding 统计。"""
    from app.schemas.vector import EmbeddingStatusResponse
    from app.services import vector_retrieval_service

    result = await vector_retrieval_service.get_embedding_status(db)
    return EmbeddingStatusResponse(**result)


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
