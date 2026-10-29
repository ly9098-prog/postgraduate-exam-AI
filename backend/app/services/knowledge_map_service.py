"""408 student-facing knowledge mastery map.

The map is a read model over the existing canonical knowledge state and graph
facts.  It deliberately does not maintain a second mastery score.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subject_scope import EXAM408_CORE_CODES, EXAM408_ROOT_CODE
from app.models.knowledge_point import KnowledgePoint
from app.models.syllabus import SyllabusKnowledgePoint
from app.services import syllabus_service
from app.services.knowledge_map_detail import (
    _detail_payload,
    _detail_tree_labels,
    _practice_route_params,
)
from app.services.knowledge_map_hierarchy import _build_hierarchy_metadata
from app.services.knowledge_map_nodes import _detail_node, _node_payload
from app.services.knowledge_map_queries import (
    _load_core_subjects,
    _load_overview_points,
    _load_parent_edges,
    _load_point,
    _load_relation_edges,
    _load_states,
    _load_subject_points,
    _load_trainable_counts,
    _recent_answers,
)
from app.services.knowledge_map_relations import _build_relation_payloads
from app.services.knowledge_map_summary import _build_subject_summary
from app.services.knowledge_map_summary import _state_status as _state_status
from app.services.knowledge_map_topology import _build_parent_map, _ordered_tree_rows


async def get_overview(db: AsyncSession, user_id: int) -> dict:
    root, core_subjects = await _load_core_subjects(db)
    if root is None or len(core_subjects) != len(EXAM408_CORE_CODES):
        return {
            "scope": EXAM408_ROOT_CODE,
            "syllabus_version": None,
            "scope_ready": False,
            "subjects": [],
        }

    subject_ids = [int(subject.id) for subject in core_subjects]
    syllabus_version, memberships = await syllabus_service.active_memberships(
        db, subject_ids
    )
    if syllabus_version is None:
        return {
            "scope": EXAM408_ROOT_CODE,
            "syllabus_version": None,
            "scope_ready": False,
            "subjects": [],
        }

    points = await _load_overview_points(db, subject_ids, memberships)
    points_by_subject: dict[int, list[KnowledgePoint]] = defaultdict(list)
    for point in points:
        points_by_subject[int(point.subject_id)].append(point)

    states = await _load_states(db, user_id, subject_ids)
    trainable_counts = await _load_trainable_counts(db, subject_ids)
    summaries = [
        _build_subject_summary(
            subject,
            points_by_subject.get(int(subject.id), []),
            states,
            trainable_counts,
        )
        for subject in core_subjects
    ]
    return {
        "scope": EXAM408_ROOT_CODE,
        "syllabus_version": syllabus_service.active_summary(syllabus_version),
        "scope_ready": True,
        "subjects": summaries,
    }


async def get_subject_map(
    db: AsyncSession, user_id: int, subject_id: int
) -> dict | None:
    _root, core_subjects = await _load_core_subjects(db)
    subject_map = {int(subject.id): subject for subject in core_subjects}
    subject = subject_map.get(int(subject_id))
    if subject is None:
        return None

    syllabus_version, memberships = await syllabus_service.active_memberships(
        db, [int(subject.id)]
    )
    if syllabus_version is None:
        return None
    points = await _load_subject_points(db, subject.id, memberships, ordered=True)
    states = await _load_states(db, user_id, [int(subject.id)])
    trainable_counts = await _load_trainable_counts(db, [int(subject.id)])
    edges = await _load_parent_edges(db, subject.id)
    parent_map = _build_parent_map(points, edges)
    hierarchy_meta = _build_hierarchy_metadata(
        points, parent_map, states, trainable_counts
    )
    ordered = _ordered_tree_rows(points, parent_map, memberships)
    nodes = [
        _node_payload(
            point,
            state=states.get(int(point.id)),
            trainable_question_count=trainable_counts.get(int(point.id), 0),
            parent_id=parent_id,
            depth=depth,
            child_count=child_count,
            hierarchy_meta=hierarchy_meta.get(int(point.id)),
            syllabus_item=memberships.get(int(point.id)),
        )
        for point, depth, parent_id, child_count in ordered
    ]
    return {
        "scope": EXAM408_ROOT_CODE,
        "syllabus_version": syllabus_service.active_summary(syllabus_version),
        "subject": _build_subject_summary(subject, points, states, trainable_counts),
        "root_count": sum(1 for point in points if int(point.id) not in parent_map),
        "max_depth": max((int(node["depth"]) for node in nodes), default=0),
        "parented_knowledge_points": len(parent_map),
        "parent_coverage_ratio": round(len(parent_map) / len(points), 4)
        if points
        else 0.0,
        "nodes": nodes,
    }


async def _relation_payloads(
    db: AsyncSession,
    point: KnowledgePoint,
    memberships: dict[int, SyllabusKnowledgePoint],
) -> tuple[list[dict], list[dict], list[dict]]:
    rows = await _load_relation_edges(db, point)
    return _build_relation_payloads(rows, point, memberships)


async def get_point_detail(
    db: AsyncSession, user_id: int, knowledge_point_id: int
) -> dict | None:
    _root, core_subjects = await _load_core_subjects(db)
    core_map = {int(subject.id): subject for subject in core_subjects}
    point = await _load_point(db, knowledge_point_id)
    if point is None or int(point.subject_id) not in core_map:
        return None
    subject = core_map[int(point.subject_id)]
    syllabus_version, memberships = await syllabus_service.active_memberships(
        db, [int(subject.id)]
    )
    syllabus_item = memberships.get(int(point.id))
    if syllabus_version is None or syllabus_item is None:
        return None
    states = await _load_states(db, user_id, [int(subject.id)])
    trainable = await _load_trainable_counts(db, [int(subject.id)])
    tree_points = await _load_subject_points(db, subject.id, memberships)
    tree_edges = await _load_parent_edges(db, subject.id)
    parent_map = _build_parent_map(tree_points, tree_edges)
    hierarchy_meta = _build_hierarchy_metadata(
        tree_points, parent_map, states, trainable
    )
    state = states.get(int(point.id))
    node = _detail_node(
        point, states, trainable, parent_map, hierarchy_meta, syllabus_item
    )
    ancestors, direct_children = _detail_tree_labels(
        point, tree_points, parent_map, memberships, node
    )
    prerequisites, next_nodes, related_nodes = await _relation_payloads(
        db, point, memberships
    )
    result = _detail_payload(
        subject,
        point,
        node,
        state,
        syllabus_service.active_summary(syllabus_version),
        ancestors,
        direct_children,
    )
    result["recent_answers"] = await _recent_answers(db, user_id, int(point.id))
    result.update(
        prerequisites=prerequisites,
        next_nodes=next_nodes,
        related_nodes=related_nodes,
        practice_route_params=_practice_route_params(subject, point, node),
    )
    return result
