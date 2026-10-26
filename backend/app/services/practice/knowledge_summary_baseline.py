"""Pure issue-time snapshot projection for the signed knowledge context."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def issue_scope_ids(scope: dict) -> tuple[int, list[int]]:
    root_id = int(scope["root_id"])
    ids = list(
        dict.fromkeys(
            int(value)
            for value in scope.get("knowledge_point_ids") or []
            if int(value) > 0
        )
    )
    return root_id, ids


def _compact_point_baseline(state: Any, knowledge_point_id: int) -> list:
    attempts = int(state.attempt_count or 0) if state is not None else 0
    mastery = (
        round(float(state.mastery_score), 2)
        if state is not None and attempts > 0 and state.mastery_score is not None
        else None
    )
    confidence = round(float(state.confidence or 0.0), 4) if state is not None else 0.0
    return [int(knowledge_point_id), mastery, confidence, attempts]


def _root_baseline(detail: dict | None, scope: dict) -> list | None:
    if detail is None:
        return None
    descendants = bool(scope.get("include_descendants"))
    reliable = (
        int(detail.get("subtree_reliable_knowledge_points", 0) or 0)
        if descendants
        else (1 if detail.get("status") not in {"no_data", "insufficient"} else 0)
    )
    weak = (
        int(detail.get("subtree_weak_knowledge_points", 0) or 0)
        if descendants
        else (1 if detail.get("status") == "weak" else 0)
    )
    trainable = (
        int(detail.get("subtree_trainable_knowledge_points", 0) or 0)
        if descendants
        else (1 if int(detail.get("trainable_question_count", 0) or 0) > 0 else 0)
    )
    return [
        detail.get("subtree_mastery_score")
        if descendants
        else detail.get("mastery_score"),
        detail.get("subtree_coverage_ratio", 0.0)
        if descendants
        else (1.0 if reliable else 0.0),
        weak,
        reliable,
        trainable,
    ]


def signed_knowledge_context(
    scope: dict,
    root_id: int,
    scope_ids: list[int],
    served_ids: list[int],
    touched_ids: list[int],
    states: dict,
    root_detail: dict | None,
    practice_subject_id: int | None,
    version: int,
    compact_point: Callable,
) -> dict:
    root_baseline = _root_baseline(root_detail, scope)
    return {
        "v": version,
        "practice_mode": (
            "knowledge_chapter"
            if bool(scope.get("include_descendants"))
            else "knowledge_point"
        ),
        "root_id": root_id,
        "root_name": str(scope.get("root_name") or ""),
        # The issuing subject can be an aggregate parent of the KP's own subject.
        "subject_id": int(practice_subject_id or scope.get("subject_id") or 0) or None,
        "syllabus_version_id": int(scope.get("syllabus_version_id") or 0) or None,
        # Signed IDs preserve the issue-time tree without resolving it again on submit.
        "scope_ids": scope_ids,
        "served_ids": served_ids,
        "include_descendants": bool(scope.get("include_descendants")),
        "scope_count": len(scope_ids),
        "served_count": len(served_ids),
        "baseline": {
            "root": root_baseline,
            "points": [
                compact_point(states.get(kp_id), kp_id) for kp_id in touched_ids
            ],
        },
    }
