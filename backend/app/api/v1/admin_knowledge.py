"""管理端知识点 backfill + 状态 + 知识图谱边 API。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.knowledge_mastery import (
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


@router.get("/status", response_model=KnowledgeStatusResponse)
async def get_knowledge_status(
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    """返回知识点映射状态统计。"""
    from app.services import knowledge_point_service

    result = await knowledge_point_service.get_knowledge_status(db)
    return KnowledgeStatusResponse(**result)


@router.get("/subjects")
async def list_knowledge_graph_subjects(
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    """返回存在知识点的科目，供管理端知识图谱筛选。"""
    from sqlalchemy import func, select

    from app.models.admin import Subject
    from app.models.knowledge_edge import KnowledgeEdge
    from app.models.knowledge_point import KnowledgePoint

    subject_result = await db.execute(
        select(Subject).where(Subject.is_active).order_by(Subject.sort_order.asc(), Subject.id.asc())
    )
    subjects = subject_result.scalars().all()

    kp_result = await db.execute(
        select(KnowledgePoint.subject_id, func.count(KnowledgePoint.id))
        .where(KnowledgePoint.is_active)
        .group_by(KnowledgePoint.subject_id)
    )
    kp_counts = {int(subject_id): int(count) for subject_id, count in kp_result.all()}

    edge_result = await db.execute(
        select(KnowledgeEdge.subject_id, func.count(KnowledgeEdge.id))
        .where(KnowledgeEdge.is_active)
        .group_by(KnowledgeEdge.subject_id)
    )
    edge_counts = {int(subject_id): int(count) for subject_id, count in edge_result.all()}

    return [
        {
            "id": subject.id,
            "code": subject.code,
            "name": subject.name,
            "level": subject.level,
            "path": subject.path,
            "knowledge_point_count": kp_counts.get(subject.id, 0),
            "edge_count": edge_counts.get(subject.id, 0),
        }
        for subject in subjects
        if kp_counts.get(subject.id, 0) > 0
    ]


@router.get("/graph")
async def get_knowledge_graph(
    subject_id: int = Query(...),
    relation_type: str | None = Query(None),
    knowledge_point_id: int | None = Query(None),
    search: str | None = Query(None, max_length=128),
    depth: int = Query(2, ge=1, le=3),
    max_nodes: int = Query(70, ge=10, le=120),
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    """返回管理端知识图谱可视化所需的节点、边与汇总信息。

    - 未指定中心节点时，优先展示连接度高的知识点；
    - 指定中心节点或搜索命中时，按无向邻接做有限深度 BFS，仅用于可视化取景；
    - 边本身仍保持 source -> target 的真实有向语义；
    - 返回所有关系的统计，但画布可按 relation_type 过滤。
    """
    from collections import Counter, deque

    from sqlalchemy import func, select

    from app.models.admin import Subject
    from app.models.knowledge_edge import KnowledgeEdge
    from app.models.knowledge_point import KnowledgePoint
    from app.models.question import Question
    from app.models.question_knowledge_point import QuestionKnowledgePoint

    valid_relations = {"prerequisite", "parent", "related", "next"}
    if relation_type and relation_type not in valid_relations:
        raise HTTPException(status_code=422, detail="relation_type 不合法")

    subject = await db.get(Subject, subject_id)
    if not subject or not subject.is_active:
        raise HTTPException(status_code=404, detail="科目不存在或已停用")

    kp_result = await db.execute(
        select(KnowledgePoint)
        .where(KnowledgePoint.subject_id == subject_id, KnowledgePoint.is_active)
        .order_by(KnowledgePoint.id.asc())
    )
    knowledge_points = kp_result.scalars().all()
    kp_map = {kp.id: kp for kp in knowledge_points}
    kp_ids = set(kp_map)

    if not kp_ids:
        return {
            "subject": {"id": subject.id, "code": subject.code, "name": subject.name},
            "summary": {
                "total_nodes": 0, "total_edges": 0, "visible_nodes": 0, "visible_edges": 0,
                "isolated_nodes": 0, "avg_confidence": 0.0, "relation_counts": {},
                "source_counts": {}, "relation_confidence": {},
            },
            "nodes": [], "edges": [], "hot_nodes": [], "focus_id": None,
        }

    qcount_result = await db.execute(
        select(
            QuestionKnowledgePoint.knowledge_point_id,
            func.count(func.distinct(QuestionKnowledgePoint.question_id)),
        )
        .join(Question, Question.id == QuestionKnowledgePoint.question_id)
        .where(
            QuestionKnowledgePoint.knowledge_point_id.in_(kp_ids),
            Question.is_active == True,  # noqa: E712
        )
        .group_by(QuestionKnowledgePoint.knowledge_point_id)
    )
    question_counts = {int(kp_id): int(count) for kp_id, count in qcount_result.all()}

    edge_result = await db.execute(
        select(KnowledgeEdge).where(
            KnowledgeEdge.subject_id == subject_id,
            KnowledgeEdge.is_active,
        )
    )
    all_edges = [
        edge for edge in edge_result.scalars().all()
        if edge.source_knowledge_point_id in kp_ids and edge.target_knowledge_point_id in kp_ids
    ]
    filtered_edges = [
        edge for edge in all_edges if not relation_type or edge.relation_type == relation_type
    ]

    relation_counts = Counter(edge.relation_type for edge in all_edges)
    source_counts = Counter(edge.source for edge in all_edges)
    confidence_sums: dict[str, float] = {}
    confidence_counts: dict[str, int] = {}
    for edge in all_edges:
        confidence_sums[edge.relation_type] = confidence_sums.get(edge.relation_type, 0.0) + float(edge.confidence or 0.0)
        confidence_counts[edge.relation_type] = confidence_counts.get(edge.relation_type, 0) + 1

    all_degree = Counter()
    filtered_degree = Counter()
    adjacency: dict[int, list[int]] = {kp_id: [] for kp_id in kp_ids}
    for edge in all_edges:
        all_degree[edge.source_knowledge_point_id] += 1
        all_degree[edge.target_knowledge_point_id] += 1
    for edge in filtered_edges:
        source_id = edge.source_knowledge_point_id
        target_id = edge.target_knowledge_point_id
        filtered_degree[source_id] += 1
        filtered_degree[target_id] += 1
        adjacency[source_id].append(target_id)
        adjacency[target_id].append(source_id)

    normalized_search = (search or "").strip().casefold()
    search_matches: list[int] = []
    if normalized_search:
        ranked_matches: list[tuple[int, int, int]] = []
        for kp in knowledge_points:
            aliases = kp.aliases if isinstance(kp.aliases, list) else []
            alias_values = [str(alias).strip().casefold() for alias in aliases if str(alias).strip()]
            name = (kp.name or "").casefold()
            normalized_name = (kp.normalized_name or "").casefold()

            rank: int | None = None
            if normalized_search == str(kp.id):
                rank = 0
            elif normalized_search == name or normalized_search == normalized_name:
                rank = 1
            elif any(normalized_search == alias for alias in alias_values):
                rank = 2
            elif name.startswith(normalized_search) or normalized_name.startswith(normalized_search):
                rank = 3
            elif any(alias.startswith(normalized_search) for alias in alias_values):
                rank = 4
            elif normalized_search in name or normalized_search in normalized_name:
                rank = 5
            elif any(normalized_search in alias for alias in alias_values):
                rank = 6

            if rank is not None:
                # Text relevance wins first; graph degree only breaks ties so an
                # alias hit never loses to an unrelated high-degree node.
                ranked_matches.append((rank, -all_degree[kp.id], kp.id))

        ranked_matches.sort()
        search_matches = [kp_id for _, _, kp_id in ranked_matches]

    # 显式传入中心知识点时应 fail-fast。旧行为在 ID 不属于当前科目时静默
    # 回退到总览，会让管理员误以为定位成功。
    if knowledge_point_id is not None and knowledge_point_id not in kp_map:
        raise HTTPException(status_code=404, detail="知识点不存在、已停用或不属于当前科目")

    focus_id: int | None = None
    if knowledge_point_id is not None:
        focus_id = knowledge_point_id
    elif search_matches:
        focus_id = search_matches[0]

    selected_ids: list[int] = []
    selected_set: set[int] = set()

    if focus_id is not None:
        queue = deque([(focus_id, 0)])
        selected_set.add(focus_id)
        selected_ids.append(focus_id)
        while queue and len(selected_ids) < max_nodes:
            current_id, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            neighbors = sorted(
                set(adjacency.get(current_id, [])),
                key=lambda kp_id: (-filtered_degree[kp_id], -question_counts.get(kp_id, 0), kp_id),
            )
            for neighbor_id in neighbors:
                if neighbor_id in selected_set:
                    continue
                selected_set.add(neighbor_id)
                selected_ids.append(neighbor_id)
                queue.append((neighbor_id, current_depth + 1))
                if len(selected_ids) >= max_nodes:
                    break
    elif normalized_search:
        # 搜索词没有命中时返回空视图，而不是悄悄展示“热门总览”。这样前端
        # 能准确告诉管理员“没有搜索结果”。
        selected_ids = []
        selected_set = set()
    else:
        ranked_ids = sorted(
            kp_ids,
            key=lambda kp_id: (-filtered_degree[kp_id], -all_degree[kp_id], -question_counts.get(kp_id, 0), kp_id),
        )
        selected_ids = ranked_ids[:max_nodes]
        selected_set = set(selected_ids)
        focus_id = selected_ids[0] if selected_ids else None

    visible_edges = [
        edge for edge in filtered_edges
        if edge.source_knowledge_point_id in selected_set and edge.target_knowledge_point_id in selected_set
    ]

    incoming_counts = Counter(edge.target_knowledge_point_id for edge in all_edges)
    outgoing_counts = Counter(edge.source_knowledge_point_id for edge in all_edges)
    node_relation_counts: dict[int, Counter] = {kp_id: Counter() for kp_id in kp_ids}
    for edge in all_edges:
        node_relation_counts[edge.source_knowledge_point_id][edge.relation_type] += 1
        node_relation_counts[edge.target_knowledge_point_id][edge.relation_type] += 1

    nodes = []
    for kp_id in selected_ids:
        kp = kp_map[kp_id]
        relation_breakdown = node_relation_counts[kp_id]
        nodes.append({
            "id": kp.id,
            "name": kp.name,
            "normalized_name": kp.normalized_name,
            "aliases": [str(alias) for alias in (kp.aliases or []) if str(alias).strip()] if isinstance(kp.aliases, list) else [],
            "description": kp.description,
            "difficulty_level": kp.difficulty_level,
            "subject_id": kp.subject_id,
            "question_count": question_counts.get(kp.id, 0),
            "in_degree": incoming_counts[kp.id],
            "out_degree": outgoing_counts[kp.id],
            "degree": all_degree[kp.id],
            "relation_counts": dict(relation_breakdown),
        })

    edge_payload = [
        {
            "id": edge.id,
            "source": edge.source_knowledge_point_id,
            "target": edge.target_knowledge_point_id,
            "relation_type": edge.relation_type,
            "weight": float(edge.weight or 0.0),
            "confidence": float(edge.confidence or 0.0),
            "source_type": edge.source,
        }
        for edge in visible_edges
    ]

    hot_nodes = [
        {
            "id": kp_id,
            "name": kp_map[kp_id].name,
            "degree": all_degree[kp_id],
        }
        for kp_id in sorted(
            kp_ids,
            key=lambda item: (-all_degree[item], -question_counts.get(item, 0), item),
        )[:6]
    ]

    total_confidence = sum(float(edge.confidence or 0.0) for edge in all_edges)
    return {
        "subject": {"id": subject.id, "code": subject.code, "name": subject.name},
        "summary": {
            "total_nodes": len(kp_ids),
            "total_edges": len(all_edges),
            "visible_nodes": len(nodes),
            "visible_edges": len(edge_payload),
            "isolated_nodes": sum(1 for kp_id in kp_ids if all_degree[kp_id] == 0),
            "avg_confidence": round(total_confidence / len(all_edges), 4) if all_edges else 0.0,
            "relation_counts": dict(relation_counts),
            "source_counts": dict(source_counts),
            "relation_confidence": {
                relation: round(confidence_sums[relation] / confidence_counts[relation], 4)
                for relation in confidence_sums
                if confidence_counts.get(relation)
            },
        },
        "nodes": nodes,
        "edges": edge_payload,
        "hot_nodes": hot_nodes,
        "focus_id": focus_id,
    }


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

    # 需要先查 subject_id（从 source_kp 获取）
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
        subject_id=source_kp.subject_id,
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
        subject_id=source_kp.subject_id,
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
        subject_id=data.subject_id,
        limit=data.limit,
        force_rebuild=data.force_rebuild,
    )
    await write_admin_audit(
        db, current_admin, "knowledge.infer_edges", "knowledge_edge",
        None, severity="normal",
        detail={"subject_id": data.subject_id, "limit": data.limit, "force_rebuild": data.force_rebuild, **result},
        request=request,
    )
    await db.commit()
    return result


@router.get("/edges/status", response_model=KnowledgeEdgeStatusResponse)
async def get_edge_status(
    subject_id: int = Query(...),
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    """返回指定科目知识图谱边统计。"""
    from app.services import knowledge_graph_service

    result = await knowledge_graph_service.get_edge_status(db, subject_id)
    return KnowledgeEdgeStatusResponse(**result)
