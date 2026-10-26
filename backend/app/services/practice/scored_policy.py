"""Compose ranked selection through caller-owned scoring and explanation ports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from logging import Logger

    from app.models.question import Question
    from app.services.practice.scored_context import ScoredLearningContext


@dataclass(slots=True)
class ScoredPolicyRequest:
    candidates: list[Question]
    learning: ScoredLearningContext
    runtime: dict
    graph_config: dict
    now: datetime
    count: int
    user_id: int
    metadata: dict[int, dict]
    logger: Logger
    rank_candidates: Callable
    select_candidates: Callable
    calculate_score: Callable
    build_metadata: Callable


@dataclass(slots=True)
class ScoredSelection:
    questions: list[Question]
    question_ids: set[int]
    relaxed_diversity: bool


def rank_and_select_candidates(request: ScoredPolicyRequest) -> ScoredSelection:
    learning = request.learning
    scored = request.rank_candidates(
        request.candidates,
        learning.q_state_map,
        learning.q_kp_map,
        learning.kp_mastery,
        learning.recent_kp_ids,
        request.now,
        kp_observations=learning.kp_observations,
        blocked_kps=learning.blocked_kps,
        graph_candidates=learning.graph_candidates,
        prerequisites_by_target=learning.prerequisites_by_target,
        weights=learning.rec_weights,
        graph_config=request.graph_config,
        calculate_score=request.calculate_score,
    )
    if scored:
        top = scored[:5]
        request.logger.info(
            "[smart_scored] top5 uid=%s: %s",
            request.user_id,
            [(q.id, round(s, 1), r) for q, s, r in top],
        )
    return _select_ranked_candidates(request, scored)


def _select_ranked_candidates(
    request: ScoredPolicyRequest,
    scored: list[tuple[Question, float, list[str]]],
) -> ScoredSelection:
    learning = request.learning

    def scored_metadata(score: float, reasons: list[str], kp_ids: list[int]) -> dict:
        return request.build_metadata(
            score,
            reasons,
            kp_ids,
            learning.kp_names,
            graph_candidates=learning.graph_candidates,
            blocked_kps=learning.blocked_kps,
            kp_mastery=learning.kp_mastery,
            kp_observations=learning.kp_observations,
            strategy_config_id=request.runtime.get("strategy_config_id"),
        )

    selected, selected_ids, relaxed = request.select_candidates(
        scored,
        request.count,
        learning.q_kp_map,
        request.metadata,
        scored_metadata,
    )
    return ScoredSelection(selected, selected_ids, relaxed)
