"""Read-time scope, chapter comparison and response projection without I/O."""

from __future__ import annotations

from collections.abc import Callable


def public_knowledge_session(context: dict | None) -> dict | None:
    if not isinstance(context, dict):
        return None
    root_id = int(context.get("root_id") or 0)
    if root_id <= 0:
        return None
    return {
        "practice_mode": str(context.get("practice_mode") or "knowledge_point"),
        "root_knowledge_point_id": root_id,
        "root_name": str(context.get("root_name") or ""),
        "include_descendants": bool(context.get("include_descendants")),
        "knowledge_point_count": max(1, int(context.get("scope_count") or 1)),
    }


def summary_scope(
    persisted: dict | None, knowledge_session: object
) -> tuple[dict | None, str]:
    if persisted is not None:
        scope = {
            "root_knowledge_point_id": int(persisted["root_knowledge_point_id"]),
            "root_name": str(persisted.get("root_name") or ""),
            "include_descendants": bool(persisted.get("include_descendants")),
            "knowledge_point_count": max(
                1, int(persisted.get("resolved_knowledge_point_count") or 1)
            ),
        }
        mode = str(persisted.get("practice_mode") or "knowledge_point")
    elif isinstance(knowledge_session, dict):
        # Sessions predating durable scopes retain the canonical replay fallback.
        scope = {
            "root_knowledge_point_id": int(
                knowledge_session.get("root_knowledge_point_id") or 0
            ),
            "root_name": str(knowledge_session.get("root_name") or ""),
            "include_descendants": bool(knowledge_session.get("include_descendants")),
            "knowledge_point_count": max(
                1, int(knowledge_session.get("knowledge_point_count") or 1)
            ),
        }
        mode = str(knowledge_session.get("practice_mode") or "knowledge_point")
    else:
        return None, "general"
    return scope, mode


def summary_response(
    request_id: str,
    practice_mode: str,
    scope: dict | None,
    *,
    status: str = "ready",
    pending_count: int = 0,
    chapter: dict | None = None,
    touched_count: int = 0,
    points: list | None = None,
) -> dict:
    return {
        "request_id": request_id,
        "status": status,
        "practice_mode": practice_mode,
        "projection_pending_count": pending_count,
        "scope": scope,
        "chapter": chapter,
        "touched_knowledge_point_count": touched_count,
        "points": points if points is not None else [],
    }


def _chapter_before(root_baseline: list | None) -> tuple:
    mastery = root_baseline[0] if root_baseline and len(root_baseline) > 0 else None
    coverage = (
        float(root_baseline[1] or 0.0)
        if root_baseline and len(root_baseline) > 1
        else 0.0
    )
    weak = int(root_baseline[2] or 0) if root_baseline and len(root_baseline) > 2 else 0
    reliable = (
        int(root_baseline[3] or 0) if root_baseline and len(root_baseline) > 3 else 0
    )
    return mastery, coverage, weak, reliable


def project_chapter(
    detail: dict | None,
    root_baseline: list | None,
    scope: dict,
    root_id: int,
    *,
    number: Callable,
    delta: Callable,
) -> dict | None:
    if detail is None:
        return None
    is_chapter = bool(scope["include_descendants"])
    after_mastery = (
        detail.get("subtree_mastery_score")
        if is_chapter
        else detail.get("mastery_score")
    )
    after_coverage = (
        float(detail.get("subtree_coverage_ratio", 0.0) or 0.0)
        if is_chapter
        else (1.0 if detail.get("status") not in {"no_data", "insufficient"} else 0.0)
    )
    before_mastery, before_coverage, before_weak, before_reliable = _chapter_before(
        root_baseline
    )
    trainable = (
        int(detail.get("subtree_trainable_knowledge_points", 0) or 0)
        if is_chapter
        else (1 if int(detail.get("trainable_question_count", 0) or 0) > 0 else 0)
    )
    return {
        "root_knowledge_point_id": root_id,
        "root_name": str(scope["root_name"] or detail.get("name") or ""),
        "mastery_before": number(before_mastery),
        "mastery_after": number(after_mastery),
        "mastery_delta": delta(before_mastery, after_mastery),
        "coverage_before": round(before_coverage, 4),
        "coverage_after": round(after_coverage, 4),
        "weak_before": before_weak,
        "weak_after": int(detail.get("subtree_weak_knowledge_points", 0) or 0)
        if is_chapter
        else (1 if detail.get("status") == "weak" else 0),
        "reliable_before": before_reliable,
        "reliable_after": int(detail.get("subtree_reliable_knowledge_points", 0) or 0)
        if is_chapter
        else (1 if detail.get("status") not in {"no_data", "insufficient"} else 0),
        "trainable_knowledge_points": trainable,
    }
