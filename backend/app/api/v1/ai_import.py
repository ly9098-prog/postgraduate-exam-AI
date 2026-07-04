"""AI 辅助导题路由。

注意：AI 仅生成"待审核数据"，永远不直接写入 questions 正式表。
所有结果统一进入 question_imports 暂存区，再走人工审核流。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.ai_import import (
    AiLogItem,
    AiLogListResponse,
    GenerateRequest,
    GenerateResponse,
)
from app.features import question_pipeline as svc


router = APIRouter(prefix="/api/v1/ai-import")


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    data: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 批量生成草稿题目，进入暂存区。绝不直接进入正式题库。"""
    try:
        result = await svc.generate_drafts(
            db,
            current_user.id,
            knowledge_points=data.knowledge_points,
            difficulty=data.difficulty,
            count=data.count,
            question_type=data.question_type,
            extra_hint=data.extra_hint,
            subject_id=data.subject_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return GenerateResponse(**result)


@router.get("/logs", response_model=AiLogListResponse)
async def list_logs(
    action: str | None = Query(default=None),
    batch_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 调用审计日志（按当前用户）"""
    result = await svc.list_logs(
        db,
        user_id=current_user.id,
        action=action,
        batch_id=batch_id,
        page=page,
        page_size=page_size,
    )
    return AiLogListResponse(
        items=[AiLogItem.model_validate(it) for it in result["items"]],
        page=result["page"],
        pageSize=result["pageSize"],
    )
