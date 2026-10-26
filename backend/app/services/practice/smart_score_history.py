"""Score review timing, answer history and knowledge coverage without IO."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime


def score_due_review(q_state, now: datetime) -> tuple[float, list[str]]:
    total = 0.0
    reasons: list[str] = []
    if q_state and q_state.next_review_at and q_state.next_review_at <= now:
        total += 40
        reasons.append("due_review")
        overdue_days = (now - q_state.next_review_at).days
        overdue_score = min(overdue_days * 2, 20)
        total += overdue_score
        if overdue_score > 0:
            reasons.append(f"overdue_{overdue_days}d")
    return total, reasons


def score_weakness(
    kp_ids: list[int],
    kp_mastery: dict[int, tuple],
    kp_observations: dict[int, tuple[int, int]],
    observed_weak_ids: Callable,
) -> tuple[float, list[str]]:
    total = 0.0
    reasons: list[str] = []
    if kp_ids:
        total_ws = 0.0
        cnt = 0
        for kid in kp_ids:
            ms, conf = kp_mastery.get(kid, (50.0, 0.0))
            total_ws += (100 - ms) * conf * 0.4
            cnt += 1
        if cnt:
            ws = total_ws / cnt
            total += ws
            if ws >= 15:
                reasons.append("weak_kp")
            elif observed_weak_ids(kp_ids, kp_mastery, kp_observations):
                total += 12.0
                reasons.append("observed_weak")
    return total, reasons


def score_answer_history(q_state) -> tuple[float, float, list[str]]:
    wrong_total = 0.0
    new_total = 0.0
    reasons: list[str] = []
    if q_state:
        wrong_total += min(q_state.wrong_count * 8, 30)
        if q_state.wrong_count > 0:
            reasons.append("wrong_history")
    if not q_state or q_state.answer_count == 0:
        new_total += 20
        reasons.append("new_question")
    return wrong_total, new_total, reasons


def score_coverage(
    q_state,
    now: datetime,
    kp_ids: list[int],
    recent_kp_ids: set[int],
) -> tuple[float, list[str]]:
    total = 0.0
    reasons: list[str] = []
    if q_state and q_state.last_answered_at:
        days_since = (now - q_state.last_answered_at).days
        if days_since >= 30:
            total += min(days_since * 0.5, 15)
            reasons.append("long_unpracticed")
    if kp_ids and not set(kp_ids) & recent_kp_ids:
        total += 10
        reasons.append("diversity")
    return total, reasons


def combine_score_groups(
    totals: tuple[float, float, float, float, float, float],
    weights: dict[str, float] | None,
) -> float:
    due, weakness, wrong, new, diversity, path = totals
    # Keep the original addition order; tiny float changes can affect ranking ties.
    if weights:
        return (
            due * weights.get("due_weight", 1.0)
            + weakness * weights.get("weakness_weight", 1.0)
            + wrong * weights.get("wrong_weight", 1.0)
            + new * weights.get("new_question_weight", 1.0)
            + diversity * weights.get("diversity_weight", 1.0)
            + path * weights.get("path_weight", 1.0)
        )
    return due + weakness + wrong + new + diversity + path
