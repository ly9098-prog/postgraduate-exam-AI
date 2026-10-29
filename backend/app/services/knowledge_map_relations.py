"""Syllabus-scoped relation display selection, ranking and truncation."""

from __future__ import annotations

from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.syllabus import SyllabusKnowledgePoint


def _relation_target(
    edge: KnowledgeEdge,
    point: KnowledgePoint,
    names: dict[int, str],
    source_id: int,
    target_id: int,
) -> tuple[int, str, str] | None:
    payload = None
    if (
        edge.relation_type == "prerequisite"
        and target_id == int(point.id)
        and source_id in names
    ):
        payload = (source_id, names[source_id], "prerequisite")
    elif (
        edge.relation_type == "next"
        and source_id == int(point.id)
        and target_id in names
    ):
        payload = (target_id, names[target_id], "next")
    elif edge.relation_type == "related":
        other_id = target_id if source_id == int(point.id) else source_id
        if other_id in names:
            payload = (other_id, names[other_id], "related")
    return payload


def _build_relation_payloads(
    rows: list[KnowledgeEdge],
    point: KnowledgePoint,
    memberships: dict[int, SyllabusKnowledgePoint],
) -> tuple[list[dict], list[dict], list[dict]]:
    allowed_ids = set(memberships)
    names = {
        kp_id: str(member.name_snapshot)
        for kp_id, member in memberships.items()
        if kp_id != int(point.id)
    }

    prerequisites: list[dict] = []
    next_nodes: list[dict] = []
    related_nodes: list[dict] = []
    buckets = {
        "prerequisite": prerequisites,
        "next": next_nodes,
        "related": related_nodes,
    }
    for edge in rows:
        source_id = int(edge.source_knowledge_point_id)
        target_id = int(edge.target_knowledge_point_id)
        if source_id not in allowed_ids or target_id not in allowed_ids:
            continue
        payload = _relation_target(edge, point, names, source_id, target_id)
        bucket = buckets[payload[2]] if payload else None
        if payload and bucket is not None:
            bucket.append(
                {
                    "knowledge_point_id": payload[0],
                    "name": payload[1],
                    "relation_type": payload[2],
                    "confidence": round(float(edge.confidence or 0.0), 3),
                    "weight": round(float(edge.weight or 0.0), 3),
                }
            )
    for items in (prerequisites, next_nodes, related_nodes):
        items.sort(
            key=lambda item: (
                -item["confidence"],
                -item["weight"],
                item["knowledge_point_id"],
            )
        )
    return prerequisites[:8], next_nodes[:8], related_nodes[:8]
