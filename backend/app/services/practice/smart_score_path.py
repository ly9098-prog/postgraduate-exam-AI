"""Score prerequisite evidence while preserving graph policy boundaries."""

from __future__ import annotations


def prerequisite_thresholds(graph_config: dict) -> tuple[float, float]:
    mastery = max(
        1.0, min(float(graph_config.get("prerequisite_mastery_threshold", 60.0)), 100.0)
    )
    confidence = max(
        0.0, min(float(graph_config.get("prerequisite_confidence_threshold", 0.3)), 1.0)
    )
    return mastery, confidence


def _blocked_penalty(
    kp_ids: list[int],
    blocked_kps: dict[int, list[dict]] | None,
) -> tuple[float, list[str]]:
    if blocked_kps is None or not kp_ids:
        return 0.0, []
    has_blocked = False
    blocked_quality = 0.0
    for kid in kp_ids:
        blockers = blocked_kps.get(kid) or []
        if blockers:
            has_blocked = True
            blocked_quality = max(
                blocked_quality,
                max(float(b.get("path_quality") or 0.0) for b in blockers),
            )
    if has_blocked:
        return 0.0 - 25 * blocked_quality, ["weak_prerequisite"]
    return 0.0, []


def _graph_bonus(graph: dict, mastery_threshold: float) -> float:
    path_quality = max(0.0, min(float(graph.get("path_quality") or 0.0), 1.0))
    raw_origin_mastery = graph.get("origin_mastery_score")
    raw_origin_conf = graph.get("origin_mastery_confidence")
    raw_prereq_mastery = graph.get("mastery_score")
    raw_prereq_conf = graph.get("mastery_confidence")
    origin_mastery = max(
        0.0,
        min(float(50.0 if raw_origin_mastery is None else raw_origin_mastery), 100.0),
    )
    origin_conf = max(
        0.0,
        min(float(0.0 if raw_origin_conf is None else raw_origin_conf), 1.0),
    )
    prereq_mastery = max(
        0.0,
        min(float(50.0 if raw_prereq_mastery is None else raw_prereq_mastery), 100.0),
    )
    prereq_conf = max(
        0.0,
        min(float(0.0 if raw_prereq_conf is None else raw_prereq_conf), 1.0),
    )
    origin_need = ((100.0 - origin_mastery) / 100.0) * origin_conf
    if graph.get("confirmed_gap"):
        prereq_gap = (
            max(0.0, (mastery_threshold - prereq_mastery) / mastery_threshold)
            * prereq_conf
        )
        return (
            45.0
            * (0.55 + 0.45 * origin_need)
            * (0.65 + 0.35 * prereq_gap)
            * path_quality
        )
    return 10.0 * (0.5 + 0.5 * origin_need) * path_quality


def _path_ready(
    kp_ids: list[int],
    blocked_kps: dict[int, list[dict]] | None,
    prerequisites_by_target: dict[int, list[dict]] | None,
    mastery_threshold: float,
    confidence_threshold: float,
) -> bool:
    if not (
        prerequisites_by_target
        and kp_ids
        and not any(k in (blocked_kps or {}) for k in kp_ids)
    ):
        return False
    for kid in kp_ids:
        direct_prereqs = [
            p
            for p in (prerequisites_by_target.get(kid) or [])
            if int(p.get("depth") or 0) == 1
        ]
        if direct_prereqs and all(
            not p.get("unknown_gap")
            and float(p.get("mastery_score") or 0.0) >= mastery_threshold
            and float(p.get("mastery_confidence") or 0.0) >= confidence_threshold
            for p in direct_prereqs
        ):
            return True
    return False


def score_prerequisite_path(
    kp_ids: list[int],
    blocked_kps: dict[int, list[dict]] | None,
    graph_candidates: dict[int, dict] | None,
    prerequisites_by_target: dict[int, list[dict]] | None,
    thresholds: tuple[float, float],
) -> tuple[float, list[str]]:
    total, reasons = _blocked_penalty(kp_ids, blocked_kps)
    mastery_threshold, confidence_threshold = thresholds
    if graph_candidates and kp_ids:
        best_bonus = 0.0
        for kid in kp_ids:
            graph = graph_candidates.get(kid)
            if graph:
                best_bonus = max(best_bonus, _graph_bonus(graph, mastery_threshold))
        if best_bonus > 0:
            total += best_bonus
            reasons.append("prerequisite_need")
    if _path_ready(
        kp_ids,
        blocked_kps,
        prerequisites_by_target,
        mastery_threshold,
        confidence_threshold,
    ):
        total += 8
        reasons.append("path_ready")
    return total, reasons
