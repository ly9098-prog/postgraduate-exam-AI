"""Canonical knowledge-map status and subject aggregation."""

from __future__ import annotations

from app.models.admin import Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState

_MIN_RELIABLE_CONFIDENCE = 0.30
_WEAK_THRESHOLD = 40.0
_GOOD_THRESHOLD = 70.0
_MASTERED_THRESHOLD = 85.0


def _state_status(*, attempts: int, mastery: float | None, confidence: float) -> str:
    if attempts <= 0:
        return "no_data"
    if confidence < _MIN_RELIABLE_CONFIDENCE or mastery is None:
        return "insufficient"
    if mastery < _WEAK_THRESHOLD:
        return "weak"
    if mastery < _GOOD_THRESHOLD:
        return "developing"
    if mastery < _MASTERED_THRESHOLD:
        return "good"
    return "mastered"


def _subject_mastery(
    observed: list[UserKnowledgeState],
    reliable: list[UserKnowledgeState],
    required_reliable: int,
    attempt_count: int,
) -> tuple[float | None, float, str]:
    mastery_score: float | None = None
    confidence = 0.0
    status = "no_data"
    if observed:
        status = "insufficient"
    if reliable and len(reliable) >= max(1, required_reliable):
        total_weight = sum(float(state.confidence or 0.0) for state in reliable)
        if total_weight > 0:
            mastery_score = (
                sum(
                    float(
                        state.mastery_score if state.mastery_score is not None else 50.0
                    )
                    * float(state.confidence or 0.0)
                    for state in reliable
                )
                / total_weight
            )
            confidence = sum(
                float(state.confidence or 0.0) for state in reliable
            ) / len(reliable)
            status = _state_status(
                attempts=attempt_count,
                mastery=mastery_score,
                confidence=max(confidence, _MIN_RELIABLE_CONFIDENCE),
            )

    return mastery_score, confidence, status


def _subject_observations(
    point_ids: list[int], states: dict[int, UserKnowledgeState]
) -> tuple[list[UserKnowledgeState], list[UserKnowledgeState]]:
    subject_states = [states[kp_id] for kp_id in point_ids if kp_id in states]
    observed = [state for state in subject_states if int(state.attempt_count or 0) > 0]
    reliable = [
        state
        for state in observed
        if float(state.confidence or 0.0) >= _MIN_RELIABLE_CONFIDENCE
    ]
    return observed, reliable


def _build_subject_summary(
    subject: Subject,
    points: list[KnowledgePoint],
    states: dict[int, UserKnowledgeState],
    trainable_counts: dict[int, int],
) -> dict:
    point_ids = [int(point.id) for point in points]
    observed, reliable = _subject_observations(point_ids, states)
    trainable_count = sum(
        1 for kp_id in point_ids if trainable_counts.get(kp_id, 0) > 0
    )
    required_reliable = min(3, trainable_count) if trainable_count > 0 else 0

    attempt_count = sum(int(state.attempt_count or 0) for state in observed)
    correct_count = sum(int(state.correct_count or 0) for state in observed)
    weak_count = sum(
        1
        for state in reliable
        if float(state.mastery_score if state.mastery_score is not None else 50.0)
        < _WEAK_THRESHOLD
    )

    mastery_score, confidence, status = _subject_mastery(
        observed, reliable, required_reliable, attempt_count
    )

    total_points = len(points)
    coverage_ratio = len(reliable) / trainable_count if trainable_count > 0 else 0.0
    return {
        "subject_id": int(subject.id),
        "subject_code": str(subject.code),
        "subject_name": str(subject.name),
        "status": status,
        "mastery_score": round(mastery_score, 1) if mastery_score is not None else None,
        "confidence": round(confidence, 3),
        "total_knowledge_points": total_points,
        "trainable_knowledge_points": trainable_count,
        "observed_knowledge_points": len(observed),
        "reliable_knowledge_points": len(reliable),
        "weak_knowledge_points": weak_count,
        "attempt_count": attempt_count,
        "correct_count": correct_count,
        "accuracy": round(correct_count / attempt_count, 4)
        if attempt_count > 0
        else None,
        "coverage_ratio": round(coverage_ratio, 4),
    }
