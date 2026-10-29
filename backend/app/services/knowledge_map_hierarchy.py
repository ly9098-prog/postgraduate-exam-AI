"""Read-only subtree coverage and mastery metadata."""

from __future__ import annotations

from collections import defaultdict

from app.models.knowledge_point import KnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState
from app.services.knowledge_map_summary import (
    _MIN_RELIABLE_CONFIDENCE,
    _WEAK_THRESHOLD,
    _state_status,
)


def _subtree_observations(
    subtree: tuple[int, ...], states: dict[int, UserKnowledgeState]
) -> tuple[list[int], list[int], list[int]]:
    observed_ids: list[int] = []
    reliable_ids: list[int] = []
    weak_ids: list[int] = []
    for node_id in subtree:
        state = states.get(node_id)
        if state is None or int(state.attempt_count or 0) <= 0:
            continue
        observed_ids.append(node_id)
        confidence = float(state.confidence or 0.0)
        mastery = state.mastery_score
        if confidence < _MIN_RELIABLE_CONFIDENCE or mastery is None:
            continue
        reliable_ids.append(node_id)
        if float(mastery) < _WEAK_THRESHOLD:
            weak_ids.append(node_id)

    return observed_ids, reliable_ids, weak_ids


def _subtree_mastery(
    trainable_ids: list[int],
    reliable_ids: list[int],
    reliable_trainable_ids: list[int],
    observed_ids: list[int],
    states: dict[int, UserKnowledgeState],
    trainable_counts: dict[int, int],
) -> tuple[str, float | None, float]:
    required_reliable = min(3, len(trainable_ids)) if trainable_ids else 0
    subtree_status = "no_data" if not observed_ids else "insufficient"
    subtree_mastery: float | None = None
    subtree_confidence = 0.0

    aggregation_ids = reliable_trainable_ids if trainable_ids else reliable_ids
    if aggregation_ids and len(aggregation_ids) >= max(1, required_reliable):
        weighted_rows: list[tuple[float, float]] = []
        for node_id in aggregation_ids:
            state = states[node_id]
            confidence = float(state.confidence or 0.0)
            question_weight = max(1, int(trainable_counts.get(node_id, 0)))
            weight = confidence * question_weight
            weighted_rows.append((float(state.mastery_score), weight))
        total_weight = sum(weight for _mastery, weight in weighted_rows)
        if total_weight > 0:
            subtree_mastery = (
                sum(mastery * weight for mastery, weight in weighted_rows)
                / total_weight
            )
            subtree_confidence = sum(
                float(states[node_id].confidence or 0.0) for node_id in aggregation_ids
            ) / len(aggregation_ids)
            subtree_status = _state_status(
                attempts=sum(
                    int(states[node_id].attempt_count or 0) for node_id in observed_ids
                ),
                mastery=subtree_mastery,
                confidence=max(subtree_confidence, _MIN_RELIABLE_CONFIDENCE),
            )

    return subtree_status, subtree_mastery, subtree_confidence


def _subtree_metadata(
    subtree: tuple[int, ...],
    children: list[int],
    ancestors: list[int],
    states: dict[int, UserKnowledgeState],
    trainable_counts: dict[int, int],
) -> dict:
    observed_ids, reliable_ids, weak_ids = _subtree_observations(subtree, states)
    trainable_ids = [
        node_id for node_id in subtree if trainable_counts.get(node_id, 0) > 0
    ]
    trainable_set = set(trainable_ids)
    reliable_trainable_ids = [
        node_id for node_id in reliable_ids if node_id in trainable_set
    ]
    subtree_status, subtree_mastery, subtree_confidence = _subtree_mastery(
        trainable_ids,
        reliable_ids,
        reliable_trainable_ids,
        observed_ids,
        states,
        trainable_counts,
    )

    return {
        "ancestor_ids": ancestors,
        "descendant_count": max(0, len(subtree) - 1),
        "direct_child_count": len(children),
        "has_children": bool(children),
        "is_leaf": not bool(children),
        "subtree_total_knowledge_points": len(subtree),
        "subtree_trainable_knowledge_points": len(trainable_ids),
        "subtree_observed_knowledge_points": len(observed_ids),
        "subtree_reliable_knowledge_points": len(reliable_ids),
        "subtree_weak_knowledge_points": len(weak_ids),
        "subtree_coverage_ratio": round(
            len(reliable_trainable_ids) / len(trainable_ids), 4
        )
        if trainable_ids
        else 0.0,
        "subtree_status": subtree_status,
        "subtree_mastery_score": round(subtree_mastery, 1)
        if subtree_mastery is not None
        else None,
        "subtree_confidence": round(subtree_confidence, 3),
    }


def _build_hierarchy_metadata(
    points: list[KnowledgePoint],
    parent_map: dict[int, int],
    states: dict[int, UserKnowledgeState],
    trainable_counts: dict[int, int],
) -> dict[int, dict]:
    point_ids = {int(point.id) for point in points}
    children: dict[int, list[int]] = defaultdict(list)
    for child_id, parent_id in parent_map.items():
        if child_id in point_ids and parent_id in point_ids:
            children[parent_id].append(child_id)

    subtree_cache: dict[int, tuple[int, ...]] = {}

    def subtree_ids(kp_id: int) -> tuple[int, ...]:
        cached = subtree_cache.get(kp_id)
        if cached is not None:
            return cached
        collected = [kp_id]
        for child_id in children.get(kp_id, []):
            collected.extend(subtree_ids(child_id))
        result = tuple(dict.fromkeys(collected))
        subtree_cache[kp_id] = result
        return result

    def ancestor_ids(kp_id: int) -> list[int]:
        chain: list[int] = []
        cursor = parent_map.get(kp_id)
        seen: set[int] = set()
        while cursor is not None and cursor not in seen:
            seen.add(cursor)
            chain.append(cursor)
            cursor = parent_map.get(cursor)
        chain.reverse()
        return chain

    metadata: dict[int, dict] = {}
    for point in points:
        kp_id = int(point.id)
        subtree = subtree_ids(kp_id)
        metadata[kp_id] = _subtree_metadata(
            subtree,
            children.get(kp_id, []),
            ancestor_ids(kp_id),
            states,
            trainable_counts,
        )
    return metadata
