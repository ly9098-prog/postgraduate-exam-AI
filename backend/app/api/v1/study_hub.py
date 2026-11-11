"""408 智能学习中心 API。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.runtime_paths import API_V1_PREFIX
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.knowledge_diagnosis import KnowledgeDiagnosisResponse
from app.schemas.study_hub import StudyHubOverviewResponse
from app.services import knowledge_diagnosis_service, study_hub_service

router = APIRouter(prefix=f"{API_V1_PREFIX}/study-hub", tags=["study-hub"])


@router.get("/overview", response_model=StudyHubOverviewResponse)
async def get_study_hub_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回 408 今日学习的统一决策视图。"""
    data = await study_hub_service.get_study_hub_overview(db, current_user.id)
    return StudyHubOverviewResponse(**data)


@router.get("/knowledge-diagnosis", response_model=KnowledgeDiagnosisResponse)
async def get_knowledge_diagnosis(
    subject_id: int = Query(..., ge=1, description="408 叶子科目 ID"),
    days: int = Query(30, ge=1, le=365, description="章节专项历史统计窗口"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回当前知识树诊断、章节专项历史与可直接执行的学习建议。"""
    data = await knowledge_diagnosis_service.get_knowledge_diagnosis(
        db, current_user.id, subject_id, days=days
    )
    if data is None:
        raise HTTPException(
            status_code=404, detail="408 科目不存在、已停用或当前大纲不可用"
        )
    return KnowledgeDiagnosisResponse(**data)
