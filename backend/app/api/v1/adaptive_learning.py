"""V6 个性化调度 API 路由"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.adaptive_learning import (
    AdaptiveOverviewResponse,
    HardQuestionsResponse,
    KnowledgePathResponse,
)
from app.services import adaptive_learning_service as svc

router = APIRouter(prefix="/api/v1/adaptive-learning", tags=["adaptive-learning"])


@router.get("/overview", response_model=AdaptiveOverviewResponse)
async def adaptive_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_adaptive_overview(db, current_user.id)
    return AdaptiveOverviewResponse(**data)


@router.get("/hard-questions", response_model=HardQuestionsResponse)
async def hard_questions(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_hard_questions(db, current_user.id, limit=limit)
    return HardQuestionsResponse(**data)


@router.get("/knowledge-path", response_model=KnowledgePathResponse)
async def knowledge_path(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await svc.get_knowledge_path_adaptive(db, current_user.id, limit=limit)
    return KnowledgePathResponse(**data)
