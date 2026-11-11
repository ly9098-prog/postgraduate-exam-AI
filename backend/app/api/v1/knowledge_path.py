"""Phase 3 — 知识路径推荐 + 知识点关系查询 API。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.knowledge_path import (
    KnowledgeEdgeResponse,
    KnowledgePathNode,
    KnowledgePathResponse,
)
from app.core.runtime_paths import API_V1_PREFIX

logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{API_V1_PREFIX}", tags=["knowledge-path"])


@router.get("/knowledge-path", response_model=KnowledgePathResponse)
async def get_knowledge_path(
    subject_id: int = Query(...),
    start_knowledge_point_id: int | None = Query(None),
    limit: int = Query(8, ge=1, le=20),
    questions_per_node: int = Query(3, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回当前用户的知识路径推荐。"""
    from app.services import knowledge_path_service

    result = await knowledge_path_service.get_user_path_recommendations(
        db=db,
        user_id=current_user.id,
        subject=subject_id,
        start_knowledge_point_id=start_knowledge_point_id,
        limit=limit,
        questions_per_node=questions_per_node,
    )

    if result.get("subject_id") is None:
        raise HTTPException(status_code=400, detail="科目不存在或无法解析")

    nodes = [
        KnowledgePathNode(
            knowledge_point_id=n["knowledge_point_id"],
            name=n["name"],
            subject_id=n["subject_id"],
            subject_code=n.get("subject_code", ""),
            subject_name=n.get("subject_name", ""),
            mastery_score=n.get("mastery_score"),
            weakness_level=n.get("weakness_level"),
            path_role=n["path_role"],
            priority=n.get("priority", 0.0),
            reason=n.get("reason", ""),
            recommended_question_ids=n.get("recommended_question_ids", []),
        )
        for n in result.get("nodes", [])
    ]

    return KnowledgePathResponse(
        subject_id=result.get("subject_id"),
        subject_code=result.get("subject_code", ""),
        subject_name=result.get("subject_name", ""),
        user_id=result["user_id"],
        start_knowledge_point_id=result.get("start_knowledge_point_id"),
        strategy=result.get("strategy", "knowledge_path"),
        nodes=nodes,
        recommended_question_ids=result.get("recommended_question_ids", []),
        fallback_used=result.get("fallback_used", False),
    )


@router.get("/knowledge-edges", response_model=list[KnowledgeEdgeResponse])
async def get_knowledge_edges(
    subject_id: int = Query(...),
    relation_type: str | None = Query(None),
    knowledge_point_id: int | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回知识点关系列表。"""
    from app.services import knowledge_graph_service

    edges = await knowledge_graph_service.list_knowledge_edges(
        db=db,
        subject_id=subject_id,
        relation_type=relation_type,
        knowledge_point_id=knowledge_point_id,
        limit=limit,
    )

    return [KnowledgeEdgeResponse(**e) for e in edges]
