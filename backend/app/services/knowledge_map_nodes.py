"""Knowledge-map node identity, hierarchy and observation projection."""

from __future__ import annotations

from app.core.time_utils import serialize_utc_datetime
from app.models.knowledge_point import KnowledgePoint
from app.models.syllabus import SyllabusKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState
from app.services.knowledge_map_summary import _state_status


def _node_identity(
    point: KnowledgePoint, syllabus_item: SyllabusKnowledgePoint | None
) -> dict:
    display_name = (
        str(syllabus_item.name_snapshot)
        if syllabus_item is not None
        else str(point.name)
    )
    aliases = (
        [
            str(alias).strip()
            for alias in (point.aliases or [])
            if alias is not None and str(alias).strip()
        ]
        if isinstance(point.aliases, (list, tuple))
        else []
    )
    description = (
        syllabus_item.description_snapshot
        if syllabus_item is not None
        else point.description
    )
    difficulty_level = (
        int(syllabus_item.difficulty_level_snapshot or 3)
        if syllabus_item is not None
        else int(point.difficulty_level or 3)
    )
    return {
        "knowledge_point_id": int(point.id),
        "name": display_name,
        "aliases": aliases,
        "description": description,
        "difficulty_level": difficulty_level,
    }


def _node_hierarchy(
    hierarchy_meta: dict | None,
    child_count: int,
    parent_id: int | None,
    depth: int,
    trainable_question_count: int,
) -> dict:
    meta = hierarchy_meta or {}
    direct_child_count = int(meta.get("direct_child_count", child_count) or 0)
    return {
        "parent_id": parent_id,
        "depth": depth,
        "child_count": direct_child_count,
        "direct_child_count": direct_child_count,
        "has_children": bool(meta.get("has_children", direct_child_count > 0)),
        "is_leaf": bool(meta.get("is_leaf", direct_child_count <= 0)),
        "descendant_count": int(meta.get("descendant_count", direct_child_count) or 0),
        "ancestor_ids": list(meta.get("ancestor_ids", [])),
        "trainable_question_count": int(trainable_question_count or 0),
        "subtree_total_knowledge_points": int(
            meta.get("subtree_total_knowledge_points", 1) or 1
        ),
        "subtree_trainable_knowledge_points": int(
            meta.get("subtree_trainable_knowledge_points", 0) or 0
        ),
        "subtree_observed_knowledge_points": int(
            meta.get("subtree_observed_knowledge_points", 0) or 0
        ),
        "subtree_reliable_knowledge_points": int(
            meta.get("subtree_reliable_knowledge_points", 0) or 0
        ),
        "subtree_weak_knowledge_points": int(
            meta.get("subtree_weak_knowledge_points", 0) or 0
        ),
        "subtree_coverage_ratio": float(meta.get("subtree_coverage_ratio", 0.0) or 0.0),
        "subtree_status": str(meta.get("subtree_status", "no_data")),
        "subtree_mastery_score": meta.get("subtree_mastery_score"),
        "subtree_confidence": float(meta.get("subtree_confidence", 0.0) or 0.0),
    }


def _node_payload(
    point: KnowledgePoint,
    *,
    state: UserKnowledgeState | None,
    trainable_question_count: int,
    parent_id: int | None,
    depth: int,
    child_count: int,
    hierarchy_meta: dict | None = None,
    syllabus_item: SyllabusKnowledgePoint | None = None,
) -> dict:
    attempts = int(state.attempt_count or 0) if state else 0
    correct = int(state.correct_count or 0) if state else 0
    wrong = int(state.wrong_count or 0) if state else 0
    mastery = (
        float(state.mastery_score)
        if state and state.mastery_score is not None
        else None
    )
    confidence = float(state.confidence or 0.0) if state else 0.0
    status = _state_status(attempts=attempts, mastery=mastery, confidence=confidence)
    return {
        **_node_identity(point, syllabus_item),
        **_node_hierarchy(
            hierarchy_meta, child_count, parent_id, depth, trainable_question_count
        ),
        "status": status,
        "mastery_score": round(mastery, 1)
        if status not in {"no_data", "insufficient"} and mastery is not None
        else None,
        "confidence": round(confidence, 3),
        "attempt_count": attempts,
        "correct_count": correct,
        "wrong_count": wrong,
        "accuracy": round(correct / attempts, 4) if attempts > 0 else None,
        "recent_wrong_count": int(state.recent_wrong_count or 0) if state else 0,
        "last_practiced_at": serialize_utc_datetime(state.last_practiced_at)
        if state and state.last_practiced_at
        else None,
    }
