"""Candidate and context loading for the V4 smart-scored entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.question import Question


@dataclass(slots=True)
class ScoredCandidateContext:
    candidates: list[Question]
    active_candidate_conditions: list
    scope_ids: list[int]
    excluded_sub: Any
    fallback_level: int
    subject_condition: Any


@dataclass(slots=True)
class ScoredLearningContext:
    kp_mastery: dict
    kp_observations: dict
    graph_context: dict
    q_state_map: dict[int, object]
    recent_kp_ids: set[int]
    q_kp_map: dict[int, list[int]]
    blocked_kps: dict
    graph_candidates: dict
    prerequisites_by_target: dict
    kp_names: dict[int, str]
    rec_weights: dict[str, float]


async def load_scored_candidate_context(
    *,
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    subject_ids: list[int] | None,
    count: int,
    exclude_answered: bool,
    no_repeat_days: int | None,
    now: datetime,
    load_runtime: Any,
    load_candidates: Any,
    build_subject_condition: Any,
) -> tuple[dict, ScoredCandidateContext | None]:
    scored_runtime = await load_runtime(db)
    candidate_limit = max(count * 5, 50)
    (
        candidates,
        active_candidate_conditions,
        scope_ids,
        excluded_sub,
        fallback_level,
    ) = await load_candidates(
        db,
        user_id,
        subject_code,
        subject_ids,
        candidate_limit,
        exclude_answered,
        no_repeat_days,
        count,
        now,
    )
    context = ScoredCandidateContext(
        candidates=candidates,
        active_candidate_conditions=active_candidate_conditions,
        scope_ids=scope_ids,
        excluded_sub=excluded_sub,
        fallback_level=fallback_level,
        subject_condition=build_subject_condition(scope_ids),
    )
    return scored_runtime, context


async def load_scored_learning_context(
    *,
    db: AsyncSession,
    user_id: int,
    candidates: list[Question],
    active_candidate_conditions: list,
    scope_ids: list[int],
    graph_runtime: dict,
    count: int,
    system_weights: dict,
    load_knowledge_graph: Any,
    load_candidate_states: Any,
    extract_graph_context: Any,
    load_kp_names: Any,
    compute_weights: Any,
) -> ScoredLearningContext:
    kp_mastery, kp_observations, graph_context = await load_knowledge_graph(
        db,
        user_id,
        scope_ids,
        candidates,
        active_candidate_conditions,
        graph_runtime,
        count,
    )
    cand_ids = {q.id for q in candidates}
    q_state_map, recent_kp_ids, q_kp_map = await load_candidate_states(
        db,
        user_id,
        cand_ids,
        scope_ids,
    )
    blocked_kps, graph_candidates, prerequisites_by_target = extract_graph_context(
        graph_context
    )
    return ScoredLearningContext(
        kp_mastery=kp_mastery,
        kp_observations=kp_observations,
        graph_context=graph_context,
        q_state_map=q_state_map,
        recent_kp_ids=recent_kp_ids,
        q_kp_map=q_kp_map,
        blocked_kps=blocked_kps,
        graph_candidates=graph_candidates,
        prerequisites_by_target=prerequisites_by_target,
        kp_names=await load_kp_names(db, q_kp_map, scope_ids),
        rec_weights=await compute_weights(db, user_id, system_weights),
    )
