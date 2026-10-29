"""Knowledge-map detail labels and response projection."""

from __future__ import annotations

from app.core.subject_scope import EXAM408_ROOT_CODE
from app.core.time_utils import serialize_utc_datetime
from app.models.admin import Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.syllabus import SyllabusKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState


def _detail_tree_labels(
    point: KnowledgePoint,
    tree_points: list[KnowledgePoint],
    parent_map: dict[int, int],
    memberships: dict[int, SyllabusKnowledgePoint],
    node: dict,
) -> tuple[list[dict], list[dict]]:
    by_id = {int(item.id): item for item in tree_points}
    child_ids = sorted(
        [
            child_id
            for child_id, parent_id in parent_map.items()
            if parent_id == int(point.id)
        ],
        key=lambda child_id: (
            int(memberships[child_id].sort_order or 0)
            if child_id in memberships
            else 0,
            str(memberships[child_id].name_snapshot)
            if child_id in memberships
            else str(by_id[child_id].name),
            child_id,
        ),
    )
    ancestors = [
        {
            "knowledge_point_id": ancestor_id,
            "name": str(memberships[ancestor_id].name_snapshot)
            if ancestor_id in memberships
            else str(by_id[ancestor_id].name),
            "depth": depth,
        }
        for depth, ancestor_id in enumerate(node.get("ancestor_ids", []))
        if ancestor_id in by_id
    ]
    direct_children = [
        {
            "knowledge_point_id": child_id,
            "name": str(memberships[child_id].name_snapshot)
            if child_id in memberships
            else str(by_id[child_id].name),
            "depth": int(node["depth"]) + 1,
        }
        for child_id in child_ids
        if child_id in by_id
    ]
    return ancestors, direct_children


def _detail_hierarchy_fields(
    node: dict, ancestors: list[dict], direct_children: list[dict]
) -> dict:
    return {
        "trainable_question_count": node["trainable_question_count"],
        "parent_id": node["parent_id"],
        "ancestors": ancestors,
        "direct_children": direct_children,
        "descendant_count": node["descendant_count"],
        "subtree_total_knowledge_points": node["subtree_total_knowledge_points"],
        "subtree_trainable_knowledge_points": node[
            "subtree_trainable_knowledge_points"
        ],
        "subtree_observed_knowledge_points": node["subtree_observed_knowledge_points"],
        "subtree_reliable_knowledge_points": node["subtree_reliable_knowledge_points"],
        "subtree_weak_knowledge_points": node["subtree_weak_knowledge_points"],
        "subtree_coverage_ratio": node["subtree_coverage_ratio"],
        "subtree_status": node["subtree_status"],
        "subtree_mastery_score": node["subtree_mastery_score"],
        "subtree_confidence": node["subtree_confidence"],
    }


def _detail_payload(
    subject: Subject,
    point: KnowledgePoint,
    node: dict,
    state: UserKnowledgeState | None,
    syllabus_summary: dict | None,
    ancestors: list[dict],
    direct_children: list[dict],
) -> dict:
    return {
        "scope": EXAM408_ROOT_CODE,
        "syllabus_version": syllabus_summary,
        "subject_id": int(subject.id),
        "subject_code": str(subject.code),
        "subject_name": str(subject.name),
        "knowledge_point_id": int(point.id),
        "name": node["name"],
        "description": node["description"],
        "difficulty_level": node["difficulty_level"],
        "status": node["status"],
        "mastery_score": node["mastery_score"],
        "confidence": node["confidence"],
        "attempt_count": node["attempt_count"],
        "correct_count": node["correct_count"],
        "wrong_count": node["wrong_count"],
        "accuracy": node["accuracy"],
        "recent_wrong_count": node["recent_wrong_count"],
        "last_practiced_at": node["last_practiced_at"],
        "last_wrong_at": serialize_utc_datetime(state.last_wrong_at)
        if state and state.last_wrong_at
        else None,
        **_detail_hierarchy_fields(node, ancestors, direct_children),
    }


def _practice_route_params(subject: Subject, point: KnowledgePoint, node: dict) -> dict:
    return (
        {
            "subject_id": int(subject.id),
            "mode": "random",
            "count": (
                10
                if int(node["direct_child_count"] or 0) > 0
                else min(10, max(1, int(node["trainable_question_count"] or 0)))
            ),
            "knowledge_point": node["name"],
            "knowledge_point_id": int(point.id),
            "include_descendants": 1 if int(node["direct_child_count"] or 0) > 0 else 0,
            "allow_repeat": 1,
            "autostart": 1,
            "source": "knowledge_map",
        }
        if (
            int(node["subtree_trainable_knowledge_points"] or 0) > 0
            if int(node["direct_child_count"] or 0) > 0
            else int(node["trainable_question_count"] or 0) > 0
        )
        else {}
    )
