"""Rank scored practice candidates without database or metadata ownership."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from app.models.question import Question


def score_and_rank_candidates(
    questions: list[Question],
    q_state_map: dict[int, object],
    q_kp_map: dict[int, list[int]],
    kp_mastery: dict[int, tuple],
    recent_kp_ids: set[int],
    now: datetime,
    *,
    kp_observations: dict[int, tuple[int, int]],
    blocked_kps: dict,
    graph_candidates: dict,
    prerequisites_by_target: dict,
    weights: dict[str, float],
    graph_config: dict,
    calculate_score: Callable[..., tuple[float, list[str]]],
) -> list[tuple[Question, float, list[str]]]:
    """Score candidates in order and sort by score descending, stable on ties."""
    scored: list[tuple[Question, float, list[str]]] = []
    for question in questions:
        score, reasons = calculate_score(
            question,
            q_state_map.get(question.id),
            q_kp_map.get(question.id, []),
            kp_mastery,
            recent_kp_ids,
            now,
            kp_observations=kp_observations,
            blocked_kps=blocked_kps,
            graph_candidates=graph_candidates,
            prerequisites_by_target=prerequisites_by_target,
            weights=weights,
            graph_config=graph_config,
        )
        scored.append((question, score, reasons))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored
