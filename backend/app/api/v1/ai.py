from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.ai import AiChatRecord, AiResponse, ErrorAnalysisRequest, StudyAdviceRequest
from app.schemas.ai_learning import (
    AIExplainRequest,
    AIExplainResponse,
    AIMistakeAnalysisRequest,
    AIMistakeAnalysisResponse,
    AIRecommendRequest,
    AIRecommendResponse,
    AIReportRequest,
    AIReportResponse,
    Recommendation,
    StrongPoint,
    WeakPoint,
)
from app.services import ai_learning_service, ai_service as svc

router = APIRouter(prefix="/api/v1/ai")


# ============================================================
# 现有端点
# ============================================================


@router.post("/error-analysis")
async def error_analysis(
    data: ErrorAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await svc.analyze_error(db, current_user.id, data.wrong_question_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return AiResponse(
        session_type="error_analysis",
        **result,
    )


@router.post("/study-advice")
async def study_advice(
    data: StudyAdviceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await svc.generate_advice(db, current_user.id, data.subject)

    return AiResponse(
        session_type="study_advice",
        **result,
    )


# ============================================================
# Stage 13: AI 学习引擎
# ============================================================


@router.post("/explain", response_model=AIExplainResponse)
async def ai_explain(
    data: AIExplainRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 题目讲解。"""
    try:
        result = await ai_learning_service.ai_explain(
            db=db,
            user_id=current_user.id,
            question_id=data.question_id,
            user_answer=data.user_answer,
            is_correct=data.is_correct,
            focus=data.focus,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return AIExplainResponse(**result)


@router.post("/recommend", response_model=AIRecommendResponse)
async def ai_recommend(
    data: AIRecommendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 相似题推荐（规则推荐）。"""
    try:
        result = await ai_learning_service.recommend_similar_questions(
            db=db,
            user_id=current_user.id,
            question_id=data.question_id,
            count=data.count,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return AIRecommendResponse(
        source_question_id=result["source_question_id"],
        recommendations=[Recommendation(**r) for r in result["recommendations"]],
        strategy=result["strategy"],
        tokens_used=result["tokens_used"],
    )


@router.post("/report", response_model=AIReportResponse)
async def ai_report(
    data: AIReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 学习报告。"""
    result = await ai_learning_service.generate_learning_report(
        db=db,
        user_id=current_user.id,
        subject=data.subject,
        days=data.days,
    )

    return AIReportResponse(
        subject=result["subject"],
        period_days=result["period_days"],
        total_answered=result["total_answered"],
        accuracy=result["accuracy"],
        weak_points=[WeakPoint(**wp) for wp in result["weak_points"]],
        strong_points=[StrongPoint(**sp) for sp in result["strong_points"]],
        learning_suggestions=result["learning_suggestions"],
        tokens_used=result["tokens_used"],
        from_fallback=result["from_fallback"],
    )


@router.post("/analyze-mistake", response_model=AIMistakeAnalysisResponse)
async def ai_analyze_mistake(
    data: AIMistakeAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 错因分析。"""
    try:
        result = await ai_learning_service.ai_analyze_mistake(
            db=db,
            user_id=current_user.id,
            question_id=data.question_id,
            user_answer=data.user_answer,
            correct_answer=data.correct_answer,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return AIMistakeAnalysisResponse(**result)
