"""408 智能学习中心 API。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.study_hub import StudyHubOverviewResponse
from app.services import study_hub_service

router = APIRouter(prefix="/api/v1/study-hub", tags=["study-hub"])


@router.get("/overview", response_model=StudyHubOverviewResponse)
async def get_study_hub_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回 408 今日学习的统一决策视图。"""
    data = await study_hub_service.get_study_hub_overview(db, current_user.id)
    return StudyHubOverviewResponse(**data)
