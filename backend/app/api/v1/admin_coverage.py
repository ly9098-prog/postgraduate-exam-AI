"""Admin API for 408 question-bank coverage and content quality governance."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.coverage import CoverageReportResponse
from app.services import coverage_service

router = APIRouter(prefix="/api/admin/v1/coverage", tags=["admin-coverage"])


@router.get("/report", response_model=CoverageReportResponse)
async def get_coverage_report(
    syllabus_version_id: int | None = Query(None, ge=1),
    subject_id: int | None = Query(None, ge=1),
    min_questions: int = Query(10, ge=1, le=500),
    year_from: int | None = Query(None, ge=2000, le=2200),
    year_to: int | None = Query(None, ge=2000, le=2200),
    _=Depends(require_permissions("question:read", "knowledge:read")),
    db: AsyncSession = Depends(get_db),
):
    if year_from is not None and year_to is not None and year_from > year_to:
        raise HTTPException(status_code=422, detail="year_from 不能大于 year_to")
    try:
        return CoverageReportResponse(**await coverage_service.build_coverage_report(
            db,
            syllabus_version_id=syllabus_version_id,
            subject_id=subject_id,
            min_questions=min_questions,
            year_from=year_from,
            year_to=year_to,
        ))
    except coverage_service.CoverageError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=404 if "不存在" in message else 422,
            detail=message,
        ) from exc
