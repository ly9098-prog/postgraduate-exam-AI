"""Pure ranking logic for knowledge chapter diagnosis.

This module intentionally has no database/model imports so recommendation ranking
can be unit-tested without booting the async SQLAlchemy application.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

_DEFAULT_QUESTION_COUNT = 10
_MAX_RECOMMENDATIONS = 3
_CANDIDATE_MAX_DEPTH = 2


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _accuracy(correct: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(correct / total, 4)


def _days_since(value: datetime | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    delta = now - value
    return max(0, int(delta.total_seconds() // 86400))


def _chapter_kind(node: dict, chapter_stat: dict, *, now: datetime) -> str:
    status = str(node.get("subtree_status") or "no_data")
    coverage = max(0.0, min(1.0, _float(node.get("subtree_coverage_ratio"))))
    reliable = _int(node.get("subtree_reliable_knowledge_points"))
    weak = _int(node.get("subtree_weak_knowledge_points"))
    mastery = node.get("subtree_mastery_score")
    mastery_value = _float(mastery) if mastery is not None else None
    days = _days_since(chapter_stat.get("last_practiced_at"), now=now)

    if status in {"no_data", "insufficient"} or reliable <= 0 or coverage < 0.35:
        return "build"
    if weak > 0 or (mastery_value is not None and mastery_value < 65.0):
        return "strengthen"
    if days is not None and days >= 14:
        return "review"
    return "maintain"


def _priority_score(node: dict, chapter_stat: dict, *, now: datetime) -> float:
    coverage = max(0.0, min(1.0, _float(node.get("subtree_coverage_ratio"))))
    weak = _int(node.get("subtree_weak_knowledge_points"))
    mastery = node.get("subtree_mastery_score")
    mastery_value = _float(mastery) if mastery is not None else None
    status = str(node.get("subtree_status") or "no_data")
    session_count = _int(chapter_stat.get("session_count"))
    days = _days_since(chapter_stat.get("last_practiced_at"), now=now)
    depth = _int(node.get("depth"))

    score = (1.0 - coverage) * 30.0
    score += min(5, weak) * 5.0
    if mastery_value is None:
        score += 20.0
    else:
        score += max(0.0, 72.0 - mastery_value) * 0.75
    if status in {"no_data", "insufficient"}:
        score += 12.0
    if session_count <= 0:
        score += 10.0
    elif days is not None and days >= 21:
        score += 12.0
    elif days is not None and days >= 14:
        score += 8.0
    elif days is not None and days <= 2:
        score -= 8.0

    score += min(depth, _CANDIDATE_MAX_DEPTH) * 2.0
    return round(max(0.0, score), 2)


def _recommendation_copy(
    kind: str, node: dict, chapter_stat: dict, *, now: datetime
) -> tuple[str, str, str]:
    name = str(node.get("name") or "知识章节")
    coverage = round(
        max(0.0, min(1.0, _float(node.get("subtree_coverage_ratio")))) * 100
    )
    reliable = _int(node.get("subtree_reliable_knowledge_points"))
    trainable = _int(node.get("subtree_trainable_knowledge_points"))
    weak = _int(node.get("subtree_weak_knowledge_points"))
    mastery = node.get("subtree_mastery_score")
    mastery_text = (
        f"{round(_float(mastery))}%" if mastery is not None else "尚未形成可靠判断"
    )
    days = _days_since(chapter_stat.get("last_practiced_at"), now=now)

    if kind == "build":
        return (
            f"建立「{name}」知识覆盖",
            f"当前可靠覆盖 {coverage}%，{reliable}/{trainable} 个可练知识点已建立可靠证据，建议先完成一轮章节专项。",
            "开始建立覆盖",
        )
    if kind == "strengthen":
        weak_text = f"，子树内仍有 {weak} 个薄弱知识点" if weak > 0 else ""
        return (
            f"优先强化「{name}」",
            f"当前章节掌握度约 {mastery_text}{weak_text}，适合集中练习后再观察章节聚合变化。",
            "开始弱项强化",
        )
    if kind == "review":
        day_text = (
            f"最近一次章节练习已过去 {days} 天"
            if days is not None
            else "近期没有章节专项记录"
        )
        return (
            f"复习「{name}」保持稳定",
            f"当前章节掌握度约 {mastery_text}，{day_text}，建议用一组题恢复提取强度。",
            "开始章节复习",
        )
    return (
        f"继续巩固「{name}」",
        f"当前章节掌握度约 {mastery_text}、可靠覆盖 {coverage}%，可用少量练习维持稳定。",
        "继续巩固",
    )


def _overlaps(candidate: dict, selected: dict) -> bool:
    candidate_id = _int(candidate.get("knowledge_point_id"))
    selected_id = _int(selected.get("knowledge_point_id"))
    candidate_ancestors = {_int(value) for value in candidate.get("ancestor_ids") or []}
    selected_ancestors = {_int(value) for value in selected.get("ancestor_ids") or []}
    return selected_id in candidate_ancestors or candidate_id in selected_ancestors


def rank_chapter_recommendations(
    nodes: list[dict],
    chapter_stats: dict[int, dict],
    *,
    subject_id: int,
    now: datetime,
    limit: int = _MAX_RECOMMENDATIONS,
) -> list[dict]:
    """Rank actionable, preferably non-overlapping chapter recommendations."""
    candidates: list[dict] = []
    for node in nodes:
        if not bool(node.get("has_children")):
            continue
        if _int(node.get("depth")) > _CANDIDATE_MAX_DEPTH:
            continue
        if _int(node.get("subtree_trainable_knowledge_points")) <= 0:
            continue
        kp_id = _int(node.get("knowledge_point_id"))
        stat = chapter_stats.get(kp_id, {})
        candidates.append(
            {
                **node,
                "_priority_score": _priority_score(node, stat, now=now),
                "_chapter_stat": stat,
            }
        )

    candidates.sort(
        key=lambda item: (
            -_float(item.get("_priority_score")),
            -_int(item.get("depth")),
            _int(item.get("knowledge_point_id")),
        )
    )

    selected: list[dict] = []
    for candidate in candidates:
        if any(_overlaps(candidate, prior) for prior in selected):
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        selected_ids = {_int(item.get("knowledge_point_id")) for item in selected}
        for candidate in candidates:
            if _int(candidate.get("knowledge_point_id")) in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(_int(candidate.get("knowledge_point_id")))
            if len(selected) >= limit:
                break

    result: list[dict] = []
    for rank, node in enumerate(selected, start=1):
        kp_id = _int(node.get("knowledge_point_id"))
        stat = node.get("_chapter_stat") or {}
        kind = _chapter_kind(node, stat, now=now)
        title, reason, action_label = _recommendation_copy(kind, node, stat, now=now)
        mastery = node.get("subtree_mastery_score")
        last_at = stat.get("last_practiced_at")
        result.append(
            {
                "rank": rank,
                "kind": kind,
                "knowledge_point_id": kp_id,
                "knowledge_point_name": str(node.get("name") or ""),
                "depth": _int(node.get("depth")),
                "priority_score": _float(node.get("_priority_score")),
                "title": title,
                "reason": reason,
                "action_label": action_label,
                "mastery_score": round(_float(mastery), 1)
                if mastery is not None
                else None,
                "coverage_ratio": round(
                    max(0.0, min(1.0, _float(node.get("subtree_coverage_ratio")))), 4
                ),
                "weak_knowledge_points": _int(
                    node.get("subtree_weak_knowledge_points")
                ),
                "trainable_knowledge_points": _int(
                    node.get("subtree_trainable_knowledge_points")
                ),
                "reliable_knowledge_points": _int(
                    node.get("subtree_reliable_knowledge_points")
                ),
                "last_chapter_practiced_at": last_at.isoformat() + "Z"
                if isinstance(last_at, datetime)
                else None,
                "chapter_session_count": _int(stat.get("session_count")),
                "route": "practice",
                "route_params": {
                    "subject_id": int(subject_id),
                    "mode": "random",
                    "count": _DEFAULT_QUESTION_COUNT,
                    "knowledge_point_id": kp_id,
                    "include_descendants": 1,
                    "include_children": 1,
                    "allow_repeat": 1,
                    "autostart": 1,
                    "source": "knowledge_diagnosis",
                },
            }
        )
    return result


def _scope_coverage(served_count: int, resolved_count: int) -> float | None:
    if resolved_count <= 0:
        return None
    return round(max(0.0, min(1.0, served_count / resolved_count)), 4)


def _empty_chapter_stat() -> dict:
    return {
        "session_count": 0,
        "recent_session_count": 0,
        "question_count": 0,
        "correct_count": 0,
        "last_practiced_at": None,
        "served_ids": set(),
        "resolved_ids": set(),
        "scope_served_count": 0,
        "scope_resolved_count": 0,
    }


def aggregate_session_stats(
    nodes: list[dict],
    sessions: list[dict],
    *,
    recent_since: datetime | None = None,
) -> tuple[dict[int, dict], dict]:
    """Attribute a scoped session to its root and every current ancestor.

    A session rooted at ``链表`` therefore contributes to the period report for
    both ``链表`` and its top-level ancestor ``线性表`` without pretending the
    historical session itself was rooted at ``线性表``.
    """
    node_by_id = {_int(node.get("knowledge_point_id")): node for node in nodes}
    stats: dict[int, dict] = {}
    total_questions = 0
    total_correct = 0
    unique_served: set[int] = set()
    unique_resolved: set[int] = set()
    scope_served_count = 0
    scope_resolved_count = 0
    recent_session_count = 0

    for session in sessions:
        root_id = _int(session.get("root_knowledge_point_id"))
        root_node = node_by_id.get(root_id)
        target_ids = [root_id]
        if root_node is not None:
            target_ids.extend(
                _int(value) for value in root_node.get("ancestor_ids") or []
            )
        question_count = _int(session.get("question_count"))
        correct_count = _int(session.get("correct_count"))
        finished_at = session.get("finished_at")
        served_ids = set(session.get("served_ids") or set())
        resolved_ids = set(session.get("resolved_ids") or set())
        served_count = max(0, _int(session.get("served_count"), len(served_ids)))
        resolved_count = max(0, _int(session.get("resolved_count"), len(resolved_ids)))
        is_recent = bool(
            recent_since is not None
            and isinstance(finished_at, datetime)
            and finished_at >= recent_since
        )
        total_questions += question_count
        total_correct += correct_count
        unique_served.update(served_ids)
        unique_resolved.update(resolved_ids)
        scope_served_count += served_count
        scope_resolved_count += resolved_count
        if is_recent:
            recent_session_count += 1

        for target_id in dict.fromkeys(value for value in target_ids if value > 0):
            stat = stats.setdefault(target_id, _empty_chapter_stat())
            stat["session_count"] += 1
            if is_recent:
                stat["recent_session_count"] += 1
            stat["question_count"] += question_count
            stat["correct_count"] += correct_count
            stat["served_ids"].update(served_ids)
            stat["resolved_ids"].update(resolved_ids)
            stat["scope_served_count"] += served_count
            stat["scope_resolved_count"] += resolved_count
            if isinstance(finished_at, datetime) and (
                stat["last_practiced_at"] is None
                or finished_at > stat["last_practiced_at"]
            ):
                stat["last_practiced_at"] = finished_at

    return stats, {
        "session_count": len(sessions),
        "recent_session_count": recent_session_count,
        "question_count": total_questions,
        "correct_count": total_correct,
        "served_ids": unique_served,
        "resolved_ids": unique_resolved,
        "scope_served_count": scope_served_count,
        "scope_resolved_count": scope_resolved_count,
        "scope_coverage_ratio": _scope_coverage(
            scope_served_count, scope_resolved_count
        ),
    }
