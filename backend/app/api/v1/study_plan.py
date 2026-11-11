"""408 long-horizon study plan and countdown API."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.study_plan import (
    StudyPlanConfigResponse,
    StudyPlanOverviewResponse,
    StudyPlanUpsertRequest,
)
from app.services import study_plan_service
from app.core.runtime_paths import API_V1_PREFIX
router = APIRouter(prefix=f"{API_V1_PREFIX}/study-plan", tags=["study-plan"])


@router.get("/overview", response_model=StudyPlanOverviewResponse)
async def get_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await study_plan_service.get_study_plan_overview(db, current_user.id)


@router.put("", response_model=StudyPlanConfigResponse)
async def upsert_plan(
    data: StudyPlanUpsertRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await study_plan_service.upsert_study_plan(db, current_user.id, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_plan(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await study_plan_service.deactivate_study_plan(db, current_user.id)
    return None
