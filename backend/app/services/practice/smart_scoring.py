"""Pure scoring and explanation primitives for smart practice recommendations.

Kept free of database access so scoring policy can be unit-tested independently
of candidate recall, vector search and fallback orchestration.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.services.practice.smart_reason_text import (
    blocked_target_reason,
    coverage_reason,
    first_kp_name,
    graph_prerequisite_reason,
    observed_weakness_reason,
    weak_knowledge_reason,
)
from app.services.practice.smart_score_history import (
    combine_score_groups,
    score_answer_history,
    score_coverage,
    score_due_review,
    score_weakness,
)
from app.services.practice.smart_score_path import (
    prerequisite_thresholds,
    score_prerequisite_path,
)

if TYPE_CHECKING:
    from app.models.question import Question
else:
    Question = Any


def _pick_graph_target_kps(
    kp_mastery: dict[int, tuple],
    *,
    limit: int = 5,
) -> list[int]:
    """Pick high-value weak KPs whose prerequisites are worth expanding.

    Low-confidence states are not treated as confirmed weakness.  This keeps
    the graph from turning an unobserved prerequisite into a hard learning
    detour while still allowing the graph helper to add a small diagnostic
    candidate for unknown *prerequisites* of a genuinely weak target.
    """
    ranked: list[tuple[int, float]] = []
    for kp_id, (mastery, confidence) in kp_mastery.items():
        mastery_value = 50.0 if mastery is None else mastery
        confidence_value = 0.0 if confidence is None else confidence
        mastery = max(0.0, min(float(mastery_value), 100.0))
        confidence = max(0.0, min(float(confidence_value), 1.0))
        if confidence < 0.3 or mastery >= 70.0:
            continue
        weakness = ((100.0 - mastery) / 100.0) * confidence
        ranked.append((kp_id, weakness))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [kp_id for kp_id, _score in ranked[:limit]]


def _get_observed_weak_kp_ids(
    kp_ids: list[int],
    kp_mastery: dict[int, tuple],
    kp_observations: dict[int, tuple[int, int]] | None = None,
) -> list[int]:
    """Return KPs with an early but meaningful weak-performance signal.

    This is intentionally weaker than ``weak_kp``: two or more attempts with
    at least two wrong answers and mastery <= 40 are enough to say that recent
    performance needs more validation, but not enough to declare a confirmed
    weakness. ``calculate_smart_score`` only emits this signal when the
    existing confirmed-weakness threshold has not been reached.
    """
    kp_observations = kp_observations or {}
    observed: list[int] = []
    for kp_id in kp_ids:
        mastery, _confidence = kp_mastery.get(kp_id, (50.0, 0.0))
        attempt_count, wrong_count = kp_observations.get(kp_id, (0, 0))
        mastery_value = 50.0 if mastery is None else float(mastery)
        if (
            int(attempt_count or 0) >= 2
            and int(wrong_count or 0) >= 2
            and mastery_value <= 40.0
        ):
            observed.append(kp_id)
    return observed


def _build_smart_recommendation_reason(
    reason_codes: list[str],
    kp_ids: list[int],
    kp_names: dict[int, str],
    graph_candidates: dict[int, dict] | None = None,
    blocked_kps: dict[int, list[dict]] | None = None,
    kp_mastery: dict[int, tuple] | None = None,
    kp_observations: dict[int, tuple[int, int]] | None = None,
) -> str:
    """Convert internal score reason codes into a concise combined Chinese reason.

    The explanation keeps the strongest recommendation signal as the main
    reason, then appends at most one useful secondary signal.  In particular,
    ``new_question`` is treated as supporting context instead of masking a more
    meaningful reason such as weak knowledge, review due, or wrong history.
    """
    graph_candidates = graph_candidates or {}
    blocked_kps = blocked_kps or {}
    kp_mastery = kp_mastery or {}
    kp_observations = kp_observations or {}
    reason_set = set(reason_codes)
    is_new = "new_question" in reason_set
    is_diverse = "diversity" in reason_set
    is_long_unpracticed = "long_unpracticed" in reason_set
    has_wrong_history = "wrong_history" in reason_set

    graph_reason = graph_prerequisite_reason(kp_ids, kp_names, graph_candidates, is_new)
    if graph_reason is not None:
        return graph_reason
    if "due_review" in reason_set:
        if has_wrong_history:
            return "这道题已进入复习窗口，而且你之前在这类题目上出现过错误，现在重做有助于巩固记忆并确认是否已经掌握。"
        return "这道题已进入复习窗口，现在练习有助于巩固记忆。"
    if "weak_kp" in reason_set:
        return weak_knowledge_reason(first_kp_name(kp_ids, kp_names), is_new, has_wrong_history)
    if "observed_weak" in reason_set:
        observed_ids = _get_observed_weak_kp_ids(kp_ids, kp_mastery, kp_observations)
        name = first_kp_name(observed_ids, kp_names) or first_kp_name(kp_ids, kp_names)
        return observed_weakness_reason(name, is_new, has_wrong_history)
    if has_wrong_history:
        if is_long_unpracticed:
            return "你之前在这类题目上出现过错误，而且已有一段时间没有练习，建议现在重做确认是否已经掌握。"
        return "你之前在这类题目上出现过错误，建议再次练习确认是否已经掌握。"
    blocked_reason = blocked_target_reason(kp_ids, kp_names, blocked_kps, is_new)
    if blocked_reason is not None:
        return blocked_reason
    return coverage_reason(
        kp_ids, kp_names, path_ready="path_ready" in reason_set, is_new=is_new,
        is_diverse=is_diverse, is_long_unpracticed=is_long_unpracticed,
    )


def calculate_smart_score(
    question: Question,
    q_state,  # UserQuestionState | None
    kp_ids: list[int],
    kp_mastery: dict[int, tuple],  # kp_id -> (mastery_score, confidence)
    recent_kp_ids: set[int],
    now: datetime,
    kp_observations: dict[int, tuple[int, int]]
    | None = None,  # kp_id -> (attempt_count, wrong_count)
    blocked_kps: dict[int, list[dict]] | None = None,  # V6.3: kp_id -> [weak prereqs]
    graph_candidates: dict[int, dict] | None = None,  # V6.5: prereq kp -> graph context
    prerequisites_by_target: dict[int, list[dict]] | None = None,
    weights: dict[str, float] | None = None,  # 系统级 × 用户级综合权重
    graph_config: dict | None = None,
) -> tuple[float, list[str]]:
    """Combine review, learning history, coverage and graph score groups in order."""
    graph_config = graph_config or {}
    kp_observations = kp_observations or {}
    thresholds = prerequisite_thresholds(graph_config)
    due, due_reasons = score_due_review(q_state, now)
    weakness, weak_reasons = score_weakness(
        kp_ids, kp_mastery, kp_observations, _get_observed_weak_kp_ids,
    )
    wrong, new, history_reasons = score_answer_history(q_state)
    diversity, coverage_reasons = score_coverage(q_state, now, kp_ids, recent_kp_ids)
    path, path_reasons = score_prerequisite_path(
        kp_ids, blocked_kps, graph_candidates, prerequisites_by_target, thresholds,
    )
    score = combine_score_groups((due, weakness, wrong, new, diversity, path), weights)
    return score, due_reasons + weak_reasons + history_reasons + coverage_reasons + path_reasons
