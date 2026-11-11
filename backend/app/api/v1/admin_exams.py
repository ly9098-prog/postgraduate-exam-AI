from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions, require_roles
from app.core.database import get_db
from app.schemas.admin_exam import (
    AdminExamPaperCreateRequest,
    AdminExamPaperDetail,
    AdminExamPaperItemsReplaceRequest,
    AdminExamPaperListItem,
    AdminExamPaperUpdateRequest,
    AdminExamPastExamCandidatesResponse,
)
from app.services import admin_exam_service
from app.core.runtime_paths import API_ADMIN_V1_PREFIX
router = APIRouter(prefix=f"{API_ADMIN_V1_PREFIX}/exams", tags=["admin-exams"])


def _raise_exam_error(exc: ValueError) -> None:
    if isinstance(exc, admin_exam_service.ExamPaperNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, admin_exam_service.ExamPaperStateError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


def _exam_action_error_response(exc: ValueError, *, action: str) -> JSONResponse:
    """Return administrator-safe details for paper state transitions.

    ``HTTPException`` details are sanitized globally, which is appropriate for
    arbitrary endpoints but too vague for controlled exam workflow errors.
    The messages emitted by ``admin_exam_service`` are curated admin-facing
    validation/state diagnostics, so state-action endpoints can opt in to
    returning them directly.
    """
    if isinstance(exc, admin_exam_service.ExamPaperNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
        code = "EXAM_PAPER_NOT_FOUND"
    elif isinstance(exc, admin_exam_service.ExamPaperStateError):
        status_code = status.HTTP_409_CONFLICT
        code = "EXAM_PAPER_STATE_ERROR"
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        code = "EXAM_PAPER_ACTION_INVALID"

    fallback = f"{action}失败，请检查试卷状态后重试"
    message = (str(exc) or fallback).strip()[:4000]
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": message,
            "error": {
                "code": code,
                "message": message,
                "retryable": False,
            },
        },
    )


def _exam_items_error_response(exc: ValueError) -> JSONResponse:
    """Return safe, actionable diagnostics for the admin paper-items editor.

    The global exception handler intentionally sanitizes arbitrary 4xx details.
    This endpoint only emits paper/question validation messages created by the
    exam service, so administrators can see the offending question IDs instead
    of the generic ``HTTP_422`` text.
    """
    if isinstance(exc, admin_exam_service.ExamPaperNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
        code = "EXAM_PAPER_NOT_FOUND"
    elif isinstance(exc, admin_exam_service.ExamPaperStateError):
        status_code = status.HTTP_409_CONFLICT
        code = "EXAM_PAPER_STATE_ERROR"
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        code = "EXAM_PAPER_ITEMS_INVALID"
    message = (str(exc) or "试卷题目校验未通过").strip()[:4000]
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": message,
            "error": {
                "code": code,
                "message": message,
                "retryable": False,
            },
        },
    )


@router.get("/papers", response_model=list[AdminExamPaperListItem])
async def list_papers(
    paper_status: str | None = Query(None, alias="status"),
    paper_type: str | None = None,
    year: int | None = Query(None, ge=2000, le=2100),
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    return await admin_exam_service.list_exam_papers(
        db,
        status=paper_status,
        paper_type=paper_type,
        year=year,
    )


@router.post("/papers", response_model=AdminExamPaperDetail)
async def create_paper(
    data: AdminExamPaperCreateRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper = await admin_exam_service.create_exam_paper(
            db, data, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, int(paper.id))
    except ValueError as exc:
        await db.rollback()
        _raise_exam_error(exc)


@router.get("/papers/{paper_id}", response_model=AdminExamPaperDetail)
async def get_paper(
    paper_id: int,
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        _raise_exam_error(exc)


@router.get(
    "/papers/public/{public_id}",
    response_model=AdminExamPaperDetail,
)
async def get_paper_by_public_id(
    public_id: str,
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper_id = await admin_exam_service.get_exam_paper_id_by_public_id(db, public_id)
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        _raise_exam_error(exc)


@router.get(
    "/past-exam-candidates",
    response_model=AdminExamPastExamCandidatesResponse,
)
async def get_past_exam_candidates(
    year: int = Query(..., ge=2000, le=2100),
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    return await admin_exam_service.list_past_exam_candidates(db, year)


@router.patch("/papers/{paper_id}", response_model=AdminExamPaperDetail)
async def update_paper(
    paper_id: int,
    data: AdminExamPaperUpdateRequest,
    request: Request,
    current_admin=Depends(require_roles("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await admin_exam_service.update_exam_paper(
            db, paper_id, data, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        _raise_exam_error(exc)


@router.patch(
    "/papers/public/{public_id}",
    response_model=AdminExamPaperDetail,
)
async def update_paper_by_public_id(
    public_id: str,
    data: AdminExamPaperUpdateRequest,
    request: Request,
    current_admin=Depends(require_roles("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper_id = await admin_exam_service.get_exam_paper_id_by_public_id(db, public_id)
        await admin_exam_service.update_exam_paper(
            db, paper_id, data, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        _raise_exam_error(exc)


@router.delete("/papers/{paper_id}")
async def delete_paper(
    paper_id: int,
    request: Request,
    current_admin=Depends(require_roles("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper = await admin_exam_service.soft_delete_exam_paper(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return {"status": "ok", "public_id": paper.public_id}
    except ValueError as exc:
        await db.rollback()
        _raise_exam_error(exc)


@router.delete("/papers/public/{public_id}")
async def delete_paper_by_public_id(
    public_id: str,
    request: Request,
    current_admin=Depends(require_roles("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper_id = await admin_exam_service.get_exam_paper_id_by_public_id(db, public_id)
        paper = await admin_exam_service.soft_delete_exam_paper(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return {"status": "ok", "public_id": paper.public_id}
    except ValueError as exc:
        await db.rollback()
        _raise_exam_error(exc)


@router.put("/papers/{paper_id}/items", response_model=AdminExamPaperDetail)
async def replace_items(
    paper_id: int,
    data: AdminExamPaperItemsReplaceRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await admin_exam_service.replace_exam_paper_items(
            db, paper_id, data, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_items_error_response(exc)


@router.put(
    "/papers/public/{public_id}/items",
    response_model=AdminExamPaperDetail,
)
async def replace_items_by_public_id(
    public_id: str,
    data: AdminExamPaperItemsReplaceRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper_id = await admin_exam_service.get_exam_paper_id_by_public_id(db, public_id)
        await admin_exam_service.replace_exam_paper_items(
            db, paper_id, data, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_items_error_response(exc)


@router.post(
    "/papers/{paper_id}/items/quick-fill-past-exam",
    response_model=AdminExamPaperDetail,
)
async def quick_fill_past_exam_items(
    paper_id: int,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await admin_exam_service.quick_fill_past_exam_paper_items(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_items_error_response(exc)


@router.post(
    "/papers/public/{public_id}/items/quick-fill-past-exam",
    response_model=AdminExamPaperDetail,
)
async def quick_fill_past_exam_items_by_public_id(
    public_id: str,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper_id = await admin_exam_service.get_exam_paper_id_by_public_id(db, public_id)
        await admin_exam_service.quick_fill_past_exam_paper_items(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_items_error_response(exc)


@router.post(
    "/papers/{paper_id}/items/refresh-past-exam",
    response_model=AdminExamPaperDetail,
)
async def refresh_past_exam_items(
    paper_id: int,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await admin_exam_service.refresh_past_exam_paper_items(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_items_error_response(exc)


@router.post(
    "/papers/public/{public_id}/items/refresh-past-exam",
    response_model=AdminExamPaperDetail,
)
async def refresh_past_exam_items_by_public_id(
    public_id: str,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper_id = await admin_exam_service.get_exam_paper_id_by_public_id(db, public_id)
        await admin_exam_service.refresh_past_exam_paper_items(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_items_error_response(exc)


@router.delete("/papers/{paper_id}/items", response_model=AdminExamPaperDetail)
async def clear_items(
    paper_id: int,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await admin_exam_service.clear_exam_paper_items(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_items_error_response(exc)


@router.delete(
    "/papers/public/{public_id}/items",
    response_model=AdminExamPaperDetail,
)
async def clear_items_by_public_id(
    public_id: str,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper_id = await admin_exam_service.get_exam_paper_id_by_public_id(db, public_id)
        await admin_exam_service.clear_exam_paper_items(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_items_error_response(exc)


@router.post("/papers/{paper_id}/publish", response_model=AdminExamPaperDetail)
async def publish_paper(
    paper_id: int,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await admin_exam_service.publish_exam_paper(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_action_error_response(exc, action="发布试卷")


@router.post(
    "/papers/public/{public_id}/publish",
    response_model=AdminExamPaperDetail,
)
async def publish_paper_by_public_id(
    public_id: str,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper_id = await admin_exam_service.get_exam_paper_id_by_public_id(db, public_id)
        await admin_exam_service.publish_exam_paper(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_action_error_response(exc, action="发布试卷")


@router.post("/papers/{paper_id}/restore", response_model=AdminExamPaperDetail)
async def restore_paper(
    paper_id: int,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await admin_exam_service.restore_and_publish_exam_paper(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_action_error_response(exc, action="还原发布")


@router.post(
    "/papers/public/{public_id}/restore",
    response_model=AdminExamPaperDetail,
)
async def restore_paper_by_public_id(
    public_id: str,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper_id = await admin_exam_service.get_exam_paper_id_by_public_id(db, public_id)
        await admin_exam_service.restore_and_publish_exam_paper(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_action_error_response(exc, action="还原发布")


@router.post("/papers/{paper_id}/archive", response_model=AdminExamPaperDetail)
async def archive_paper(
    paper_id: int,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await admin_exam_service.archive_exam_paper(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_action_error_response(exc, action="归档试卷")


@router.post(
    "/papers/public/{public_id}/archive",
    response_model=AdminExamPaperDetail,
)
async def archive_paper_by_public_id(
    public_id: str,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper_id = await admin_exam_service.get_exam_paper_id_by_public_id(db, public_id)
        await admin_exam_service.archive_exam_paper(
            db, paper_id, current_admin, request
        )
        await db.commit()
        return await admin_exam_service.get_exam_paper_detail(db, paper_id)
    except ValueError as exc:
        await db.rollback()
        return _exam_action_error_response(exc, action="归档试卷")
