from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.review import (
    ReviewDueItem,
    ReviewStatsResponse,
    ReviewSubmitRequest,
    ReviewSubmitResponse,
    ReviewSubmitResult,
)
from app.services import review_service as svc

router = APIRouter(prefix="/api/v1/review")


@router.get("/due")
async def list_due_reviews(
    subject: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = await svc.get_due_reviews(
        db, current_user.id, subject, page, page_size
    )
    return {
        "items": [ReviewDueItem(**item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.post("/submit", response_model=ReviewSubmitResponse)
async def submit_review(
    data: ReviewSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = [d.model_dump() for d in data.items]
    results = await svc.submit_batch_review(db, current_user.id, items)

    processed = len(results)
    if processed == 0:
        raise HTTPException(status_code=404, detail="没有找到有效的错题记录")

    return ReviewSubmitResponse(
        results=[ReviewSubmitResult(**r) for r in results],
        processed=processed,
    )


@router.get("/stats", response_model=ReviewStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stats = await svc.get_review_stats(db, current_user.id)
    return ReviewStatsResponse(**stats)
