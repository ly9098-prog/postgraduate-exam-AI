"""用户知识点掌握度 + 推荐反馈 API。"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.knowledge_mastery import (
    KnowledgeStateItem,
    RecommendationFeedbackRequest,
    RecommendationFeedbackResponse,
    WeakKnowledgePointItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge-mastery"])


@router.get("/states", response_model=list[KnowledgeStateItem])
async def get_knowledge_states(
    subject: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回当前用户某科目下的知识点掌握状态。"""
    from app.services import mastery_service

    states = await mastery_service.get_user_knowledge_states(
        db, current_user.id, subject,
    )
    return [KnowledgeStateItem(**s) for s in states]


@router.get("/weak-points", response_model=list[WeakKnowledgePointItem])
async def get_weak_knowledge_points(
    subject: str = Query(...),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回当前用户薄弱知识点。"""
    from app.services import mastery_service

    weak = await mastery_service.get_user_weak_knowledge_points(
        db, current_user.id, subject, limit=limit,
    )
    return [WeakKnowledgePointItem(**w) for w in weak]


@router.post("/feedback", response_model=RecommendationFeedbackResponse)
async def post_recommendation_feedback(
    data: RecommendationFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """小程序端回传推荐曝光/点击/作答事件。"""
    from app.services import recommendation_log_service

    matched = False
    if data.event == "clicked":
        matched = await recommendation_log_service.mark_recommendation_clicked(
            db, current_user.id, data.question_id, data.request_id,
        )
    elif data.event == "answered":
        matched = await recommendation_log_service.mark_recommendation_answered(
            db, current_user.id, data.question_id,
            is_correct=data.is_correct or False,
            request_id=data.request_id,
        )
    elif data.event == "shown":
        # shown 事件在推荐日志创建时已记录，此处仅做确认
        matched = True

    return RecommendationFeedbackResponse(status="ok", matched=matched)
