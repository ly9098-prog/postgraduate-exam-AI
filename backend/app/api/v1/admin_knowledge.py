"""管理端知识点 backfill + 状态 + 知识图谱边 API。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.knowledge_mastery import (
    KnowledgeBackfillRequest,
    KnowledgeBackfillResponse,
    KnowledgeStatusResponse,
)
from app.schemas.knowledge_path import (
    KnowledgeEdgeBackfillRequest,
    KnowledgeEdgeCreate,
    KnowledgeEdgeResponse,
    KnowledgeEdgeStatusResponse,
)
from app.services.admin_audit_service import write_admin_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/v1/knowledge", tags=["admin-knowledge"])


@router.post("/backfill", response_model=KnowledgeBackfillResponse)
async def backfill_knowledge_points(
    data: KnowledgeBackfillRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """扫描题目 knowledge_points JSON，写入 knowledge_points 和 question_knowledge_points。"""
    from app.services import knowledge_point_service

    result = await knowledge_point_service.backfill_question_knowledge_points(
        db, subject=data.subject, limit=data.limit,
    )
    await write_admin_audit(
        db, current_admin, "knowledge.backfill", "knowledge",
        None, severity="normal",
        detail={"subject": data.subject, "limit": data.limit, **result},
        request=request,
    )
    await db.commit()
    return KnowledgeBackfillResponse(**result)


@router.get("/status", response_model=KnowledgeStatusResponse)
async def get_knowledge_status(
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    """返回知识点映射状态统计。"""
    from app.services import knowledge_point_service

    result = await knowledge_point_service.get_knowledge_status(db)
    return KnowledgeStatusResponse(**result)


# ── Phase 3: 知识图谱边管理 ──


@router.post("/edges", response_model=KnowledgeEdgeResponse)
async def create_knowledge_edge(
    data: KnowledgeEdgeCreate,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """人工创建知识点关系。"""
    from sqlalchemy import select

    # 需要先查 subject（从 source_kp 获取）
    from app.models.knowledge_point import KnowledgePoint
    from app.services import knowledge_graph_service
    kp_result = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.id == data.source_knowledge_point_id)
    )
    source_kp = kp_result.scalar_one_or_none()
    if not source_kp:
        raise HTTPException(status_code=400, detail="source_knowledge_point_id 不存在")

    await knowledge_graph_service.create_knowledge_edge(
        db=db,
        subject=source_kp.subject,
        source_id=data.source_knowledge_point_id,
        target_id=data.target_knowledge_point_id,
        relation_type=data.relation_type,
        weight=data.weight,
        confidence=data.confidence,
        source=data.source,
    )
    await write_admin_audit(
        db, current_admin, "knowledge.create_edge", "knowledge_edge",
        None, severity="normal",
        detail={"source_kp_id": data.source_knowledge_point_id, "target_kp_id": data.target_knowledge_point_id, "relation_type": data.relation_type},
        request=request,
    )
    await db.commit()

    # 返回完整边信息
    edges = await knowledge_graph_service.list_knowledge_edges(
        db=db,
        subject=source_kp.subject,
        knowledge_point_id=data.source_knowledge_point_id,
        limit=1,
    )
    if edges:
        return KnowledgeEdgeResponse(**edges[0])

    raise HTTPException(status_code=500, detail="创建成功但查询失败")


@router.post("/edges/infer")
async def infer_knowledge_edges(
    data: KnowledgeEdgeBackfillRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """基于知识点名称推断低置信度关系。

    force_rebuild=true 时先删除该科目所有 source='inferred' 边再重新推断，
    manual/imported/ai 边不受影响。knowledge_points、题目映射、用户掌握度、推荐日志均不受影响。
    """
    from app.services import knowledge_graph_service

    result = await knowledge_graph_service.infer_simple_edges_from_names(
        db=db,
        subject=data.subject,
        limit=data.limit,
        force_rebuild=data.force_rebuild,
    )
    await write_admin_audit(
        db, current_admin, "knowledge.infer_edges", "knowledge_edge",
        None, severity="normal",
        detail={"subject": data.subject, "limit": data.limit, "force_rebuild": data.force_rebuild, **result},
        request=request,
    )
    await db.commit()
    return result


@router.get("/edges/status", response_model=KnowledgeEdgeStatusResponse)
async def get_edge_status(
    subject: str = Query(...),
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    """返回指定科目知识图谱边统计。"""
    from app.services import knowledge_graph_service

    result = await knowledge_graph_service.get_edge_status(db, subject)
    return KnowledgeEdgeStatusResponse(**result)
