"""Pure wording rules for graph, weakness and coverage recommendations."""

from __future__ import annotations


def first_kp_name(kp_ids: list[int], kp_names: dict[int, str]) -> str | None:
    return next((kp_names.get(k) for k in kp_ids if kp_names.get(k)), None)


def append_new_context(text: str, is_new: bool) -> str:
    if not is_new:
        return text
    return f"{text} 同时推荐一道尚未练过的新题，用来检验当前掌握情况。"


def graph_prerequisite_reason(
    kp_ids: list[int],
    kp_names: dict[int, str],
    graph_candidates: dict[int, dict],
    is_new: bool,
) -> str | None:
    for kp_id in kp_ids:
        graph = graph_candidates.get(kp_id)
        if not graph:
            continue
        kp_name = graph.get("name") or kp_names.get(kp_id) or "这个知识点"
        origin_name = graph.get("origin_name") or "目标知识点"
        if graph.get("confirmed_gap"):
            return append_new_context(
                f"你在「{origin_name}」上的掌握较弱，而「{kp_name}」是它的重要前置知识，建议先巩固「{kp_name}」。",
                is_new,
            )
        base = f"「{kp_name}」是「{origin_name}」的前置知识，目前掌握数据较少，这道题可用于快速确认基础是否扎实。"
        if is_new:
            return f"{base[:-1]}，并通过一道尚未练过的新题减少熟题记忆带来的干扰。"
        return base
    return None


def weak_knowledge_reason(
    name: str | None, is_new: bool, has_wrong_history: bool
) -> str:
    if name:
        if is_new:
            return f"你最近在「{name}」上的掌握度较低，推荐一道尚未练过的新题继续巩固并检验掌握情况。"
        if has_wrong_history:
            return f"你最近在「{name}」上的掌握度较低，而且之前在相关题目上出现过错误，建议继续巩固。"
        return f"你最近在「{name}」上的掌握度较低，这道题适合继续巩固。"
    if is_new:
        return "你最近在这类知识点上的掌握度较低，推荐一道尚未练过的新题继续巩固并检验掌握情况。"
    if has_wrong_history:
        return "你最近在这类知识点上的掌握度较低，而且之前在相关题目上出现过错误，建议继续巩固。"
    return "你最近在这类知识点上的掌握度较低，建议继续巩固。"


def observed_weakness_reason(
    name: str | None, is_new: bool, has_wrong_history: bool
) -> str:
    if name:
        if is_new:
            return f"你近期在「{name}」上的练习表现有待提升，推荐一道尚未练过的新题继续巩固并确认掌握情况。"
        if has_wrong_history:
            return f"你近期在「{name}」上的练习表现有待提升，而且之前在相关题目上出现过错误，建议继续巩固并确认掌握情况。"
        return f"你近期在「{name}」上的练习表现有待提升，这道题适合继续巩固并确认掌握情况。"
    if is_new:
        return "你近期在相关知识点上的练习表现有待提升，推荐一道尚未练过的新题继续巩固并确认掌握情况。"
    return "你近期在相关知识点上的练习表现有待提升，建议继续巩固并确认掌握情况。"


def blocked_target_reason(
    kp_ids: list[int],
    kp_names: dict[int, str],
    blocked_kps: dict[int, list[dict]],
    is_new: bool,
) -> str | None:
    for kp_id in kp_ids:
        blockers = blocked_kps.get(kp_id) or []
        if blockers:
            target_name = kp_names.get(kp_id) or "当前知识点"
            prereq_name = blockers[0].get("name") or "前置知识"
            return append_new_context(
                f"「{target_name}」仍需巩固，同时「{prereq_name}」这一前置知识也较薄弱，建议结合练习。",
                is_new,
            )
    return None


def coverage_reason(
    kp_ids: list[int],
    kp_names: dict[int, str],
    *,
    path_ready: bool,
    is_new: bool,
    is_diverse: bool,
    is_long_unpracticed: bool,
) -> str:
    if path_ready:
        name = first_kp_name(kp_ids, kp_names)
        if name:
            if is_new:
                return f"相关前置知识已经基本具备，可以继续巩固「{name}」；这道新题可用于检验能否顺利推进。"
            return f"相关前置知识已经基本具备，可以继续巩固「{name}」。"
    if is_new:
        if is_diverse:
            return "这是一道尚未练过的新题，同时用于补充近期练习的知识覆盖，检验当前掌握情况。"
        return "这是一道尚未练过的新题，用来检验当前掌握情况。"
    if is_long_unpracticed:
        if is_diverse:
            return (
                "这个知识点已有一段时间没有练习，同时近期覆盖较少，适合现在做一次巩固。"
            )
        return "这个知识点已有一段时间没有练习，适合现在做一次巩固。"
    if is_diverse:
        return "为避免重复刷同类题，这道题用于补充近期练习的知识覆盖。"
    return "根据你的近期答题表现和知识掌握情况推荐。"
