"""Pure score features for the retained weakness-vector reranker."""

from __future__ import annotations

from typing import Any


def build_strategy_base_scores(
    question: Any,
    question_kps: list[str],
    metadata: dict[int, dict],
    weak_names: set[str],
    name_to_id: dict[str, int],
    mastery_by_kp: dict[int, float],
    target_difficulty: int | None,
) -> dict:
    overlap = len(set(question_kps) & weak_names) / max(1, len(question_kps))
    gaps = []
    for name in question_kps:
        kp_id = name_to_id.get(name)
        mastery = mastery_by_kp.get(kp_id) if kp_id is not None else None
        gaps.append((100.0 - mastery) / 100.0 if mastery is not None else 0.5)
    mastery_gap = sum(gaps) / len(gaps) if gaps else 0.5
    if target_difficulty is None:
        difficulty_match = 1.0
    else:
        difficulty_match = 1.0 - min(
            1.0,
            abs((question.difficulty or 3) - target_difficulty) / 4.0,
        )
    return {
        "vector_similarity": (metadata.get(question.id) or {}).get("similarity") or 0.0,
        "knowledge_overlap": overlap,
        "difficulty_match": difficulty_match,
        "mastery_gap": mastery_gap,
        "path_priority": 0.0,
    }
