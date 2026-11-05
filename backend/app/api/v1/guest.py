"""Guest practice endpoints: browse and try questions without an account."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.guest import (
    GuestEvaluateRequest,
    GuestEvaluateResponse,
    GuestPracticeQuestionsResponse,
)
from app.services.guest_evaluation import evaluate_guest_answers
from app.services.guest_practice import (
    GuestPracticeError,
    GuestSubjectUnavailableError,
    decode_guest_batch_token,
    load_guest_questions,
    load_guest_subject_tree,
)
from app.services.guest_rate_limit import require_guest_request_budget

router = APIRouter(
    prefix="/api/v1/guest/practice", tags=["guest-practice"],
    dependencies=[Depends(require_guest_request_budget)],
)


@router.get("/subjects")
async def list_guest_subjects(db: AsyncSession = Depends(get_db)):
    """Return the practice subject tree restricted to subjects with guest questions."""
    return {"items": await load_guest_subject_tree(db)}


@router.get("/questions", response_model=GuestPracticeQuestionsResponse)
async def get_guest_questions(
    subject_id: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await load_guest_questions(db, subject_id)
    except GuestSubjectUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/evaluate", response_model=GuestEvaluateResponse)
async def evaluate_guest_practice(
    data: GuestEvaluateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Grade guest answers against the immutable revisions in the signed batch."""
    try:
        batch = decode_guest_batch_token(data.batch_token)
        return await evaluate_guest_answers(db, batch=batch, answers=data.answers)
    except GuestPracticeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
