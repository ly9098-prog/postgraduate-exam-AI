from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.exam import (
    ExamAnswerSaveRequest,
    ExamAnswerSaveResponse,
    ExamAttemptStartRequest,
    ExamAttemptView,
    ExamHistoryItem,
    ExamPaperDetail,
    ExamPaperSummary,
    ExamResult,
)
from app.services import exam_service

router = APIRouter(prefix="/api/v1/exams", tags=["exams"])


def _raise_exam_error(exc: ValueError) -> None:
    if isinstance(exc, exam_service.ExamNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, exam_service.ExamStateError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/papers", response_model=list[ExamPaperSummary])
async def list_papers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await exam_service.list_published_papers(db, current_user.id)


@router.get("/papers/{paper_id}", response_model=ExamPaperDetail)
async def get_paper(
    paper_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await exam_service.get_published_paper_detail(db, paper_id, current_user.id)
    except ValueError as exc:
        _raise_exam_error(exc)


@router.post("/papers/{paper_id}/attempts", response_model=ExamAttemptView)
async def start_attempt(
    paper_id: int,
    data: ExamAttemptStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await exam_service.start_attempt(db, paper_id, current_user.id, data.request_id)
    except ValueError as exc:
        _raise_exam_error(exc)


@router.get("/attempts/{attempt_id}", response_model=ExamAttemptView)
async def get_attempt(
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await exam_service.get_attempt_view(db, attempt_id, current_user.id)
    except ValueError as exc:
        _raise_exam_error(exc)


@router.patch(
    "/attempts/{attempt_id}/answers/{item_id}",
    response_model=ExamAnswerSaveResponse,
)
async def save_answer(
    attempt_id: int,
    item_id: int,
    data: ExamAnswerSaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kwargs = {
        "marked_for_review": data.marked_for_review,
        "used_time": data.used_time,
    }
    if "selected_answer" in data.model_fields_set:
        kwargs["selected_answer"] = data.selected_answer
    try:
        return await exam_service.save_attempt_answer(
            db,
            attempt_id,
            item_id,
            current_user.id,
            **kwargs,
        )
    except ValueError as exc:
        _raise_exam_error(exc)


@router.post("/attempts/{attempt_id}/submit", response_model=ExamResult)
async def submit_attempt(
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await exam_service.submit_attempt(db, attempt_id, current_user.id)
    except ValueError as exc:
        _raise_exam_error(exc)


@router.get("/attempts/{attempt_id}/result", response_model=ExamResult)
async def get_result(
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await exam_service.get_attempt_result(db, attempt_id, current_user.id)
    except ValueError as exc:
        _raise_exam_error(exc)


@router.get("/history", response_model=list[ExamHistoryItem])
async def history(
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await exam_service.list_exam_history(db, current_user.id, limit=limit)
