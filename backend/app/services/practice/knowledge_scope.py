"""Resolve practice knowledge scope against the active syllabus hierarchy."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from sqlalchemy import select

from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint


async def load_active_knowledge_point(
    db: Any,
    knowledge_point_id: int,
    subject_ids: list[int],
) -> KnowledgePoint | None:
    return (
        await db.execute(
            select(KnowledgePoint).where(
                KnowledgePoint.id == int(knowledge_point_id),
                KnowledgePoint.subject_id.in_(subject_ids),
                KnowledgePoint.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()


def root_scope(point: KnowledgePoint, syllabus_version_id: int) -> dict:
    return {
        "root_id": int(point.id),
        "root_name": str(point.name),
        "subject_id": int(point.subject_id),
        "syllabus_version_id": int(syllabus_version_id),
        "knowledge_point_ids": [int(point.id)],
        "include_descendants": False,
    }


async def load_descendant_scope(
    db: Any,
    point: KnowledgePoint,
    syllabus_version_id: int,
    memberships: dict[int, Any],
) -> dict | None:
    """Return the syllabus-ordered BFS closure of active parent edges."""
    allowed_ids = {int(kp_id) for kp_id in memberships}
    active_rows = await db.execute(
        select(KnowledgePoint.id).where(
            KnowledgePoint.subject_id == int(point.subject_id),
            KnowledgePoint.id.in_(allowed_ids),
            KnowledgePoint.is_active.is_(True),
        )
    )
    active_ids = {int(value) for value in active_rows.scalars().all()}
    if int(point.id) not in active_ids:
        return None

    edge_rows = await db.execute(
        select(
            KnowledgeEdge.source_knowledge_point_id,
            KnowledgeEdge.target_knowledge_point_id,
        ).where(
            KnowledgeEdge.subject_id == int(point.subject_id),
            KnowledgeEdge.relation_type == "parent",
            KnowledgeEdge.is_active.is_(True),
            KnowledgeEdge.source_knowledge_point_id.in_(active_ids),
            KnowledgeEdge.target_knowledge_point_id.in_(active_ids),
        )
    )
    children: dict[int, list[int]] = defaultdict(list)
    for parent_id, child_id in edge_rows.all():
        children[int(parent_id)].append(int(child_id))

    def sort_key(kp_id: int) -> tuple[int, int]:
        member = memberships.get(kp_id)
        return (int(getattr(member, "sort_order", 0) or 0), kp_id)

    for child_ids in children.values():
        child_ids.sort(key=sort_key)

    ordered_ids: list[int] = []
    queue = deque([int(point.id)])
    seen: set[int] = set()
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        ordered_ids.append(current)
        queue.extend(children.get(current, ()))

    return {
        "root_id": int(point.id),
        "root_name": str(point.name),
        "subject_id": int(point.subject_id),
        "syllabus_version_id": int(syllabus_version_id),
        "knowledge_point_ids": ordered_ids,
        "include_descendants": True,
    }
