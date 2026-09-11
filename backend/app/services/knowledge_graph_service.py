"""Phase 3 — 轻量知识图谱服务。

基于 PostgreSQL 实现知识点关系管理：
- 创建/查询知识点边（prerequisite / parent / related / next）
- 前置知识链查询（BFS，防循环）
- 冷启动推断（基于名称前缀包含关系）
"""

import logging
from collections import deque

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.admin import Subject
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint

logger = logging.getLogger(__name__)

_VALID_RELATION_TYPES = {"prerequisite", "parent", "related", "next"}


async def create_knowledge_edge(
    db: AsyncSession,
    subject_id: int,
    source_id: int,
    target_id: int,
    relation_type: str,
    weight: float = 1.0,
    confidence: float = 1.0,
    source: str = "manual",
) -> dict:
    """创建或更新一条知识点关系边。

    校验:
    - source_id != target_id（防自环）
    - source_id 和 target_id 必须存在且属于同一 subject_id
    - relation_type 必须在合法范围内
    - 已存在则更新 weight/confidence/source/is_active

    返回: {"id": ..., "created": bool, "updated": bool}
    """
    if source_id == target_id:
        raise ValueError("source_knowledge_point_id 不能等于 target_knowledge_point_id")

    if relation_type not in _VALID_RELATION_TYPES:
        raise ValueError(
            f"relation_type 必须为 {_VALID_RELATION_TYPES} 之一，收到 {relation_type!r}"
        )

    # 校验两个知识点存在且 subject_id 一致
    kp_result = await db.execute(
        select(KnowledgePoint).where(
            KnowledgePoint.id.in_([source_id, target_id]),
            KnowledgePoint.is_active,
        )
    )
    kps = {kp.id: kp for kp in kp_result.scalars().all()}

    if source_id not in kps:
        raise ValueError(f"source_knowledge_point_id={source_id} 不存在或已停用")
    if target_id not in kps:
        raise ValueError(f"target_knowledge_point_id={target_id} 不存在或已停用")

    src_kp = kps[source_id]
    tgt_kp = kps[target_id]

    if src_kp.subject_id != subject_id or tgt_kp.subject_id != subject_id:
        raise ValueError(
            f"两个知识点 subject_id 不一致: 请求={subject_id}, "
            f"source.subject_id={src_kp.subject_id}, target.subject_id={tgt_kp.subject_id}"
        )

    # 查找是否已存在
    existing_result = await db.execute(
        select(KnowledgeEdge).where(
            KnowledgeEdge.source_knowledge_point_id == source_id,
            KnowledgeEdge.target_knowledge_point_id == target_id,
            KnowledgeEdge.relation_type == relation_type,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        existing.weight = weight
        existing.confidence = confidence
        existing.source = source
        existing.is_active = True
        existing.updated_at = utcnow()
        await db.flush()
        return {"id": existing.id, "created": False, "updated": True}

    edge = KnowledgeEdge(
        subject_id=subject_id,
        source_knowledge_point_id=source_id,
        target_knowledge_point_id=target_id,
        relation_type=relation_type,
        weight=weight,
        confidence=confidence,
        source=source,
    )
    db.add(edge)
    await db.flush()
    await db.refresh(edge)
    return {"id": edge.id, "created": True, "updated": False}


async def list_knowledge_edges(
    db: AsyncSession,
    subject_id: int,
    relation_type: str | None = None,
    knowledge_point_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """查询知识点关系列表。

    - 按 subject_id 过滤
    - relation_type 可选
    - knowledge_point_id 可选：查 source 或 target 任一端相关边
    """
    conditions = [KnowledgeEdge.subject_id == subject_id]

    if relation_type:
        conditions.append(KnowledgeEdge.relation_type == relation_type)

    if knowledge_point_id is not None:
        conditions.append(
            or_(
                KnowledgeEdge.source_knowledge_point_id == knowledge_point_id,
                KnowledgeEdge.target_knowledge_point_id == knowledge_point_id,
            )
        )

    result = await db.execute(
        select(KnowledgeEdge)
        .where(and_(*conditions))
        .order_by(KnowledgeEdge.weight.desc(), KnowledgeEdge.id.asc())
        .limit(limit)
    )
    edges = result.scalars().all()

    subject_map: dict[int, Subject] = {}
    edge_subject_ids = {e.subject_id for e in edges}
    if edge_subject_ids:
        subj_result = await db.execute(
            select(Subject).where(Subject.id.in_(edge_subject_ids))
        )
        subject_map = {s.id: s for s in subj_result.scalars().all()}

    return [
        {
            "id": e.id,
            "subject_id": e.subject_id,
            "subject_code": subject_map[e.subject_id].code
            if e.subject_id in subject_map
            else "",
            "subject_name": subject_map[e.subject_id].name
            if e.subject_id in subject_map
            else "",
            "source_knowledge_point_id": e.source_knowledge_point_id,
            "source_name": e.source_kp.name if e.source_kp else None,
            "target_knowledge_point_id": e.target_knowledge_point_id,
            "target_name": e.target_kp.name if e.target_kp else None,
            "relation_type": e.relation_type,
            "weight": e.weight,
            "confidence": e.confidence,
            "source": e.source,
        }
        for e in edges
    ]


async def get_prerequisites(
    db: AsyncSession,
    knowledge_point_id: int,
    max_depth: int = 2,
) -> list[dict]:
    """查询前置知识点（BFS）。

    relation_type='prerequisite' 表示 source 是 target 的前置知识，
    所以查 knowledge_point_id 的前置知识 = 查 target=knowledge_point_id 的 source 端。

    返回按 depth 和 weight 排序的知识点列表。
    防循环：visited set。
    """
    max_depth = min(max_depth, 2)
    visited = {knowledge_point_id}
    results = []

    queue = deque()
    # 第一层：查 target=knowledge_point_id 的 prerequisite 边
    first_layer = await _get_prerequisite_sources(db, knowledge_point_id)
    for item in first_layer:
        kp_id = item["knowledge_point_id"]
        if kp_id not in visited:
            visited.add(kp_id)
            item["depth"] = 1
            queue.append(kp_id)
            results.append(item)

    # 第二层
    if max_depth >= 2:
        while queue:
            current_id = queue.popleft()
            second_layer = await _get_prerequisite_sources(db, current_id)
            for item in second_layer:
                kp_id = item["knowledge_point_id"]
                if kp_id not in visited:
                    visited.add(kp_id)
                    item["depth"] = 2
                    results.append(item)

    # 按 depth ASC, weight DESC 排序
    results.sort(key=lambda x: (x["depth"], -x["weight"]))
    return results


async def _get_prerequisite_sources(
    db: AsyncSession,
    target_kp_id: int,
) -> list[dict]:
    """查 target=target_kp_id 且 relation_type='prerequisite' 的 source 端知识点。"""
    result = await db.execute(
        select(KnowledgeEdge)
        .where(
            KnowledgeEdge.target_knowledge_point_id == target_kp_id,
            KnowledgeEdge.relation_type == "prerequisite",
            KnowledgeEdge.is_active,
        )
        .order_by(KnowledgeEdge.weight.desc())
    )
    edges = result.scalars().all()

    items = []
    for e in edges:
        kp = e.source_kp
        if kp and kp.is_active:
            items.append(
                {
                    "knowledge_point_id": kp.id,
                    "name": kp.name,
                    "subject_id": kp.subject_id,
                    "weight": e.weight,
                    "confidence": e.confidence,
                    "edge_id": e.id,
                }
            )
    return items


async def get_next_nodes(
    db: AsyncSession,
    knowledge_point_id: int,
    max_depth: int = 1,
) -> list[dict]:
    """查询后续知识点。

    relation_type='next' 表示 source 后接 target，
    所以查 source=knowledge_point_id 的 target 端。

    如果 next 不存在，fallback 到 related。
    """
    result = await db.execute(
        select(KnowledgeEdge)
        .where(
            KnowledgeEdge.source_knowledge_point_id == knowledge_point_id,
            KnowledgeEdge.relation_type == "next",
            KnowledgeEdge.is_active,
        )
        .order_by(KnowledgeEdge.weight.desc())
        .limit(10)
    )
    edges = result.scalars().all()

    items = []
    for e in edges:
        kp = e.target_kp
        if kp and kp.is_active:
            items.append(
                {
                    "knowledge_point_id": kp.id,
                    "name": kp.name,
                    "subject_id": kp.subject_id,
                    "weight": e.weight,
                    "confidence": e.confidence,
                    "relation_type": "next",
                    "edge_id": e.id,
                }
            )

    if not items:
        # fallback 到 related
        items = await get_related_nodes(db, knowledge_point_id, limit=5)

    return items


async def get_related_nodes(
    db: AsyncSession,
    knowledge_point_id: int,
    limit: int = 10,
) -> list[dict]:
    """查询 related 关系的知识点（双向查）。"""
    result = await db.execute(
        select(KnowledgeEdge)
        .where(
            KnowledgeEdge.is_active,
            KnowledgeEdge.relation_type == "related",
            or_(
                KnowledgeEdge.source_knowledge_point_id == knowledge_point_id,
                KnowledgeEdge.target_knowledge_point_id == knowledge_point_id,
            ),
        )
        .order_by(KnowledgeEdge.weight.desc())
        .limit(limit)
    )
    edges = result.scalars().all()

    items = []
    for e in edges:
        # 取另一端
        if e.source_knowledge_point_id == knowledge_point_id:
            kp = e.target_kp
        else:
            kp = e.source_kp
        if kp and kp.is_active:
            items.append(
                {
                    "knowledge_point_id": kp.id,
                    "name": kp.name,
                    "subject_id": kp.subject_id,
                    "weight": e.weight,
                    "confidence": e.confidence,
                    "relation_type": "related",
                    "edge_id": e.id,
                }
            )
    return items


async def infer_simple_edges_from_names(
    db: AsyncSession,
    subject_id: int,
    limit: int = 500,
    force_rebuild: bool = False,
) -> dict:
    """冷启动推断：基于知识点名称的子串包含关系创建弱边。

    规则:
    - 如果 A.name 是 B.name 的子串 → parent 关系 (A 是 B 的上级概念)
      例: "链表" → "单链表", "栈" → "顺序栈"
    - 不自动创建高置信度 prerequisite
    - confidence <= 0.5, source='inferred'

    P1-1 修复: 批量计算 + 批量写入，消除 N+1 查询。
    原来在双重循环中逐条调用 create_knowledge_edge()，每次 2~3 次 DB 查询。
    现在先在 Python 端计算所有候选边，再一次查询已有边、批量 INSERT。

    force_rebuild=True 时:
    - 先删除该科目所有 source='inferred' 的边（manual/imported/ai 不受影响）
    - 再重新推断
    - 用于修正旧推断逻辑（如 startswith → in 子串修正）

    返回: {"created": int, "updated": int, "skipped": int, "deleted": int}
    """
    # 0. force_rebuild: 先清除旧推断边
    deleted = 0
    if force_rebuild:
        del_result = await db.execute(
            delete(KnowledgeEdge).where(
                KnowledgeEdge.subject_id == subject_id,
                KnowledgeEdge.source == "inferred",
            )
        )
        deleted = del_result.rowcount or 0
        await db.flush()
        logger.info(
            "force_rebuild: deleted %d inferred edges for subject_id=%s",
            deleted,
            subject_id,
        )

    # 1. 获取该科目所有活跃知识点 (1 次查询)
    result = await db.execute(
        select(KnowledgePoint)
        .where(
            KnowledgePoint.subject_id == subject_id,
            KnowledgePoint.is_active,
        )
        .order_by(KnowledgePoint.id)
        .limit(limit)
    )
    kps = list(result.scalars().all())

    if len(kps) < 2:
        return {"created": 0, "updated": 0, "skipped": 0, "deleted": deleted}

    # 2. 查已有推断边 (1 次查询)
    #    force_rebuild 时已清空，existing_edges 为空，全部走新增
    existing_result = await db.execute(
        select(
            KnowledgeEdge.source_knowledge_point_id,
            KnowledgeEdge.target_knowledge_point_id,
            KnowledgeEdge.relation_type,
        ).where(
            KnowledgeEdge.subject_id == subject_id,
            KnowledgeEdge.source == "inferred",
        )
    )
    existing_edges = {(row[0], row[1], row[2]) for row in existing_result.all()}

    # 3. Python 端批量计算候选边 (0 次 DB 查询)
    kps_sorted = sorted(kps, key=lambda kp: len(kp.normalized_name or kp.name))
    new_edges: list[KnowledgeEdge] = []
    skipped = 0

    for i, kp_a in enumerate(kps_sorted):
        name_a = (kp_a.normalized_name or kp_a.name).strip()
        if not name_a:
            continue

        for kp_b in kps_sorted[i + 1 :]:
            name_b = (kp_b.normalized_name or kp_b.name).strip()
            if not name_b:
                continue

            # A 是 B 的子串 → parent (A 是上级概念)
            if name_a in name_b and name_a != name_b:
                edge_key = (kp_a.id, kp_b.id, "parent")
                if edge_key in existing_edges:
                    skipped += 1
                    continue
                new_edges.append(
                    KnowledgeEdge(
                        subject_id=subject_id,
                        source_knowledge_point_id=kp_a.id,
                        target_knowledge_point_id=kp_b.id,
                        relation_type="parent",
                        weight=0.5,
                        confidence=0.3,
                        source="inferred",
                    )
                )

    # 4. 批量写入 (1 次批量操作)
    created = 0
    if new_edges:
        db.add_all(new_edges)
        await db.flush()
        created = len(new_edges)

    return {"created": created, "updated": 0, "skipped": skipped, "deleted": deleted}


async def get_edge_status(
    db: AsyncSession,
    subject_id: int,
) -> dict:
    """返回指定科目的边统计。"""
    from sqlalchemy import func

    result = await db.execute(
        select(
            KnowledgeEdge.relation_type,
            func.count(KnowledgeEdge.id),
        )
        .where(KnowledgeEdge.subject_id == subject_id)
        .group_by(KnowledgeEdge.relation_type)
    )
    type_counts = {row[0]: row[1] for row in result.all()}

    total_result = await db.execute(
        select(func.count(KnowledgeEdge.id)).where(
            KnowledgeEdge.subject_id == subject_id,
        )
    )
    total = total_result.scalar() or 0

    active_result = await db.execute(
        select(func.count(KnowledgeEdge.id)).where(
            KnowledgeEdge.subject_id == subject_id,
            KnowledgeEdge.is_active,
        )
    )
    active = active_result.scalar() or 0

    return {
        "subject_id": subject_id,
        "total_edges": total,
        "prerequisite_edges": type_counts.get("prerequisite", 0),
        "parent_edges": type_counts.get("parent", 0),
        "related_edges": type_counts.get("related", 0),
        "next_edges": type_counts.get("next", 0),
        "active_edges": active,
    }
