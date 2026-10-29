"""Deterministic parent selection and syllabus-ordered tree traversal."""

from __future__ import annotations

from collections import defaultdict

from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.syllabus import SyllabusKnowledgePoint


def _edge_source_rank(source: str | None) -> int:
    return {"manual": 0, "imported": 1, "ai": 2, "inferred": 3}.get(
        str(source or ""), 4
    )


def _would_cycle(child_id: int, parent_id: int, parent_map: dict[int, int]) -> bool:
    cursor = parent_id
    seen: set[int] = set()
    while cursor in parent_map and cursor not in seen:
        if cursor == child_id:
            return True
        seen.add(cursor)
        cursor = parent_map[cursor]
    return cursor == child_id


def _build_parent_map(
    points: list[KnowledgePoint], edges: list[KnowledgeEdge]
) -> dict[int, int]:
    point_ids = {int(point.id) for point in points}
    candidates = [
        edge
        for edge in edges
        if edge.relation_type == "parent"
        and edge.is_active
        and int(edge.source_knowledge_point_id) in point_ids
        and int(edge.target_knowledge_point_id) in point_ids
        and int(edge.source_knowledge_point_id) != int(edge.target_knowledge_point_id)
    ]
    candidates.sort(
        key=lambda edge: (
            _edge_source_rank(edge.source),
            -float(edge.confidence or 0.0),
            -float(edge.weight or 0.0),
            int(edge.source_knowledge_point_id),
            int(edge.target_knowledge_point_id),
        )
    )
    parent_map: dict[int, int] = {}
    for edge in candidates:
        parent_id = int(edge.source_knowledge_point_id)
        child_id = int(edge.target_knowledge_point_id)
        if child_id in parent_map:
            continue
        if _would_cycle(child_id, parent_id, parent_map):
            continue
        parent_map[child_id] = parent_id
    return parent_map


def _ordered_tree_rows(
    points: list[KnowledgePoint],
    parent_map: dict[int, int],
    memberships: dict[int, SyllabusKnowledgePoint] | None = None,
) -> list[tuple[KnowledgePoint, int, int | None, int]]:
    by_id = {int(point.id): point for point in points}
    membership_map = memberships or {}

    def sort_key(kp_id: int) -> tuple[int, str, int]:
        member = membership_map.get(kp_id)
        return (
            int(member.sort_order or 0) if member is not None else 0,
            str(member.name_snapshot) if member is not None else str(by_id[kp_id].name),
            kp_id,
        )

    children: dict[int | None, list[int]] = defaultdict(list)
    for point in points:
        point_id = int(point.id)
        children[parent_map.get(point_id)].append(point_id)
    for ids in children.values():
        ids.sort(key=sort_key)

    rows: list[tuple[KnowledgePoint, int, int | None, int]] = []
    visited: set[int] = set()

    def walk(kp_id: int, depth: int) -> None:
        if kp_id in visited:
            return
        visited.add(kp_id)
        child_ids = children.get(kp_id, [])
        rows.append((by_id[kp_id], depth, parent_map.get(kp_id), len(child_ids)))
        for child_id in child_ids:
            walk(child_id, min(depth + 1, 8))

    for root_id in children.get(None, []):
        walk(root_id, 0)
    # Defensive fallback for malformed/cyclic legacy graph fragments.
    for point in sorted(points, key=lambda item: sort_key(int(item.id))):
        if int(point.id) not in visited:
            walk(int(point.id), 0)
    return rows
