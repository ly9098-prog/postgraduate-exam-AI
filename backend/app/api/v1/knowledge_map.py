"""Student-facing 408 knowledge mastery map API."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.knowledge_map import (
    KnowledgeMapOverviewResponse,
    KnowledgeMapPointDetailResponse,
    KnowledgeMapSubjectResponse,
)
from app.services import knowledge_map_service
from app.core.runtime_paths import API_V1_PREFIX
router = APIRouter(prefix=f"{API_V1_PREFIX}/knowledge-map", tags=["knowledge-map"])


@router.get("/overview", response_model=KnowledgeMapOverviewResponse)
async def get_knowledge_map_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return KnowledgeMapOverviewResponse(
        **await knowledge_map_service.get_overview(db, current_user.id)
    )


@router.get("/subjects/{subject_id}", response_model=KnowledgeMapSubjectResponse)
async def get_subject_knowledge_map(
    subject_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await knowledge_map_service.get_subject_map(db, current_user.id, subject_id)
    if data is None:
        raise HTTPException(
            status_code=404, detail="408 科目不存在、已停用或不在当前产品范围"
        )
    return KnowledgeMapSubjectResponse(**data)


@router.get(
    "/points/{knowledge_point_id}", response_model=KnowledgeMapPointDetailResponse
)
async def get_knowledge_point_detail(
    knowledge_point_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = await knowledge_map_service.get_point_detail(
        db, current_user.id, knowledge_point_id
    )
    if data is None:
        raise HTTPException(
            status_code=404, detail="知识点不存在、已停用或不属于当前 408 范围"
        )
    return KnowledgeMapPointDetailResponse(**data)
